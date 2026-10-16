"""Age-aware desktop delivery; late historical QA alerts wait for off-site hours.

Never changes REG source or existing surveyor cutoff/deduplication rules.
Default (no site schedule) is fail-closed: assume surveyors are on site,
but CURRENT-DAY gap notifications continue immediately.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os
import shutil
import tempfile

RWANDA_TZ=timezone(timedelta(hours=2))
MAX_LATE_PER_CYCLE=5
SCHEMA="""
CREATE TABLE IF NOT EXISTS delayed_qa_notifications(
  asset TEXT NOT NULL,
  objectid INTEGER NOT NULL,
  globalid TEXT NOT NULL,
  event_time_utc_ms INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  queued_utc_ms INTEGER NOT NULL,
  PRIMARY KEY(asset,objectid,globalid)
);
"""


def site_active(config, now_ms):
    """Fail closed to ON-SITE unless a valid explicit site mode/schedule exists."""
    mode=config.get("surveyor_site_mode","on_site")
    if mode=="on_site":
        return True
    if mode=="off_site":
        return False
    if mode!="schedule":
        raise ValueError("Unknown surveyor site mode.")
    schedule=config.get("surveyor_site_schedule")
    if not isinstance(schedule,dict):
        return True
    try:
        weekdays=schedule["weekdays"]
        if not isinstance(weekdays,list) or any(
            type(v) is not int or not 0<=v<=6 for v in weekdays
        ):
            return True
        def minutes(value):
            h,m=map(int,str(value).split(":"))
            if not 0<=h<=23 or not 0<=m<=59:
                raise ValueError("Bad site hour.")
            return h*60+m
        start=minutes(schedule["start"])
        end=minutes(schedule["end"])
        if start>=end:
            return True  # overnight shifts need explicit manual handling
        local=datetime.fromtimestamp(now_ms/1000,RWANDA_TZ)
        return local.weekday() in weekdays and (
            start<=local.hour*60+local.minute<end
        )
    except (ValueError,TypeError,KeyError,OverflowError):
        return True


def is_historical(event_ms, now_ms):
    """Older than today's Kigali calendar date, never by UTC midnight."""
    return datetime.fromtimestamp(int(event_ms)/1000,RWANDA_TZ).date() < (
        datetime.fromtimestamp(int(now_ms)/1000,RWANDA_TZ).date()
    )


def ensure_schema(db):
    db.executescript(SCHEMA)
    db.commit()


def _key(item):
    return (str(item["asset"]),int(item["objectid"]),str(item["globalid"]))


def _current(db, item):
    key=_key(item)
    row=db.execute(
        """SELECT payload_json FROM delayed_qa_notifications
        WHERE asset=? AND objectid=? AND globalid=?""", key
    ).fetchone()
    return json.loads(row[0]) if row else None


def _put(db,item,now_ms):
    db.execute("""INSERT INTO delayed_qa_notifications
     (asset,objectid,globalid,event_time_utc_ms,payload_json,queued_utc_ms)
     VALUES(?,?,?,?,?,?)
     ON CONFLICT(asset,objectid,globalid) DO UPDATE SET
       event_time_utc_ms=excluded.event_time_utc_ms,
       payload_json=excluded.payload_json
    """,(
        *_key(item),int(item["event_time_utc_ms"]),
        json.dumps(item,ensure_ascii=False),int(now_ms),
    ))
    db.commit()


def _remove(db,item):
    db.execute("""DELETE FROM delayed_qa_notifications
        WHERE asset=? AND objectid=? AND globalid=?""",_key(item))
    db.commit()


def plan_delivery(notices, snapshots, config, now_ms, db):
    """Partition urgent/new and previous-day alerts, queue until crew off-site.

    Returns (deliveries, count_queued). Failed deliveries stay queued.
    When a deferred feature reappears in the fresh scan, discard stale
    queued issues if they have been fixed or if its latest editor changed.
    """
    ensure_schema(db)
    current={_key(x):x for x in notices}
    current_features={
        (asset,int(r["OBJECTID"]),str(r.get("GLOBALID") or "")):r
        for asset,(records,*_) in snapshots.items() for r in records
        if r.get("OBJECTID") is not None and r.get("GLOBALID")
    }
    # Previous-day issues are kept on disk even if the moving 24h query
    # drops the feature before the crew leave site.
    for item in notices:
        if is_historical(item["event_time_utc_ms"],now_ms):
            _put(db,item,now_ms)
    pending=[
        json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM delayed_qa_notifications ORDER BY queued_utc_ms ASC"
        ).fetchall()
    ]
    for item in pending:
        key=_key(item)
        if key in current_features and key not in current:
            # Source is currently clean/unwatched/changed: no stale old alert.
            _remove(db,item)
    if site_active(config,now_ms):
        deliveries=[
            item for item in notices
            if not is_historical(item["event_time_utc_ms"],now_ms)
        ]
        return deliveries,db.execute(
            "SELECT COUNT(*) FROM delayed_qa_notifications").fetchone()[0]
    # At off-site hours, deliver stored historical alerts in small batches
    # along with today's urgent alerts. Never double-notify same event.
    normal=[
        item for item in notices
        if not is_historical(item["event_time_utc_ms"],now_ms)
    ]
    pending=[
        json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM delayed_qa_notifications ORDER BY queued_utc_ms ASC LIMIT ?",
            (MAX_LATE_PER_CYCLE,)
        ).fetchall()
    ]
    return normal + pending,db.execute(
        "SELECT COUNT(*) FROM delayed_qa_notifications").fetchone()[0]


def mark_delivered(db,item):
    ensure_schema(db)
    _remove(db,item)


def change_site_mode(config_path,mode,*,schedule=None):
    """Supervisor config edit with backup, no monitor reset or REG writes."""
    if mode not in ("on_site","off_site","schedule"):
        raise ValueError("Site mode must be on_site, off_site, or schedule.")
    path=Path(config_path).expanduser().resolve()
    conf=json.loads(path.read_text(encoding="utf-8"))
    if not conf.get("enabled") or not conf.get("usernames"):
        raise ValueError("Incomplete watcher configuration.")
    changed=dict(conf)
    changed["surveyor_site_mode"]=mode
    if schedule is not None:
        changed["surveyor_site_schedule"]=schedule
    # Check schedule without assuming a time of day.
    if mode=="schedule":
        check=dict(changed)
        info=check.get("surveyor_site_schedule")
        if not isinstance(info,dict) or not all(k in info for k in ("start","end","weekdays")):
            raise ValueError("Specify work start/end HH:MM and weekdays.")
        # Validation rejects unexpected/overnight schedule values.
        def validate_times(value):
            pieces=str(value).split(":")
            if len(pieces)!=2 or not all(part.isdigit() for part in pieces):
                raise ValueError("Site hours must use HH:MM.")
            h,m=map(int,pieces)
            if not 0<=h<=23 or not 0<=m<=59:
                raise ValueError("Site hours out of range.")
            return h*60+m
        if validate_times(info["start"])>=validate_times(info["end"]):
            raise ValueError("Site end must be after start.")
        days=info["weekdays"]
        if not isinstance(days,list) or any(type(d) is not int or d not in range(7) for d in days):
            raise ValueError("Invalid site weekdays.")
    if conf==changed:
        return {"status":"UNCHANGED","site_mode":mode}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup=path.with_name(path.stem+"_backup_site_"+stamp+".json")
    shutil.copy2(path,backup)
    temp=None
    try:
        with tempfile.NamedTemporaryFile("w",encoding="utf-8",
             dir=path.parent,prefix=".site_mode_",suffix=".tmp",delete=False) as f:
            temp=Path(f.name)
            json.dump(changed,f,indent=2,ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return {"status":"UPDATED","site_mode":mode,"backup":str(backup)}

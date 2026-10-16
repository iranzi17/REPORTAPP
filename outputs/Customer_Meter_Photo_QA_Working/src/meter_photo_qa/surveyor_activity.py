"""Optional clean-record notifications and watcher heartbeat for REPORTAPP.

Runs inside the EXISTING one-minute surveyor watcher only after explicit
activation. Existing QA alerts, surveys, and source REG data are unchanged.
Activity is based on a qualifying *source edit event*, not the number of
features returned by the moving 24-hour service query.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

DEFAULT_HEARTBEAT_MINUTES=60
CLEAN_DIGEST_INTERVAL_MINUTES=30
MAX_NEW_CLEAN_EVENTS_PER_SCAN=1000
AGE_SECONDS=300
MAX_LOOKBACK_MS=24*3600*1000

ACTIVITY_SCHEMA="""
CREATE TABLE IF NOT EXISTS clean_surveyor_activity (
    asset TEXT NOT NULL,
    objectid INTEGER NOT NULL,
    globalid TEXT NOT NULL,
    source_event_ms INTEGER NOT NULL,
    username TEXT NOT NULL,
    event_type TEXT NOT NULL,
    notified_at_ms INTEGER NOT NULL,
    PRIMARY KEY(asset,objectid,globalid,source_event_ms)
);
CREATE TABLE IF NOT EXISTS monitor_heartbeat (
    id INTEGER PRIMARY KEY CHECK(id=1),
    notified_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS delayed_clean_activity(
    asset TEXT NOT NULL,
    objectid INTEGER NOT NULL,
    globalid TEXT NOT NULL,
    event_time_utc_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    queued_at_utc_ms INTEGER NOT NULL,
    PRIMARY KEY(asset,objectid,globalid,event_time_utc_ms)
);
CREATE TABLE IF NOT EXISTS pending_clean_digest(
    asset TEXT NOT NULL,
    objectid INTEGER NOT NULL,
    globalid TEXT NOT NULL,
    event_time_utc_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    queued_at_utc_ms INTEGER NOT NULL,
    PRIMARY KEY(asset,objectid,globalid,event_time_utc_ms)
);
CREATE TABLE IF NOT EXISTS clean_digest_clock(
    id INTEGER PRIMARY KEY CHECK(id=1),
    last_digest_ms INTEGER NOT NULL
);
"""


def ensure_schema(db):
    db.executescript(ACTIVITY_SCHEMA)
    db.commit()


def _cutoff(config,asset,username):
    base=int(config["enabled_at_utc_ms"])
    return max(
        base,
        int(config["activity_notifications_enabled_at_utc_ms"]),
        int((config.get("enabled_at_by_username_utc_ms") or {}).get(username.casefold(),base)),
        int((config.get("enabled_at_by_asset_utc_ms") or {}).get(asset,base)),
    )


def clean_activity_candidates(snapshots, config, now_ms, db):
    """Newly created/edited, QA-clean, watched source events; no historical replay."""
    from .surveyor_notifications import (
        event_timestamp, submission_actor, record_findings,
    )
    ensure_schema(db)
    if not config.get("activity_notifications_enabled"):
        return []
    watched={str(u).casefold() for u in config["usernames"]}
    pending=[]
    for asset,(records,fields,domains,rules,expectations) in snapshots.items():
        for attrs in records:
            oid=attrs.get("OBJECTID")
            gid=str(attrs.get("GLOBALID") or "").strip()
            username,event_type=submission_actor(attrs)
            event_ms=event_timestamp(attrs)
            if (username.casefold() not in watched or oid is None or not gid
                    or event_ms is None or event_ms>now_ms-AGE_SECONDS*1000
                    or event_ms<now_ms-MAX_LOOKBACK_MS):
                continue
            if event_ms<_cutoff(config,asset,username):
                continue
            key=(asset,int(oid),gid,int(event_ms))
            already=db.execute("""
                SELECT 1 FROM clean_surveyor_activity
                WHERE asset=? AND objectid=? AND globalid=? AND source_event_ms=?
            """,key).fetchone()
            pending_exists=db.execute("""
                SELECT 1 FROM pending_clean_digest
                WHERE asset=? AND objectid=? AND globalid=? AND event_time_utc_ms=?
            """,key).fetchone()
            historical_pending=db.execute("""
                SELECT 1 FROM delayed_clean_activity
                WHERE asset=? AND objectid=? AND globalid=? AND event_time_utc_ms=?
            """,key).fetchone()
            if already or pending_exists or historical_pending:
                continue
            issues,unverified=record_findings(
                asset,attrs,fields,domains,rules,expectations
            )
            if unverified:
                raise RuntimeError(
                    f"{asset}: cannot issue CLEAN notification; unverified "
                    f"mandatory schema checks: {unverified}"
                )
            if issues:
                continue  # Existing quality alert path owns flagged records.
            pending.append({
                "asset":asset,"objectid":int(oid),"globalid":gid,
                "username":username,"event_type":event_type,
                "event_time_utc_ms":int(event_ms),"issues":[],
                "notification_kind":"CLEAN_ACTIVITY",
            })
    # Process oldest unsent events first to avoid starvation in busy sites.
    pending.sort(key=lambda a:(a["event_time_utc_ms"],a["asset"],a["objectid"]))
    return pending


def record_clean_activity(db,entry,now_ms):
    ensure_schema(db)
    db.execute("""
        INSERT OR IGNORE INTO clean_surveyor_activity
        (asset,objectid,globalid,source_event_ms,username,event_type,notified_at_ms)
        VALUES(?,?,?,?,?,?,?)
    """,(
        entry["asset"],entry["objectid"],entry["globalid"],
        entry["event_time_utc_ms"],entry["username"],entry["event_type"],
        int(now_ms),
    ))
    db.commit()


def list_recent_activity(db, limit=100):
    ensure_schema(db)
    return [dict(zip(
        ("asset","objectid","globalid","event_time_utc_ms",
         "username","event_type","notified_at_ms"),r
    )) for r in db.execute("""
        SELECT asset,objectid,globalid,source_event_ms,username,event_type,notified_at_ms
        FROM clean_surveyor_activity
        ORDER BY notified_at_ms DESC,source_event_ms DESC LIMIT ?
    """,(max(1,min(int(limit),500)),)).fetchall()]


def deliver_clean_activity(entry,config):
    """One Windows toast per verified clean CREATE/EDIT, with zoom URI."""
    if config.get("channel","desktop")!="desktop":
        # Explicitly disallow misleading mixed channels for this pilot.
        raise RuntimeError("Clean activity notifications currently require the desktop channel.")
    from winotify import Notification
    from .alert_navigation import is_registered,zoom_uri
    kind="created" if entry["event_type"]=="CREATE" else "edited"
    historical=bool(entry.get("deferred_historical"))
    title=(
        f"REG QA HISTORICAL: {entry['asset'].upper()} — no gaps at scan"
        if historical else
        f"REG QA CHECKED: {entry['asset'].upper()} — no gaps found"
    )
    original=datetime.fromtimestamp(
        int(entry["event_time_utc_ms"])/1000,timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    message=(
        f"{entry['username']} {kind} OBJECTID {entry['objectid']}.\n"
        f"Source event: {original}.\n"
        +("Historical event; verify current condition before relying on it. "
          if historical else "")
        +"No outstanding issues in REPORTAPP's verified QA rules. "
        "No REG source data changed."
    )
    launch=(zoom_uri(entry["asset"],entry["objectid"]) if is_registered() else "")
    popup=Notification(
        app_id="REPORTAPP Surveyor Activity",title=title,
        msg=message,duration="long",launch=launch,
    )
    if launch:
        popup.add_actions(label="Zoom in ArcGIS Pro",launch=launch)
    popup.show()


def deliver_activity_test(asset,objectid):
    """Explicitly marked GUI/zoom test: no QA evaluation and no state writes."""
    from winotify import Notification
    from .alert_navigation import is_registered,zoom_uri
    uri=zoom_uri(asset,objectid)  # validates asset and positive OBJECTID
    launch=uri if is_registered() else ""
    popup=Notification(
        app_id="REPORTAPP Surveyor Activity",
        title="REPORTAPP TEST — activity notification",
        msg=(
            "Test popup only: no REG feature was evaluated or marked clean. "
            f"Zoom target: {asset} OBJECTID {objectid}."
        ),
        duration="long",launch=launch,
    )
    if launch:
        popup.add_actions(label="Zoom in ArcGIS Pro (TEST)",launch=launch)
    popup.show()


def _recent_count(snapshots,config,now_ms,minutes):
    from .surveyor_notifications import event_timestamp,submission_actor
    threshold=now_ms-minutes*60*1000
    users={str(u).casefold() for u in config["usernames"]}
    count=0
    for asset,(records,*_rest) in snapshots.items():
        for item in records:
            user,_action=submission_actor(item)
            ms=event_timestamp(item)
            if (ms is not None and user.casefold() in users
                    and max(_cutoff(config,asset,user),threshold)<=ms<=now_ms):
                count+=1
    return count


def heartbeat_due(db,config,now_ms):
    ensure_schema(db)
    minutes=int(config.get("activity_heartbeat_minutes",DEFAULT_HEARTBEAT_MINUTES))
    if not 10<=minutes<=240:
        raise ValueError("Activity heartbeat interval must be 10–240 minutes.")
    since=int(config.get("activity_notifications_enabled_at_utc_ms",now_ms))
    if now_ms<since+minutes*60000:
        return False
    row=db.execute("SELECT notified_at_ms FROM monitor_heartbeat WHERE id=1").fetchone()
    return not row or now_ms-int(row[0])>=minutes*60000


def deliver_heartbeat(stats,config):
    if config.get("channel","desktop")!="desktop":
        raise RuntimeError("Watcher heartbeat currently requires desktop notifications.")
    from winotify import Notification
    scans=stats["records_scanned"]
    message=(
        "Surveyor watcher active. "
        f"24h candidate scan: {scans.get('pole',0)} poles, "
        f"{scans.get('line',0)} lines, {scans.get('transformer',0)} transformers.\n"
        f"New/edited by selected surveyors in last "
        f"{stats['period_minutes']} min: {stats['recent_events']}.\n"
        f"QA gap alerts this scan: {stats['qa_alerts_sent']}. "
        f"Clean checks notified this scan: {stats['clean_notifications_sent']}."
    )
    Notification(
        app_id="REPORTAPP Surveyor Activity",
        title="REPORTAPP watcher healthy — periodic scan summary",
        msg=message,duration="long",
    ).show()


def record_heartbeat(db,now_ms):
    ensure_schema(db)
    db.execute("""
        INSERT INTO monitor_heartbeat(id,notified_at_ms) VALUES(1,?)
        ON CONFLICT(id) DO UPDATE SET notified_at_ms=excluded.notified_at_ms
    """,(int(now_ms),))
    db.commit()


def _queue_old_clean(db,entry,now_ms):
    db.execute("""
        INSERT OR IGNORE INTO delayed_clean_activity
        (asset,objectid,globalid,event_time_utc_ms,payload_json,queued_at_utc_ms)
        VALUES(?,?,?,?,?,?)
    """,(
        entry["asset"],int(entry["objectid"]),entry["globalid"],
        int(entry["event_time_utc_ms"]),json.dumps(entry,ensure_ascii=False),
        int(now_ms),
    ))
    db.commit()


def _remove_delayed_clean(db,entry):
    db.execute("""
        DELETE FROM delayed_clean_activity
        WHERE asset=? AND objectid=? AND globalid=? AND event_time_utc_ms=?
    """,(
        entry["asset"],int(entry["objectid"]),entry["globalid"],
        int(entry["event_time_utc_ms"]),
    ))
    db.commit()


def _pending_key(item):
    return (
        item["asset"],int(item["objectid"]),item["globalid"],
        int(item["event_time_utc_ms"]),
    )


def _queue_digest(db,item,now_ms):
    db.execute("""
        INSERT OR IGNORE INTO pending_clean_digest
        (asset,objectid,globalid,event_time_utc_ms,payload_json,queued_at_utc_ms)
        VALUES(?,?,?,?,?,?)
    """,(*_pending_key(item),json.dumps(item,ensure_ascii=False),int(now_ms)))
    db.commit()


def _drop_digest(db,item):
    db.execute("""
        DELETE FROM pending_clean_digest
        WHERE asset=? AND objectid=? AND globalid=? AND event_time_utc_ms=?
    """,_pending_key(item))
    db.commit()


def _clean_digest_due(db,now_ms):
    """Initialize a persistent 30-minute clock without an immediate burst."""
    db.execute("""
        INSERT OR IGNORE INTO clean_digest_clock(id,last_digest_ms) VALUES(1,?)
    """,(int(now_ms),))
    db.commit()
    row=db.execute("SELECT last_digest_ms FROM clean_digest_clock WHERE id=1").fetchone()
    return now_ms-int(row[0]) >= CLEAN_DIGEST_INTERVAL_MINUTES*60000


def deliver_clean_digest(summary,config):
    """ONE Windows popup for ALL verified clean events in the digest."""
    if config.get("channel","desktop")!="desktop":
        raise RuntimeError("Clean activity digest requires desktop delivery.")
    from winotify import Notification
    counts=summary["by_asset"]
    parts=[
        f"{counts.get('pole',0)} poles",
        f"{counts.get('line',0)} lines",
        f"{counts.get('transformer',0)} transformers",
    ]
    title=f"REG QA: {summary['total']} no-gap records / 30 minutes"
    msg=(
        "Verified checks passed: "+", ".join(parts)+".\n"
        f"Surveyors: {summary['surveyor_count']}; "
        f"created: {summary['created']}; edited: {summary['edited']}.\n"
        +(
            f"Historical/off-site: {summary['historical']}. "
            if summary["historical"] else ""
        )
        +"For individual OBJECTIDs and zoom, open Clean Activity History in REPORTAPP."
    )
    Notification(
        app_id="REPORTAPP Surveyor Activity",title=title,
        msg=msg,duration="long",
    ).show()


def process_activity(snapshots,config,now_ms,db,stats,
                     clean_sender=None,heartbeat_sender=None):
    """Queue all passing checks, then show at most ONE digest every 30 min.

    Keep full per-asset event history and delayed off-site policy. Never call
    the per-record toast from the scheduled watcher; a digest cannot zoom
    to one arbitrary record.
    """
    from collections import Counter
    from .deferred_notifications import site_active,is_historical
    from .surveyor_notifications import event_timestamp,record_findings
    if not config.get("activity_notifications_enabled"):
        return {"clean_notifications_sent":0,"clean_notifications_failed":0,
                "heartbeat_sent":0,"heartbeat_failed":0}
    digest_sender=clean_sender or deliver_clean_digest
    heartbeat_sender=heartbeat_sender or deliver_heartbeat
    ensure_schema(db)
    occupied=site_active(config,now_ms)
    _clean_digest_due(db,now_ms)  # establish clock even when no new events
    candidates=clean_activity_candidates(snapshots,config,now_ms,db)
    for item in candidates[:MAX_NEW_CLEAN_EVENTS_PER_SCAN]:
        if is_historical(item["event_time_utc_ms"],now_ms):
            _queue_old_clean(db,item,now_ms)
        else:
            _queue_digest(db,item,now_ms)
    # Revalidate only queued features that actually appear in the latest
    # source scan. Do not rerun the entire QA engine on thousands of poles
    # a second time during every one-minute scheduled scan.
    pending_items={}
    for table in ("delayed_clean_activity","pending_clean_digest"):
        pending_items[table]=[
            json.loads(row[0]) for row in db.execute(
                f"SELECT payload_json FROM {table}"
            ).fetchall()
        ]
    watched_queue={
        (item["asset"],int(item["objectid"]),item["globalid"])
        for items in pending_items.values() for item in items
    }
    latest={}
    checked_clean=set()
    for asset,(records,fields,domains,rules,expectations) in snapshots.items():
        for attrs in records:
            if attrs.get("OBJECTID") is None or not attrs.get("GLOBALID"):
                continue
            key=(asset,int(attrs["OBJECTID"]),str(attrs["GLOBALID"]).strip())
            if key not in watched_queue:
                continue
            event_ms=int(event_timestamp(attrs) or 0)
            latest[key]=event_ms
            issues,unverified=record_findings(
                asset,attrs,fields,domains,rules,expectations
            )
            if not issues and not unverified:
                checked_clean.add((*key,event_ms))
    for table,items in pending_items.items():
        for entry in items:
            key=_pending_key(entry)[:3]
            if key in latest and (
                latest[key]!=int(entry["event_time_utc_ms"])
                or (*key,int(entry["event_time_utc_ms"])) not in checked_clean
            ):
                if table=="pending_clean_digest":
                    _drop_digest(db,entry)
                else:
                    _remove_delayed_clean(db,entry)
    # A digest parked overnight must not be delivered while the crew are
    # on site. Move those entries to the existing historical queue.
    pending=[
        json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM pending_clean_digest"
        ).fetchall()
    ]
    for item in pending:
        if is_historical(item["event_time_utc_ms"],now_ms):
            _queue_old_clean(db,item,now_ms)
            _drop_digest(db,item)
    if not occupied:
        for (payload,) in db.execute(
            "SELECT payload_json FROM delayed_clean_activity ORDER BY queued_at_utc_ms"
        ).fetchall():
            item=json.loads(payload)
            item["deferred_historical"]=True
            _queue_digest(db,item,now_ms)
            _remove_delayed_clean(db,item)
    sent=failed=historical_sent=0
    records=[
        json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM pending_clean_digest ORDER BY queued_at_utc_ms"
        ).fetchall()
    ]
    if records and _clean_digest_due(db,now_ms):
        counts=Counter(item["asset"] for item in records)
        summary={
            "total":len(records),
            "by_asset":dict(counts),
            "surveyor_count":len(set(x["username"].casefold() for x in records)),
            "created":sum(x["event_type"]=="CREATE" for x in records),
            "edited":sum(x["event_type"]=="EDIT" for x in records),
            "historical":sum(bool(x.get("deferred_historical")) for x in records),
            "window_minutes":CLEAN_DIGEST_INTERVAL_MINUTES,
        }
        try:
            digest_sender(summary,config)
            # A single transaction ensures history/outbox/clock advance together.
            with db:
                for item in records:
                    db.execute("""
                        INSERT OR IGNORE INTO clean_surveyor_activity
                        (asset,objectid,globalid,source_event_ms,
                         username,event_type,notified_at_ms)
                        VALUES(?,?,?,?,?,?,?)
                    """,(
                        item["asset"],int(item["objectid"]),item["globalid"],
                        int(item["event_time_utc_ms"]),item["username"],
                        item["event_type"],int(now_ms),
                    ))
                    db.execute("""
                        DELETE FROM pending_clean_digest
                        WHERE asset=? AND objectid=? AND globalid=?
                              AND event_time_utc_ms=?
                    """,_pending_key(item))
                db.execute(
                    "UPDATE clean_digest_clock SET last_digest_ms=? WHERE id=1",
                    (int(now_ms),)
                )
            sent=1
            historical_sent=summary["historical"]
        except Exception:
            # Retry the SAME summary; never pretend the batch was delivered.
            failed=1
    historical_waiting=db.execute(
        "SELECT COUNT(*) FROM delayed_clean_activity"
    ).fetchone()[0]
    buffered=db.execute("SELECT COUNT(*) FROM pending_clean_digest").fetchone()[0]
    heartbeat_sent=heartbeat_failed=0
    if heartbeat_due(db,config,now_ms):
        mins=int(config.get("activity_heartbeat_minutes",DEFAULT_HEARTBEAT_MINUTES))
        summary=dict(stats)
        summary.update({
            "period_minutes":mins,
            "recent_events":_recent_count(snapshots,config,now_ms,mins),
            "clean_notifications_sent":sent,
        })
        try:
            heartbeat_sender(summary,config)
            record_heartbeat(db,now_ms)
            heartbeat_sent=1
        except Exception:
            heartbeat_failed=1
    return {
        "clean_notifications_sent":sent,
        "clean_notifications_failed":failed,
        "clean_digest_pending":buffered,
        "clean_digest_interval_minutes":CLEAN_DIGEST_INTERVAL_MINUTES,
        "clean_historical_queued":historical_waiting,
        "clean_historical_delivered_this_scan":historical_sent,
        "heartbeat_sent":heartbeat_sent,
        "heartbeat_failed":heartbeat_failed,
    }


def change_activity_mode(config_path,enabled,*,now_ms=None,heartbeat_minutes=60):
    """Atomic opt-in, preserves seven watched users and old alerts and state."""
    path=Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    config=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config,dict) or not config.get("usernames") or not config.get("assets"):
        raise ValueError("REPORTAPP monitoring configuration is incomplete.")
    if config.get("channel","desktop")!="desktop":
        raise ValueError("Activity notifications currently require the desktop channel.")
    if enabled and not 10<=int(heartbeat_minutes)<=240:
        raise ValueError("Heartbeat interval must be 10–240 minutes.")
    current=bool(config.get("activity_notifications_enabled"))
    if enabled and current:
        return {"status":"UNCHANGED","enabled":True,
                "activity_enabled_at_utc_ms":config["activity_notifications_enabled_at_utc_ms"]}
    if not enabled and not current:
        return {"status":"UNCHANGED","enabled":False}
    stamp=int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp()*1000)
    config["activity_notifications_enabled"]=bool(enabled)
    if enabled:
        # A separate "now" cutoff prevents years of clean records triggering toasts.
        config["activity_notifications_enabled_at_utc_ms"]=stamp
        config["activity_heartbeat_minutes"]=int(heartbeat_minutes)
    backup=path.with_name(path.stem+"_backup_activity_"+
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")+".json")
    shutil.copy2(path,backup)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",encoding="utf-8",dir=path.parent,
            prefix=".monitor_activity_",suffix=".tmp",delete=False
        ) as f:
            temp=Path(f.name)
            json.dump(config,f,indent=2,ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return {"status":"UPDATED","enabled":bool(enabled),
            "activity_enabled_at_utc_ms":config.get("activity_notifications_enabled_at_utc_ms"),
            "heartbeat_minutes":config.get("activity_heartbeat_minutes"),
            "config_backup":str(backup),"usernames":len(config["usernames"]),
            "assets":config["assets"]}

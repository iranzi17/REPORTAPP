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
MAX_CLEAN_TOASTS_PER_SCAN=5
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
            already=db.execute("""
                SELECT 1 FROM clean_surveyor_activity
                WHERE asset=? AND objectid=? AND globalid=? AND source_event_ms=?
            """,(asset,int(oid),gid,int(event_ms))).fetchone()
            if already:
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
    return pending[:MAX_CLEAN_TOASTS_PER_SCAN]


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
    title=f"REG QA CHECKED: {entry['asset'].upper()} — no gaps found"
    message=(
        f"{entry['username']} {kind} OBJECTID {entry['objectid']}.\n"
        "No outstanding issues in the currently verified QA rules.\n"
        "Source attributes were not changed by REPORTAPP."
    )
    launch=(zoom_uri(entry["asset"],entry["objectid"]) if is_registered() else "")
    popup=Notification(
        app_id="REPORTAPP Surveyor Activity",title=title,
        msg=message,duration="long",launch=launch,
    )
    if launch:
        popup.add_actions(label="Zoom in ArcGIS Pro",launch=launch)
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


def process_activity(snapshots,config,now_ms,db,stats,
                     clean_sender=None,heartbeat_sender=None):
    """Send non-flagged activity without modifying existing flag notifications."""
    if not config.get("activity_notifications_enabled"):
        return {"clean_notifications_sent":0,"clean_notifications_failed":0,
                "heartbeat_sent":0,"heartbeat_failed":0}
    clean_sender=clean_sender or deliver_clean_activity
    heartbeat_sender=heartbeat_sender or deliver_heartbeat
    entries=clean_activity_candidates(snapshots,config,now_ms,db)
    sent=failed=0
    for entry in entries:
        try:
            clean_sender(entry,config)
            record_clean_activity(db,entry,now_ms)
            sent+=1
        except Exception:
            # Do not mark sent on failure; retry next minute.
            failed+=1
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
    return {"clean_notifications_sent":sent,"clean_notifications_failed":failed,
            "heartbeat_sent":heartbeat_sent,"heartbeat_failed":heartbeat_failed}


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

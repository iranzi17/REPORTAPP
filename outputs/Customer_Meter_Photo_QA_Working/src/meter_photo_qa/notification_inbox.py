"""Persistent, local-only REPORTAPP surveyor quality alert inbox.

Shares the existing monitor_config.sqlite3 database; never edits REG features.
GUI uses tkinter only when explicitly opened by the Windows user. All review
states are local supervisory actions and do NOT mean the source defect was fixed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT UNIQUE NOT NULL,
    asset TEXT NOT NULL,
    objectid INTEGER NOT NULL,
    globalid TEXT NOT NULL,
    username TEXT NOT NULL,
    event_type TEXT NOT NULL,
    created_user TEXT NOT NULL,
    last_edited_user TEXT NOT NULL,
    event_time_utc_ms INTEGER,
    received_utc_ms INTEGER NOT NULL,
    issues_json TEXT NOT NULL,
    issue_digest TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'PENDING',
    delivery_error TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'OPEN',
    review_notes TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    reviewed_at_utc_ms INTEGER,
    origin TEXT NOT NULL DEFAULT 'LIVE'
);
CREATE INDEX IF NOT EXISTS ix_alert_inbox_review
    ON alert_inbox (review_status, received_utc_ms DESC);
"""

def database_path(config_path):
    return Path(config_path).expanduser().resolve().with_suffix(".sqlite3")

def connect_inbox(config_path):
    config = Path(config_path).expanduser().resolve()
    if not config.is_file():
        raise FileNotFoundError(f"REPORTAPP monitor config missing: {config}")
    conn = sqlite3.connect(database_path(config), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)
    return conn

def ensure_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()

def _event_key(alert):
    # Distinct source edits are separate events; an unchanged pending event is
    # never duplicated by repeated minute-by-minute retries.
    data = [
        str(alert["asset"]), int(alert["objectid"]),
        str(alert["globalid"]).strip().casefold(),
        str(alert["issue_digest"]),
        int(alert["event_time_utc_ms"]),
    ]
    digest = hashlib.sha256(
        json.dumps(data,ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return "LIVE:" + digest

def record_alert(conn, alert, received_ms):
    ensure_schema(conn)
    key = _event_key(alert)
    conn.execute("""
        INSERT OR IGNORE INTO alert_inbox
        (event_key,asset,objectid,globalid,username,event_type,created_user,
         last_edited_user,event_time_utc_ms,received_utc_ms,issues_json,
         issue_digest,delivery_status,origin)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'PENDING','LIVE')
    """, (
        key, str(alert["asset"]), int(alert["objectid"]),
        str(alert["globalid"]),str(alert["username"]),
        str(alert.get("event_type") or ""),
        str(alert.get("created_user") or ""),
        str(alert.get("last_edited_user") or ""),
        int(alert["event_time_utc_ms"]),int(received_ms),
        json.dumps(alert["issues"],ensure_ascii=False),
        str(alert["issue_digest"]),
    ))
    row = conn.execute("SELECT id FROM alert_inbox WHERE event_key=?", (key,)).fetchone()
    conn.commit()
    return int(row[0])

def mark_delivery(conn, row_id, status, reason=""):
    if status not in ("SENT", "SEND_FAILED"):
        raise ValueError("Unknown delivery status.")
    cursor=conn.execute(
        "UPDATE alert_inbox SET delivery_status=?, delivery_error=? WHERE id=?",
        (status,str(reason),int(row_id))
    )
    if cursor.rowcount != 1:
        raise ValueError(f"Unknown alert ID: {row_id}")
    conn.commit()

def import_legacy_events(config_path, conn):
    """Idempotently import old SENT JSONL events including prior real alerts.

    Old event logs lack exact source edit timestamps; only the delivery timestamp
    is shown. Test notification lines are excluded from the real alert inbox.
    """
    path=Path(config_path).expanduser().resolve().with_suffix(".events.jsonl")
    if not path.is_file():
        return {"imported":0,"skipped":0}
    ensure_schema(conn)
    imported=0
    skipped=0
    with path.open("r",encoding="utf-8-sig") as source:
        for line in source:
            line=line.strip()
            if not line:
                continue
            try:
                event=json.loads(line)
                if event.get("status")!="SENT" or not isinstance(event.get("issues"),list):
                    # Failed deliveries have no field-level issues in old logs.
                    continue
                oid=int(event["objectid"])
                asset=str(event["asset"])
                gid=str(event["globalid"])
                user=str(event["username"])
                received=int(event["at_utc_ms"])
                issues=[str(issue) for issue in event["issues"]]
                if asset not in ("pole","transformer","line") or not issues:
                    continue
                issues_json=json.dumps(issues,ensure_ascii=False)
                # The new monitor logs LIVE deliveries to JSONL as well.
                # Do not import a copy of those as legacy alerts.
                existing=conn.execute("""
                    SELECT id FROM alert_inbox
                    WHERE origin='LIVE' AND asset=? AND objectid=?
                    AND globalid=? AND username=? AND received_utc_ms=?
                    AND issues_json=? AND delivery_status='SENT' LIMIT 1
                """,(asset,oid,gid,user,received,issues_json)).fetchone()
                if existing is not None:
                    continue
                key="LEGACY:"+hashlib.sha256(line.encode("utf-8")).hexdigest()
                result=conn.execute("""
                    INSERT OR IGNORE INTO alert_inbox
                    (event_key,asset,objectid,globalid,username,event_type,created_user,
                     last_edited_user,event_time_utc_ms,received_utc_ms,issues_json,
                     issue_digest,delivery_status,origin)
                    VALUES (?,?,?,?,?,'','','',NULL,?,?,?,'SENT','HISTORICAL_JSONL')
                """,(
                    key,asset,oid,gid,user,received,
                    issues_json,
                    hashlib.sha256(line.encode("utf-8")).hexdigest(),
                ))
                imported+=int(result.rowcount>0)
            except (ValueError,TypeError,KeyError,json.JSONDecodeError,sqlite3.Error):
                skipped+=1
    conn.commit()
    return {"imported":imported,"skipped":skipped}

def list_alerts(conn, status="OPEN", search="", limit=500):
    if status not in ("OPEN","REVIEWED","ALL"):
        raise ValueError("Invalid review filter.")
    if not 1<=int(limit)<=5000:
        raise ValueError("Limit must be 1 to 5000.")
    where=[]
    values=[]
    if status!="ALL":
        where.append("review_status=?")
        values.append(status)
    query=str(search or "").strip()
    if query:
        where.append("(username LIKE ? OR globalid LIKE ? OR CAST(objectid AS TEXT) LIKE ? OR asset LIKE ?)")
        values.extend(["%"+query+"%"]*4)
    clause=" WHERE "+" AND ".join(where) if where else ""
    sql="SELECT * FROM alert_inbox"+clause+" ORDER BY received_utc_ms DESC,id DESC LIMIT ?"
    return [dict(row) for row in conn.execute(sql,(*values,int(limit))).fetchall()]

def get_alert(conn,row_id):
    row=conn.execute("SELECT * FROM alert_inbox WHERE id=?",(int(row_id),)).fetchone()
    return dict(row) if row else None

def row_zoom_action(record):
    """Show the explicit action available for this individual Inbox row.

    Old JSONL alerts have no immutable source-edit identity. They may only
    offer a clearly labeled *current asset* find, never a verified edit link.
    """
    if (record.get("origin") == "LIVE" and
            record.get("event_time_utc_ms") is not None and
            record.get("globalid") and record.get("username")):
        return "Zoom in ArcGIS Pro"
    return "Find current asset"


def queue_inbox_row_zoom(config_path, row_id, *, folder=None):
    """Explicit user click: enqueue only the selected row, never auto zoom.

    Original LIVE alerts use their full immutable source edit identity and
    must pass ArcGIS Pro Bridge's final current-source check. A historical
    record is distinguished as manual *find current asset*, not the original
    historical edit. Neither operation mutates REG or review/alert history.
    """
    config_path = Path(config_path).expanduser().resolve()
    db = connect_inbox(config_path)
    try:
        row = get_alert(db, row_id)
    finally:
        db.close()
    if not row:
        raise ValueError("The chosen Inbox alert no longer exists.")
    conf = json.loads(config_path.read_text(encoding="utf-8"))
    from .alert_navigation import enqueue, zoom_uri
    if row_zoom_action(row) == "Zoom in ArcGIS Pro":
        uri = zoom_uri(
            row["asset"], row["objectid"], globalid=row["globalid"],
            event_time_utc_ms=row["event_time_utc_ms"], actor=row["username"],
            gdb_version=conf.get("version", "sde.DEFAULT"),
        )
        mode = "VERIFIED_SOURCE_EVENT"
    else:
        uri = zoom_uri(row["asset"], row["objectid"], manual=True)
        mode = "FIND_CURRENT_ASSET_NOT_HISTORICAL_EVENT"
    request = enqueue(uri, folder=folder)
    return {
        "alert_id": int(row["id"]), "asset": row["asset"],
        "objectid": int(row["objectid"]), "mode": mode,
        "request_file": request["queue_file"],
        "bridge_result": "QUEUED_NOT_YET_VERIFIED",
    }


def fresh_sent_alerts(conn, after_id, limit=25):
    """Only new successfully dispatched LIVE gap events since Inbox opened.

    Database is never mutated. A successful .show() is not proof Windows
    displayed its banner; this feed supports an interactive Inbox fallback.
    """
    if not 1 <= int(limit) <= 100:
        raise ValueError("Gap popup batch limit must be 1..100")
    records = conn.execute(
        """SELECT * FROM alert_inbox WHERE id>? AND origin='LIVE'
           AND delivery_status='SENT' ORDER BY id DESC LIMIT ?""",
        (int(after_id), int(limit)),
    ).fetchall()
    return [dict(row) for row in records]


def resend_saved_alert(config_path, row_id, *, source_verifier=None, sender=None):
    """Operator-only recovery of a missed Windows banner, without a new scan.

    A Windows ToastNotifier.show() return cannot prove a banner was displayed.
    The stored LIVE record provides durable recovery, but an alert is never
    replayed until its original GlobalID, OBJECTID, UTC edit time, actor, and
    sde.DEFAULT are freshly verified. No REG edits, SQLite writes, new
    deduplication markers, or automatic replays.
    """
    config_path=Path(config_path).expanduser().resolve()
    conf=json.loads(config_path.read_text(encoding="utf-8"))
    if conf.get("channel","desktop")!="desktop":
        raise ValueError("Saved Windows popup requires desktop delivery.")
    conn=connect_inbox(config_path)
    try:
        row=get_alert(conn,row_id)
    finally:
        conn.close()
    if not row:
        raise ValueError("Alert not found in the existing REPORTAPP Inbox.")
    if (row["origin"]!="LIVE" or row["delivery_status"]!="SENT"
            or not row["event_time_utc_ms"] or not row["globalid"]):
        raise ValueError(
            "Only previously dispatched LIVE alerts with verified source "
            "event identity can be resent. Use Find Asset for legacy alerts."
        )
    alert={
        "asset":row["asset"],"objectid":row["objectid"],
        "globalid":row["globalid"],"username":row["username"],
        "event_type":row["event_type"],"created_user":row["created_user"],
        "last_edited_user":row["last_edited_user"],
        "event_time_utc_ms":row["event_time_utc_ms"],
        "issue_digest":row["issue_digest"],
        "issues":json.loads(row["issues_json"]),
    }
    if not alert["issues"]:
        raise ValueError("This saved alert has no recorded quality gaps.")
    if source_verifier is None:
        from .source_event_navigation import verified_source_uri
        source_verifier=verified_source_uri
    # Fail closed. A newly edited source cannot be represented by an old toast.
    source_verifier(alert,conf)
    if sender is None:
        from .surveyor_notifications import deliver
        sender=deliver
    sender(alert,conf)
    return {
        "status":"REISSUED_TO_WINDOWS_NOT_VIEW_CONFIRMED",
        "alert_id":int(row_id),
        "objectid":int(row["objectid"]),
        "source_event_utc_ms":int(row["event_time_utc_ms"]),
        "database_changed":False,
        "monitoring_schedule_changed":False,
    }


def set_review(conn,row_id,status,note=None,reviewer=None,now_ms=None):
    if status not in ("OPEN","REVIEWED"):
        raise ValueError("Use OPEN or REVIEWED.")
    if not get_alert(conn,row_id):
        raise ValueError(f"Alert {row_id} was not found.")
    now=int(now_ms if now_ms is not None else dt.datetime.now(dt.timezone.utc).timestamp()*1000)
    username=str(reviewer or os.environ.get("USERNAME") or "LOCAL_REVIEWER")
    current=get_alert(conn,row_id)
    updated_note=current["review_notes"] if note is None else str(note)
    if status=="REVIEWED":
        values=(status,updated_note,username,now,int(row_id))
    else:
        values=(status,updated_note,"",None,int(row_id))
    conn.execute("""
        UPDATE alert_inbox SET review_status=?, review_notes=?, reviewed_by=?,
        reviewed_at_utc_ms=? WHERE id=?
    """,values)
    conn.commit()
    return get_alert(conn,row_id)

def format_time(ms):
    if ms is None:
        return "(not recorded)"
    return dt.datetime.fromtimestamp(int(ms)/1000,dt.timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )

def format_details(record):
    lines=[
        "REPORTAPP SURVEYOR QUALITY ALERT",
        f"Alert ID: {record['id']}",
        f"Surveyor login: {record['username']}",
        f"Asset type: {record['asset'].upper()}",
        f"Source OBJECTID: {record['objectid']}",
        f"Source GlobalID: {record['globalid']}",
        f"Event: {record['event_type'] or 'Not recorded in legacy log'}",
        f"Source event time: {format_time(record['event_time_utc_ms'])}",
        f"Notification delivered/logged: {format_time(record['received_utc_ms'])}",
        f"Original creator: {record['created_user'] or 'Not available'}",
        f"Last editor: {record['last_edited_user'] or 'Not available'}",
        ("Windows toast dispatched (banner not confirmed)"
         if record["delivery_status"]=="SENT"
         else f"Delivery: {record['delivery_status']}"),
        f"Review: {record['review_status']}",
        f"Review by: {record['reviewed_by'] or 'Not yet reviewed'}",
        f"Reviewed at: {format_time(record['reviewed_at_utc_ms'])}",
        "Source: " + record["origin"],
        "",
        "DETECTED ISSUES:",
    ]
    for i,issue in enumerate(json.loads(record["issues_json"]),1):
        lines.append(f"{i}. {issue}")
    lines.extend(["","Supervisor notes:",record["review_notes"] or "(none)",
                  "",
                  "REVIEWED means reviewed in REPORTAPP only; no REG asset is modified."])
    return "\n".join(lines)

FIND_ASSET_OPTIONS = {
    "LV Pole": "pole",
    "LV Line": "line",
    "Transformer": "transformer",
}

def queue_find_asset(asset_label, objectid, *, folder=None):
    """Queue a read-only zoom for ANY accessible REG asset, not just QA alerts.

    No inbox query, alert insertion, monitor configuration change, or REG write.
    The ArcGIS Pro add-in performs source/version and availability checks.
    """
    from .alert_navigation import enqueue, zoom_uri
    asset=FIND_ASSET_OPTIONS.get(str(asset_label).strip())
    if asset is None:
        raise ValueError("Choose LV Pole, LV Line or Transformer.")
    uri=zoom_uri(asset,str(objectid).strip(),manual=True)
    return enqueue(uri,folder=folder)


def bootstrap_maintainer_update(*,repository=None):
    """One-time user-confirmed GitHub fast-forward; never reset hard or force.

    Needed ONLY because the already-installed v1 maintainer can auto-install
    Inbox UI updates but intentionally rejects live watcher code updates.
    Backups go outside Git, all changed paths are reviewed against the
    explicit upgrade allowlist, and local regression failures restore bytes.
    """
    import subprocess
    import shutil
    import sys
    from datetime import datetime,timezone

    repo=(Path(repository).resolve() if repository else
          Path(__file__).resolve().parents[4])
    prefix="outputs/Customer_Meter_Photo_QA_Working/"
    allowed={
        ".github/workflows/reportapp-deferred-alerts.yml",
        ".github/workflows/reportapp-bootstrap-inbox.yml",
        ".github/workflows/reportapp-managed-release.yml",
        "maintenance/build_bootstrap_inbox_release.py",
        "maintenance/README.md",
        ".github/workflows/reportapp-safe-release.yml",
        "maintenance/self_monitor.py",
        "maintenance/build_safe_release.py",
        "maintenance/tests/test_self_monitor.py",
        prefix+"src/meter_photo_qa/surveyor_notifications.py",
        prefix+"src/meter_photo_qa/surveyor_activity.py",
        prefix+"src/meter_photo_qa/deferred_notifications.py",
        prefix+"src/meter_photo_qa/notification_inbox.py",
        prefix+"tests/test_deferred_notifications.py",
        prefix+"tests/test_surveyor_activity.py",
        prefix+"docs/DEFERRED_ALERTS.md",
        prefix+"docs/SURVEYOR_ACTIVITY_NOTIFICATIONS.md",
    }
    def git(*args):
        result=subprocess.run(
            ["git","-C",str(repo),*args],
            capture_output=True,text=True,timeout=90,
        )
        if result.returncode:
            raise RuntimeError(
                "Git operation failed: "+str(args[0])+
                " (exit "+str(result.returncode)+"). "+
                result.stderr[:350]
            )
        return result.stdout.strip()
    if not (repo/".git").is_dir():
        raise RuntimeError("REPORTAPP is not an ordinary Git working tree.")
    if git("branch","--show-current")!="main":
        raise RuntimeError("Only the tested REPORTAPP main branch may be upgraded.")
    origin=git("remote","get-url","origin")
    if origin.rstrip("/").removesuffix(".git") not in (
        "https://github.com/iranzi17/REPORTAPP",
        "git@github.com:iranzi17/REPORTAPP",
    ):
        raise RuntimeError("Unexpected Git remote; update blocked.")
    git("fetch","--no-tags","origin","main")
    # v1 self-maintenance writes the *approved Inbox source* into the checkout.
    # That one tracked file is expected to appear modified before git HEAD is
    # advanced; verify it is byte-for-byte identical to origin/main.
    inbox_file=prefix+"src/meter_photo_qa/notification_inbox.py"
    dirty=[line[3:] for line in git(
        "status","--porcelain","--untracked-files=no"
    ).splitlines() if line]
    def git_blob(revision,path):
        result=subprocess.run(
            ["git","-C",str(repo),"show",revision+":"+path],
            capture_output=True,timeout=30,
        )
        if result.returncode:
            raise RuntimeError("Unable to verify approved Inbox file.")
        return result.stdout
    if inbox_file in dirty and (repo/inbox_file).read_bytes()!=git_blob("origin/main",inbox_file):
        raise RuntimeError(
            "Local Inbox differs from the approved GitHub release; "
            "update blocked to protect local work."
        )
    git("merge-base","--is-ancestor","HEAD","origin/main")
    names=[x for x in git("diff","--name-only","HEAD","origin/main").splitlines() if x]
    if not names:
        return {"status":"UP_TO_DATE","files_changed":0}
    # Keep unrelated local edits untouched. Block ONLY paths that the
    # approved incoming release would overwrite; never discard user work.
    overlap=sorted((set(dirty) & set(names))-{inbox_file})
    if overlap:
        raise RuntimeError(
            "Upgrade blocked because these locally modified files would be "
            "changed by the update: "+", ".join(overlap[:7])+
            ". Local files were preserved."
        )
    disallowed=sorted(set(names)-allowed)
    if disallowed:
        raise RuntimeError(
            "Update includes unrelated paths and was blocked: "+
            ", ".join(disallowed[:5])
        )
    if "maintenance/self_monitor.py" not in names:
        raise RuntimeError("Approved maintainer upgrade not present on main.")
    local=Path(os.environ.get("LOCALAPPDATA") or Path.home())/"REPORTAPP"/"Maintenance"
    backup=local/"bootstrap_backups"/datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup.mkdir(parents=True,exist_ok=False)
    originals={}
    for name in names:
        source=repo/name
        originals[name]=source.read_bytes() if source.is_file() else None
        if originals[name] is not None:
            archived=backup/name
            archived.parent.mkdir(parents=True,exist_ok=True)
            archived.write_bytes(originals[name])
    try:
        if inbox_file in dirty:
            # Safely normalize only the already-backed-up, verified Inbox
            # so Git can fast-forward. NEVER discard any other tracked file.
            (repo/inbox_file).write_bytes(git_blob("HEAD",inbox_file))
        git("merge","--ff-only","origin/main")
        python=Path(sys.prefix)/("python.exe" if os.name=="nt" else "bin/python")
        if not python.is_file():
            raise RuntimeError("Standalone ArcGIS Pro Python missing for smoke tests.")
        source_tests=repo/prefix/"tests"
        environment=os.environ.copy()
        environment["PYTHONPATH"]=str(repo/prefix/"src")
        for name in (
            "test_deferred_notifications.py",
            "test_surveyor_notifications.py",
            "test_surveyor_activity.py",
            "test_notification_inbox.py",
        ):
            result=subprocess.run(
                [str(python),"-m","unittest","discover",
                 "-s",str(source_tests),"-p",name],
                cwd=str(repo),env=environment,
                capture_output=True,text=True,timeout=120,
            )
            if result.returncode:
                raise RuntimeError("Local regression failure in "+name)
    except Exception:
        # Do not reset --hard: that can erase unrelated local GIS work.
        # Restore only the exact upgraded paths from preserved original bytes.
        for name,prior in originals.items():
            target=repo/name
            if prior is None:
                target.unlink(missing_ok=True)
            else:
                temporary=target.with_name(target.name+".reportapp-restore")
                temporary.write_bytes(prior)
                os.replace(temporary,target)
        raise
    return {
        "status":"UPGRADED_AND_TESTED",
        "files_changed":len(names),
        "backup_folder":str(backup),
        "maintainer_auto_releases_enabled":True,
    }


def launch_gui(config_path):
    # Import lazily so scheduled monitoring never imports GUI components.
    import tkinter as tk
    from tkinter import ttk, messagebox
    from tkinter.scrolledtext import ScrolledText

    config=Path(config_path).expanduser().resolve()
    root=tk.Tk()
    root.title("REPORTAPP | Quality Notification Inbox")
    root.geometry("1150x760")
    root.minsize(850,550)
    filter_value=tk.StringVar(value="OPEN")
    search_value=tk.StringVar()
    selected_id=[None]

    heading=ttk.Frame(root,padding=12)
    heading.pack(fill="x")
    ttk.Label(heading,text="REPORTAPP Quality Notification Inbox",
              font=("Segoe UI",17,"bold")).pack(side="left")
    counter=ttk.Label(heading,text="")
    counter.pack(side="right")

    controls=ttk.Frame(root,padding=(12,0,12,8))
    controls.pack(fill="x")
    ttk.Label(controls,text="Show").pack(side="left")
    picker=ttk.Combobox(controls,textvariable=filter_value,
                        values=("OPEN","REVIEWED","ALL"),state="readonly",width=12)
    picker.pack(side="left",padx=(7,16))
    ttk.Label(controls,text="Search username / OBJECTID / GlobalID").pack(side="left")
    search=ttk.Entry(controls,textvariable=search_value,width=35)
    search.pack(side="left",padx=(8,10))

    # Independent from the alert-only search. Do not create an alert for
    # a clean asset; the bridge can open any accessible source OBJECTID.
    find_panel=ttk.LabelFrame(
        root,text="Find Asset — any REG feature (even without a quality alert)",
        padding=(10,7),
    )
    find_panel.pack(fill="x",padx=12,pady=(0,8))
    asset_choice=tk.StringVar(value="LV Line")
    find_oid=tk.StringVar()
    find_status=tk.StringVar(value="Select asset type and enter its source OBJECTID.")
    ttk.Label(find_panel,text="Asset").pack(side="left")
    asset_picker=ttk.Combobox(
        find_panel,textvariable=asset_choice,
        values=tuple(FIND_ASSET_OPTIONS),state="readonly",width=15,
    )
    asset_picker.pack(side="left",padx=(6,12))
    ttk.Label(find_panel,text="OBJECTID").pack(side="left")
    oid_entry=ttk.Entry(find_panel,textvariable=find_oid,width=19)
    oid_entry.pack(side="left",padx=(6,12))

    def find_asset():
        try:
            result=queue_find_asset(asset_choice.get(),find_oid.get())
            request=result["request"]
            find_status.set(
                f"Queued {asset_choice.get()} OBJECTID {request['objectid']}; "
                "ArcGIS Pro will zoom if the record is accessible."
            )
        except Exception as exc:
            find_status.set("Unable to queue navigation. Check asset and OBJECTID.")
            messagebox.showerror("Find Asset",str(exc),parent=root)

    ttk.Button(
        find_panel,text="Find & Zoom in ArcGIS Pro",command=find_asset
    ).pack(side="left")
    # This feedback is deliberately 'queued', not 'found', until the
    # separate ArcGIS Pro bridge finishes its selection.
    ttk.Label(root,textvariable=find_status).pack(
        fill="x",padx=18,pady=(0,6)
    )
    oid_entry.bind("<Return>",lambda _event:find_asset())

    tree_frame=ttk.Frame(root,padding=(12,0,12,0))
    tree_frame.pack(fill="both",expand=True)
    names=("ID","Received","Surveyor","Asset","OBJECTID","Issues","Review","Delivery","Zoom")
    tree=ttk.Treeview(tree_frame,columns=names,show="headings",height=11)
    widths=(65,175,135,85,95,55,85,85,160)
    for col,width in zip(names,widths):
        tree.heading(col,text=col)
        tree.column(col,width=width,stretch=col in ("Surveyor","Received"))
    scroll=ttk.Scrollbar(tree_frame,orient="vertical",command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left",fill="both",expand=True)
    scroll.pack(side="right",fill="y")

    detail_frame=ttk.Frame(root,padding=12)
    detail_frame.pack(fill="both",expand=True)
    ttk.Label(detail_frame,text="Alert details — original REG source is read-only",
              font=("Segoe UI",10,"bold")).pack(anchor="w")
    details=ScrolledText(detail_frame,height=12,wrap="word",state="disabled")
    details.pack(fill="both",expand=True,pady=(4,7))
    ttk.Label(detail_frame,text="Supervisor review notes (stored locally):").pack(anchor="w")
    notes=tk.Text(detail_frame,height=3,wrap="word")
    notes.pack(fill="x",pady=(3,7))
    buttons=ttk.Frame(detail_frame)
    buttons.pack(fill="x")

    def open_db():
        conn=connect_inbox(config)
        migration=import_legacy_events(config,conn)
        return conn,migration

    def detail():
        record_id=selected_id[0]
        if record_id is None:
            return
        conn,_=open_db()
        try:
            rec=get_alert(conn,record_id)
        finally:
            conn.close()
        if rec is None:
            return
        details.configure(state="normal")
        details.delete("1.0","end")
        details.insert("1.0",format_details(rec))
        details.configure(state="disabled")
        notes.delete("1.0","end")
        notes.insert("1.0",rec["review_notes"])

    def on_selection(_event=None):
        selection=tree.selection()
        if selection:
            new_id=int(selection[0])
            if new_id!=selected_id[0]:
                selected_id[0]=new_id
                detail()

    def refresh():
        previous=selected_id[0]
        try:
            conn,migration=open_db()
            try:
                rows=list_alerts(conn,filter_value.get(),search_value.get())
                count_open=conn.execute(
                    "SELECT COUNT(*) FROM alert_inbox WHERE review_status='OPEN'"
                ).fetchone()[0]
                count_total=conn.execute("SELECT COUNT(*) FROM alert_inbox").fetchone()[0]
            finally:
                conn.close()
            for item in tree.get_children():
                tree.delete(item)
            for item in rows:
                tree.insert("", "end", iid=str(item["id"]),values=(
                    item["id"],format_time(item["received_utc_ms"]),
                    item["username"],item["asset"].upper(),item["objectid"],
                    len(json.loads(item["issues_json"])),item["review_status"],
                    item["delivery_status"],row_zoom_action(item),
                ))
            counter.configure(text=f"Open: {count_open} | All: {count_total}")
            if previous is not None and tree.exists(str(previous)):
                tree.selection_set(str(previous))
            elif tree.get_children():
                selected_id[0]=None
                tree.selection_set(tree.get_children()[0])
                on_selection()
            else:
                selected_id[0]=None
                details.configure(state="normal")
                details.delete("1.0","end")
                details.configure(state="disabled")
                notes.delete("1.0","end")
            if migration["skipped"]:
                messagebox.showwarning("Legacy alert import",
                    f"Skipped {migration['skipped']} invalid event log lines.")
        except Exception as exc:
            messagebox.showerror("Inbox database error",str(exc))

    def update(status=None):
        if selected_id[0] is None:
            messagebox.showinfo("Choose alert","Select an alert before saving.")
            return
        try:
            conn,_=open_db()
            try:
                rec=get_alert(conn,selected_id[0])
                target=status or rec["review_status"]
                set_review(conn,selected_id[0],target,
                           note=notes.get("1.0","end-1c"))
            finally:
                conn.close()
            refresh()
        except Exception as exc:
            messagebox.showerror("Review update failed",str(exc))

    def manage_surveyors():
        """Local add/remove actions preserve existing selected-account timing."""
        from .notification_setup import update_monitored_surveyors
        from .smart_query import USER_NAMES_PATH

        try:
            known=json.loads(USER_NAMES_PATH.read_text(encoding="utf-8"))
            current=json.loads(config.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Manage Surveyors",str(exc))
            return
        dialog=tk.Toplevel(root)
        dialog.title("REPORTAPP | Manage Surveyors")
        dialog.geometry("820x690")
        dialog.minsize(770,610)
        dialog.transient(root)
        dialog.grab_set()
        shell=ttk.Frame(dialog,padding=12)
        shell.pack(fill="both",expand=True)
        ttk.Label(shell,text="Add or remove monitored surveyors",
                  font=("Segoe UI",14,"bold")).pack(anchor="w")
        asset_status=tk.StringVar()
        ttk.Label(shell,textvariable=asset_status).pack(anchor="w",pady=(5,10))
        panes=ttk.Frame(shell)
        panes.pack(fill="both",expand=True)
        left=ttk.Frame(panes)
        right=ttk.Frame(panes)
        left.pack(side="left",fill="both",expand=True,padx=(0,8))
        right.pack(side="left",fill="both",expand=True,padx=(8,0))
        ttk.Label(left,text="Currently monitored (select to remove)").pack(anchor="w")
        monitored=tk.Listbox(left,selectmode="extended",exportselection=False)
        monitored.pack(fill="both",expand=True,pady=(5,6))
        ttk.Label(right,text="Available accounts (select to add)").pack(anchor="w")
        available=tk.Listbox(right,selectmode="extended",exportselection=False)
        available.pack(fill="both",expand=True,pady=(5,6))
        options=sorted(known.items(),key=lambda v:v[0].casefold())
        candidate_usernames=[user for user,_ in options]

        def reload_lists():
            conf=json.loads(config.read_text(encoding="utf-8"))
            asset_status.set(
                "Current assets: "+", ".join(conf.get("assets",[]))+
                "  |  Existing monitoring dates and inbox alerts preserved."
            )
            monitored.delete(0,"end")
            for login in conf.get("usernames",[]):
                monitored.insert("end",login+" — "+str(known.get(login,"(unknown name)")))
            available.delete(0,"end")
            active={x.casefold() for x in conf.get("usernames",[])}
            for user,name in options:
                available.insert("end",user+" — "+str(name))
                if user.casefold() in active:
                    available.itemconfig("end",foreground="#888888")
            return conf

        def apply_update(action):
            if action=="add":
                choices=[candidate_usernames[i] for i in available.curselection()]
                if not choices:
                    messagebox.showinfo("Manage Surveyors","Select surveyors to add.",parent=dialog)
                    return
            else:
                conf=json.loads(config.read_text(encoding="utf-8"))
                choices=[conf["usernames"][i] for i in monitored.curselection()]
                if not choices:
                    messagebox.showinfo("Manage Surveyors","Select surveyors to remove.",parent=dialog)
                    return
                if not messagebox.askyesno(
                    "Confirm removal",
                    "Stop watching: "+", ".join(choices)+"?\n"
                    "Previously recorded inbox alerts remain accessible.",
                    parent=dialog,
                ):
                    return
            try:
                result=update_monitored_surveyors(
                    config,
                    add=choices if action=="add" else (),
                    remove=choices if action=="remove" else (),
                )
                reload_lists()
                messagebox.showinfo(
                    "Monitor updated",
                    ("Added: "+", ".join(result.get("added",[]))+"\n"
                     if result.get("added") else "")+
                    ("Removed: "+", ".join(result.get("removed",[]))+"\n"
                     if result.get("removed") else "")+
                    "Task Scheduler will read this configuration on its next run.\n"
                    "The existing inbox and alert history were preserved.",
                    parent=dialog,
                )
            except Exception as exc:
                messagebox.showerror("Cannot change surveyors",str(exc),parent=dialog)

        ttk.Button(left,text="Remove Selected",command=lambda:apply_update("remove")).pack(anchor="w")
        ttk.Button(right,text="Add Selected",command=lambda:apply_update("add")).pack(anchor="w")
        asset_panel=ttk.LabelFrame(shell,text="Asset classes for ALL selected surveyors",padding=9)
        asset_panel.pack(fill="x",pady=(10,5))
        asset_options=(
            ("pole","LV Poles"),
            ("line","LV Lines"),
            ("transformer","Distribution Transformers"),
        )
        asset_flags={
            a:tk.BooleanVar(value=a in current.get("assets",[]))
            for a,_label in asset_options
        }
        for asset,label in asset_options:
            ttk.Checkbutton(asset_panel,text=label,variable=asset_flags[asset]).pack(
                side="left",padx=(0,18)
            )

        def apply_asset_classes():
            from .notification_setup import update_monitored_assets
            selected=[a for a,_label in asset_options if asset_flags[a].get()]
            if not selected:
                messagebox.showerror(
                    "Asset selection","Select at least one asset class.",parent=dialog
                )
                return
            original_assets=json.loads(config.read_text(encoding="utf-8")).get("assets",[])
            if set(selected)==set(original_assets):
                messagebox.showinfo("Asset selection","No changes needed.",parent=dialog)
                return
            if not messagebox.askyesno(
                "Verify monitored assets",
                "REPORTAPP will verify access to all selected REG asset layers "
                "before saving.\nExisting start times and inbox alerts are preserved. "
                "New asset types begin monitoring only from activation time.\n\n"
                "Continue?",parent=dialog
            ):
                return
            dialog.configure(cursor="watch")
            dialog.update_idletasks()
            try:
                outcome=update_monitored_assets(config,selected)
                reload_lists()
                messagebox.showinfo(
                    "Assets updated",
                    "REG verification successful.\n"
                    "Added: "+(", ".join(outcome["added"]) or "(none)")+"\n"
                    "Removed: "+(", ".join(outcome["removed"]) or "(none)")+"\n"
                    "Task Scheduler will use the updated monitoring list on its "
                    "next cycle. Review history was preserved.",
                    parent=dialog,
                )
            except Exception as exc:
                messagebox.showerror(
                    "REG preflight failed — no changes saved",str(exc),parent=dialog
                )
            finally:
                dialog.configure(cursor="")

        ttk.Button(
            asset_panel,text="Verify & Apply Asset Classes",command=apply_asset_classes
        ).pack(side="right")
        ttk.Label(shell,text=(
            "New surveyors and newly enabled asset classes start from their "
            "activation time. Old records are not alerted retroactively."
        ),wraplength=760).pack(anchor="w",pady=(6,6))
        ttk.Button(shell,text="Close",command=dialog.destroy).pack(anchor="e")
        reload_lists()

    def show_clean_activity():
        """Separate history; never adds clean checks to the flag-only Inbox."""
        from .surveyor_activity import list_recent_activity
        from .alert_navigation import enqueue,zoom_uri
        window=tk.Toplevel(root)
        window.title("REPORTAPP | Verified Clean Surveyor Activity")
        window.geometry("850x475")
        frame=ttk.Frame(window,padding=12)
        frame.pack(fill="both",expand=True)
        ttk.Label(
            frame,text="Recent no-gap notifications — read-only REG checks",
            font=("Segoe UI",12,"bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,text="Only events created or edited after activity monitoring was enabled. "
                       "These are not quality issues and do not affect Inbox counts.",
            wraplength=770,
        ).pack(anchor="w",pady=(4,10))
        cols=("Received","Source event","Surveyor","Asset","OBJECTID","Event")
        table=ttk.Treeview(frame,columns=cols,show="headings",height=13)
        widths=(166,166,140,110,95,90)
        for col,width in zip(cols,widths):
            table.heading(col,text=col)
            table.column(col,width=width,stretch=col=="Surveyor")
        table.pack(fill="both",expand=True)
        events={}
        def load():
            events.clear()
            for rid in table.get_children():
                table.delete(rid)
            db=connect_inbox(config)
            try:
                recent=list_recent_activity(db,limit=250)
            finally:
                db.close()
            for number,item in enumerate(recent):
                key=str(number)
                events[key]=item
                table.insert("","end",iid=key,values=(
                    format_time(item["notified_at_ms"]),
                    format_time(item["event_time_utc_ms"]),
                    item["username"],item["asset"].upper(),
                    item["objectid"],item["event_type"],
                ))
        def navigate():
            selected=table.selection()
            if not selected:
                return
            item=events[selected[0]]
            try:
                enqueue(zoom_uri(item["asset"],item["objectid"],manual=True))
                messagebox.showinfo(
                    "Navigation queued","Open ArcGIS Pro to select the asset.",
                    parent=window,
                )
            except Exception as exc:
                messagebox.showerror("Navigation error",str(exc),parent=window)
        actions=ttk.Frame(frame)
        actions.pack(fill="x",pady=(10,0))
        ttk.Button(actions,text="Refresh",command=load).pack(side="left")
        ttk.Button(
            actions,text="Zoom selected asset in ArcGIS Pro",command=navigate
        ).pack(side="left",padx=10)
        ttk.Button(actions,text="Close",command=window.destroy).pack(side="right")
        try:
            load()
        except Exception as exc:
            messagebox.showerror("Activity history",str(exc),parent=window)

    def configure_site_presence():
        """Set manual on-site/off-site mode or a confirmed Rwanda work schedule."""
        try:
            from .deferred_notifications import change_site_mode
        except ImportError:
            messagebox.showinfo(
                "Maintenance upgrade required",
                "The site-hours watcher is not installed yet. "
                "Click Install Approved Update first, then reopen this Inbox.",
                parent=root,
            )
            return
        try:
            current=json.loads(config.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Site Presence",str(exc),parent=root)
            return
        popup=tk.Toplevel(root)
        popup.title("REPORTAPP | Site Presence & Historical Alerts")
        popup.geometry("590x430")
        popup.transient(root)
        popup.grab_set()
        frame=ttk.Frame(popup,padding=18)
        frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="When are surveyors on site?",
                  font=("Segoe UI",13,"bold")).pack(anchor="w")
        ttk.Label(
            frame,text=(
                "Today’s data-quality issues are notified immediately. "
                "Previous-day issues are queued and delivered only off-site. "
                "This setting does not pause quality scanning or edit REG data."
            ),wraplength=530,
        ).pack(anchor="w",pady=(6,15))
        mode=tk.StringVar(value=current.get("surveyor_site_mode","on_site"))
        for value,label in (
            ("on_site","Surveyors are on site — hold older notifications"),
            ("off_site","Surveyors have left — deliver queued older notifications"),
            ("schedule","Automatic — use confirmed Rwanda working hours"),
        ):
            ttk.Radiobutton(frame,text=label,variable=mode,
                            value=value).pack(anchor="w",pady=3)
        timing=ttk.Frame(frame)
        timing.pack(fill="x",pady=(12,8))
        schedule=current.get("surveyor_site_schedule") or {}
        start=tk.StringVar(value=schedule.get("start",""))
        end=tk.StringVar(value=schedule.get("end",""))
        ttk.Label(timing,text="Start (HH:MM)").grid(row=0,column=0,sticky="w")
        ttk.Entry(timing,textvariable=start,width=12).grid(row=1,column=0,padx=(0,16))
        ttk.Label(timing,text="End (HH:MM)").grid(row=0,column=1,sticky="w")
        ttk.Entry(timing,textvariable=end,width=12).grid(row=1,column=1,padx=(0,16))
        ttk.Label(timing,text="Rwanda local time (UTC+2)").grid(
            row=1,column=2,sticky="w"
        )
        selected_days=set(schedule.get("weekdays",[]))
        days_frame=ttk.Frame(frame)
        days_frame.pack(fill="x",pady=(6,12))
        ttk.Label(days_frame,text="Work days: ").pack(side="left",padx=(0,12))
        labels=("Mon","Tue","Wed","Thu","Fri","Sat","Sun")
        flags=[]
        for index,name in enumerate(labels):
            state=tk.BooleanVar(value=index in selected_days)
            flags.append(state)
            ttk.Checkbutton(days_frame,text=name,variable=state).pack(
                side="left",padx=(0,7)
            )
        def save_mode():
            try:
                selected=mode.get()
                planned=(
                    {"start":start.get(),"end":end.get(),
                     "weekdays":[i for i,flag in enumerate(flags) if flag.get()]}
                    if selected=="schedule" else None
                )
                outcome=change_site_mode(config,selected,schedule=planned)
                messagebox.showinfo(
                    "Site status updated",
                    "Site mode: "+selected+"\n"
                    "The watcher will apply this from its next scheduled scan.\n"
                    "No existing alerts or surveyor histories were deleted.",
                    parent=popup,
                )
                popup.destroy()
            except Exception as exc:
                messagebox.showerror("Site mode not saved",str(exc),parent=popup)
        actions=ttk.Frame(frame)
        actions.pack(fill="x",pady=(10,0))
        ttk.Button(actions,text="Save Site Status",command=save_mode).pack(
            side="left"
        )
        ttk.Button(actions,text="Cancel",command=popup.destroy).pack(side="right")

    ttk.Button(controls,text="Refresh",command=refresh).pack(side="left")
    ttk.Button(controls,text="Manage Surveyors",command=manage_surveyors).pack(
        side="left",padx=(8,0)
    )
    ttk.Button(controls,text="Clean Activity History",command=show_clean_activity).pack(
        side="left",padx=(8,0)
    )
    ttk.Button(controls,text="Site Status",command=configure_site_presence).pack(
        side="left",padx=(8,0)
    )
    # Opt-in for the legacy pole Manufacturer rule. The default is OFF;
    # any Manufacturer value is still visible in Excel and source attributes.
    from .notification_setup import set_pole_manufacturer_gap_check
    def _manufacturer_setting():
        live=json.loads(config.read_text(encoding="utf-8"))
        return live.get("pole_manufacturer_gap_enabled",False) is True

    manufacturer_var=tk.BooleanVar(value=_manufacturer_setting())
    def toggle_manufacturer_gaps():
        requested=manufacturer_var.get()
        previous=not requested
        if not messagebox.askyesno(
            "Optional Pole Manufacturer",
            ("Include missing Pole Manufacturer in future gap notifications?"
             if requested else
             "Stop counting missing Pole Manufacturer as a notification gap?")
            +"\nOther pole rules are unchanged.",
            parent=root,
        ):
            manufacturer_var.set(previous)
            return
        try:
            set_pole_manufacturer_gap_check(config,requested)
            messagebox.showinfo(
                "Manufacturer rule updated",
                "The configuration is saved. New scans using the current "
                "REPORTAPP source will use this rule. Existing sent alerts "
                "and GIS data are unchanged.",
                parent=root,
            )
        except Exception as exc:
            manufacturer_var.set(previous)
            messagebox.showerror("Rule not updated",str(exc),parent=root)
    ttk.Checkbutton(
        controls,text="Include Pole Manufacturer gaps",
        variable=manufacturer_var,command=toggle_manufacturer_gaps,
    ).pack(side="left",padx=(8,0))

    def _navigation_paused():
        from .alert_navigation import queue_folder
        return (queue_folder().parent/"navigation-paused.flag").exists()

    def toggle_navigation_pause():
        # Self-contained for the older local alert_navigation.py on v2
        # maintainer machines: the authorized GUI-only update must work
        # before any separate navigation-handler source is pulled.
        from .alert_navigation import queue_folder
        try:
            requests=queue_folder()
            requests.mkdir(parents=True,exist_ok=True)
            flag=requests.parent/"navigation-paused.flag"
            was_paused=flag.exists()
            if not was_paused:
                flag.write_text("Paused by REPORTAPP supervisor.\\n",encoding="utf-8")
            moved=0
            for item in requests.glob("*.json"):
                try:
                    item.rename(item.with_name(item.name+".paused"))
                    moved+=1
                except FileNotFoundError:
                    continue
            if was_paused:
                # Clear pending requests BEFORE lifting the C# pause flag.
                flag.unlink(missing_ok=True)
            messagebox.showinfo(
                "Navigation " + ("resumed" if was_paused else "paused"),
                (
                    "Map zoom is enabled only for new explicit clicks. "
                    "Previously pending requests were not replayed."
                    if was_paused else
                    "Map zoom has been paused; "+
                    str(moved)+" pending clicks were preserved. "
                    "With the older add-in, restart ArcGIS Pro at a safe "
                    "break to stop any request already in progress."
                ),
                parent=root,
            )
            pause_button.configure(text=(
                "Pause Map Zoom" if was_paused else "Resume Map Zoom"
            ))
        except Exception as exc:
            messagebox.showerror("Navigation pause",str(exc),parent=root)

    pause_button=ttk.Button(
        find_panel,
        text="Resume Map Zoom" if _navigation_paused() else "Pause Map Zoom",
        command=toggle_navigation_pause,
    )
    pause_button.pack(side="right",padx=(8,0))

    def upgrade_maintainer():
        if not messagebox.askyesno(
            "REPORTAPP Maintenance Upgrade",
            "Install reviewed REPORTAPP maintenance and watcher updates?\n\n"
            "This is a one-time guarded upgrade from GitHub main. "
            "All changed application files will be backed up and tests will "
            "run locally. Surveyor accounts, REG data, monitor configuration "
            "and notification history will not be overwritten.\n\n"
            "Changes to unrelated or locally modified tracked files will be "
            "refused. If tests fail, prior code bytes will be restored.\n\n"
            "Continue?",parent=root
        ):
            return
        root.configure(cursor="watch")
        root.update_idletasks()
        try:
            result=bootstrap_maintainer_update()
            messagebox.showinfo(
                "Maintenance upgrade",
                "Status: "+result["status"]+"\n"
                "Files changed: "+str(result["files_changed"])+"\n"
                "Close and reopen the Inbox to load any new code.\n"
                "The one-minute watcher continues to use its existing task.",
                parent=root,
            )
        except Exception as exc:
            messagebox.showerror("Safe upgrade stopped",str(exc),parent=root)
        finally:
            root.configure(cursor="")
    ttk.Button(
        controls,text="Install Approved Update",
        command=upgrade_maintainer,
    ).pack(side="left",padx=(8,0))

    def zoom_selected():
        if selected_id[0] is None:
            return
        try:
            result=queue_inbox_row_zoom(config,selected_id[0])
            find_status.set(
                f"Inbox alert {result['alert_id']}: OBJECTID {result['objectid']} "
                "queued. ArcGIS Pro must verify the current source before selecting."
            )
        except Exception as exc:
            messagebox.showerror("REPORTAPP navigation",str(exc),parent=root)

    def resend_selected_popup():
        if selected_id[0] is None:
            messagebox.showinfo("REPORTAPP","Select a saved LIVE QA alert first.",parent=root)
            return
        if not messagebox.askyesno(
            "Resend selected Windows popup",
            "Verify the CURRENT source edit and resend this saved alert once?\\n"
            "No REG features or watcher history will change.",parent=root
        ):
            return
        try:
            result=resend_saved_alert(config,selected_id[0])
            messagebox.showinfo(
                "REPORTAPP popup dispatched",
                "Sent to the Windows notification service again. Windows may "
                "still suppress banners; check Win + N if needed.\\n"
                f"Alert ID {result['alert_id']}, OBJECTID {result['objectid']}.",
                parent=root
            )
        except Exception as exc:
            messagebox.showerror("Popup cannot be resent safely",str(exc),parent=root)

    # The same safe navigation is available on EACH record, not just a
    # bottom-of-window selected-row control. A Treeview cell is a click target.
    def click_row_zoom(event):
        if tree.identify_region(event.x,event.y)!="cell" or (
                tree.identify_column(event.x)!="#9"):
            return
        row=tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        selected_id[0]=int(row)
        detail()
        try:
            record_result=queue_inbox_row_zoom(config,int(row))
            find_status.set(
                f"Inbox alert {row} — {record_result['asset'].upper()} "
                f"OBJECTID {record_result['objectid']} queued; "
                "ArcGIS Pro will check the exact source before zooming."
            )
        except Exception as exc:
            messagebox.showerror("Row zoom not queued",str(exc),parent=root)
        return "break"

    tree.bind("<ButtonRelease-1>",click_row_zoom,add="+")
    ttk.Button(buttons,text="Zoom in ArcGIS Pro",command=zoom_selected).pack(side="left",padx=9)
    ttk.Button(buttons,text="Resend Windows Popup",command=resend_selected_popup).pack(side="left",padx=5)
    ttk.Button(buttons,text="Save Notes",command=lambda:update()).pack(side="left",padx=(0,9))
    ttk.Button(buttons,text="Mark Reviewed",command=lambda:update("REVIEWED")).pack(side="left",padx=9)
    ttk.Button(buttons,text="Reopen",command=lambda:update("OPEN")).pack(side="left",padx=9)
    ttk.Label(buttons,text="Review status does not change REG data.").pack(side="right")
    tree.bind("<<TreeviewSelect>>",on_selection)
    picker.bind("<<ComboboxSelected>>",lambda _evt:refresh())
    search.bind("<Return>",lambda _evt:refresh())

    def auto_refresh():
        # Do not overwrite the note editor while a supervisor is typing.
        # Refresh is explicit, but the open/total counters still update.
        try:
            conn,_=open_db()
            try:
                opened=conn.execute(
                    "SELECT COUNT(*) FROM alert_inbox WHERE review_status='OPEN'"
                ).fetchone()[0]
                total=conn.execute("SELECT COUNT(*) FROM alert_inbox").fetchone()[0]
            finally:
                conn.close()
            counter.configure(text=f"Open: {opened} | All: {total}")
        except Exception:
            pass
        root.after(15000,auto_refresh)
    refresh()
    root.after(15000,auto_refresh)
    root.mainloop()

def main(argv=None):
    parser=argparse.ArgumentParser(description="REPORTAPP local Quality Notification Inbox")
    parser.add_argument("--config",required=True,help="Existing monitor_config.json file")
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--list",action="store_true",help="Print recent alerts without GUI")
    mode.add_argument("--review",type=int,metavar="ID",help="Mark local alert reviewed")
    mode.add_argument("--reopen",type=int,metavar="ID",help="Reopen local alert")
    mode.add_argument("--resend-alert",type=int,metavar="ID",help="Operator-only resend of a verified saved LIVE Windows alert")
    mode.add_argument("--pole-manufacturer",choices=("include","exclude"),
                      help="Opt in/out of pole Manufacturer gaps in the existing live monitor")
    mode.add_argument("--add-user",action="append",metavar="USERNAME",help="Add monitored portal username without resetting the config")
    mode.add_argument("--remove-user",action="append",metavar="USERNAME",help="Remove monitored portal username without losing inbox history")
    mode.add_argument("--set-assets",nargs="+",metavar="ASSET",
                      help="Verify and set shared asset classes: line transformer pole")
    parser.add_argument("--note",help="Supervisor remark for --review/--reopen")
    options=parser.parse_args(argv)
    if options.pole_manufacturer is not None:
        from .notification_setup import set_pole_manufacturer_gap_check
        print(json.dumps(
            set_pole_manufacturer_gap_check(
                options.config, options.pole_manufacturer=="include"
            ),indent=2,ensure_ascii=False
        ))
        return 0
    if options.resend_alert is not None:
        print(json.dumps(resend_saved_alert(options.config,options.resend_alert),
                         indent=2,ensure_ascii=False))
        return 0
    if options.set_assets is not None:
        from .notification_setup import update_monitored_assets
        result=update_monitored_assets(options.config,options.set_assets)
        print(json.dumps(result,indent=2,ensure_ascii=False))
        return 0
    if options.add_user or options.remove_user:
        from .notification_setup import update_monitored_surveyors
        result=update_monitored_surveyors(
            options.config, add=options.add_user or (),
            remove=options.remove_user or (),
        )
        print(json.dumps(result,indent=2,ensure_ascii=False))
        return 0
    if not any((options.list,options.review is not None,options.reopen is not None)):
        launch_gui(options.config)
        return 0
    conn=connect_inbox(options.config)
    try:
        migration=import_legacy_events(options.config,conn)
        if options.list:
            data=[
                {"id":row["id"],"survey":row["username"],
                 "asset":row["asset"],"objectid":row["objectid"],
                 "issues":json.loads(row["issues_json"]),
                 "review":row["review_status"],
                 "delivery":row["delivery_status"],
                 "received":format_time(row["received_utc_ms"])}
                for row in list_alerts(conn,status="ALL")
            ]
            print(json.dumps({"alerts":data,"legacy_import":migration},
                             ensure_ascii=False,indent=2))
        else:
            rowid=options.review if options.review is not None else options.reopen
            status="REVIEWED" if options.review is not None else "OPEN"
            updated=set_review(conn,rowid,status,note=options.note)
            print(format_details(updated))
        return 0
    finally:
        conn.close()

if __name__=="__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"REPORTAPP INBOX ERROR: {exc}",file=sys.stderr)
        sys.exit(1)

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
        f"Delivery: {record['delivery_status']}",
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
    uri=zoom_uri(asset,str(objectid).strip())
    return enqueue(uri,folder=folder)


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
    names=("ID","Received","Surveyor","Asset","OBJECTID","Issues","Review","Delivery")
    tree=ttk.Treeview(tree_frame,columns=names,show="headings",height=11)
    widths=(65,175,135,100,115,65,100,110)
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
                    item["delivery_status"],
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
                enqueue(zoom_uri(item["asset"],item["objectid"]))
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

    ttk.Button(controls,text="Refresh",command=refresh).pack(side="left")
    ttk.Button(controls,text="Manage Surveyors",command=manage_surveyors).pack(
        side="left",padx=(8,0)
    )
    ttk.Button(controls,text="Clean Activity History",command=show_clean_activity).pack(
        side="left",padx=(8,0)
    )
    def zoom_selected():
        from .alert_navigation import enqueue, zoom_uri
        if selected_id[0] is None:
            return
        conn,_=open_db()
        try:
            rec=get_alert(conn,selected_id[0])
        finally:
            conn.close()
        if rec is None:
            return
        try:
            enqueue(zoom_uri(rec["asset"],rec["objectid"]))
            messagebox.showinfo("REPORTAPP navigation",
                "Navigation queued. Open ArcGIS Pro with the REPORTAPP add-in and a map. "
                "If navigation fails, inspect Navigation/bridge-errors.log under LOCALAPPDATA.",
                parent=root)
        except Exception as exc:
            messagebox.showerror("REPORTAPP navigation",str(exc),parent=root)

    ttk.Button(buttons,text="Zoom in ArcGIS Pro",command=zoom_selected).pack(side="left",padx=9)
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
    mode.add_argument("--add-user",action="append",metavar="USERNAME",help="Add monitored portal username without resetting the config")
    mode.add_argument("--remove-user",action="append",metavar="USERNAME",help="Remove monitored portal username without losing inbox history")
    mode.add_argument("--set-assets",nargs="+",metavar="ASSET",
                      help="Verify and set shared asset classes: line transformer pole")
    parser.add_argument("--note",help="Supervisor remark for --review/--reopen")
    options=parser.parse_args(argv)
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

"""Selected-surveyor read-only quality notifications, five-minute maturity.

Windows Task Scheduler executes this module via arcgispro-py3 once per minute.
This is a POLLING workflow, not a guaranteed event webhook. REG data are
never edited and the sender only receives an alert for a persisted current gap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import smtplib
import sys
import datetime as _dt
from email.message import EmailMessage

from .asset_quality import ASSETS, domain_map, evaluate_asset, resolve_fields
from .quality_watcher import (
    _domain_maps, _verified_phase_expectations,
    assess_line_quality, load_quality_rules,
)
from .phase_consistency import phase_type_conflict
from .progress_report import DEFAULT_LINE_SERVICE_URL,_get_gis,_layer_url,_query_with_retry
from .quality_query_batches import query_attributes_in_batches

LOOKBACK_HOURS=24
MAX_PER_ASSET=15000
MIN_AGE_SECONDS=300

def timestamp_ms(value):
    if isinstance(value, _dt.datetime):
        return int(value.timestamp()*1000)
    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
        return int(value)
    if isinstance(value,str) and value.strip().isdigit():
        return int(value.strip())
    return None


def event_timestamp(attrs):
    values=[timestamp_ms(attrs.get(key)) for key in ("created_date","last_edited_date")]
    return max((v for v in values if v is not None),default=None)


def submission_actor(attrs):
    """Latest create/edit actor; do not attribute another user's edit to creator."""
    created=timestamp_ms(attrs.get("created_date"))
    edited=timestamp_ms(attrs.get("last_edited_date"))
    if edited is not None and (created is None or edited>created):
        return str(attrs.get("last_edited_user") or "").strip(),"EDIT"
    return str(attrs.get("created_user") or "").strip(),"CREATE"


def record_findings(asset, attrs, fields,domains, line_rules=None,phase_expectations=None):
    """Existing QA gaps only, including pole height and Appendix Cable.

    No notifications for unresolved live schema fields: run logs warnings and
    requires schema correction instead of accusing every surveyor.
    """
    if asset in ("pole","transformer"):
        mapping=resolve_fields(fields,asset)
        result=evaluate_asset(attrs,asset,mapping,domains)
        return sorted(set(result["issues"])),list(result["unverified_checks"])
    if asset!="line":
        raise ValueError("Only LV Lines, LV Poles and Distribution Transformers supported.")
    if not line_rules:
        raise ValueError("Missing LV line quality rules.")
    quality=assess_line_quality(attrs,line_rules,domains)
    issues=list(quality["missing_attributes"])+list(quality["invalid_attributes"])
    phase_issue=phase_type_conflict(
        attrs, domains.get(int(attrs.get("ASSETGROUP") or 0),{}).get("Phases",{}),
        phase_expectations or {},
    )
    if phase_issue:
        issues.append(phase_issue)
    return sorted(set(issues)),[]


class State:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=15)
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sent (
                asset TEXT NOT NULL,
                objectid INTEGER NOT NULL,
                globalid TEXT NOT NULL,
                issue_digest TEXT NOT NULL,
                last_sent_at_ms INTEGER NOT NULL,
                PRIMARY KEY(asset,objectid,globalid)
            )
        """)
        self.db.commit()
    def close(self):
        self.db.close()
    def should_alert(self,asset,oid,gid,issues,actor):
        payload=json.dumps({"issues":sorted(set(issues)),"actor":actor},sort_keys=True,ensure_ascii=False)
        digest=hashlib.sha256(payload.encode("utf-8")).hexdigest()
        row=self.db.execute(
            "SELECT issue_digest FROM sent WHERE asset=? AND objectid=? AND globalid=?",
            (asset,int(oid),str(gid)),
        ).fetchone()
        return digest if not row or row[0]!=digest else None
    def mark_sent(self,asset,oid,gid,digest,now_ms):
        self.db.execute("""
            INSERT INTO sent(asset,objectid,globalid,issue_digest,last_sent_at_ms)
            VALUES(?,?,?,?,?)
            ON CONFLICT(asset,objectid,globalid) DO UPDATE SET
              issue_digest=excluded.issue_digest,
              last_sent_at_ms=excluded.last_sent_at_ms
        """,(asset,int(oid),str(gid),digest,int(now_ms)))
        self.db.commit()
    def clear_fixed(self,asset,oid,gid):
        self.db.execute(
            "DELETE FROM sent WHERE asset=? AND objectid=? AND globalid=?",
            (asset,int(oid),str(gid)),
        )
        self.db.commit()


def ready_alerts(records,asset,fields,domains,config,now_ms,state,line_rules=None,
                 phase_expectations=None):
    output=[]
    default_cutoff=int(config["enabled_at_utc_ms"])
    account_cutoffs=config.get("enabled_at_by_username_utc_ms") or {}
    asset_cutoffs=config.get("enabled_at_by_asset_utc_ms") or {}
    watch={str(u).casefold() for u in config["usernames"]}
    for a in records:
        oid=a.get("OBJECTID");gid=a.get("GLOBALID")
        username,event_type=submission_actor(a)
        submitted=event_timestamp(a)
        if username.casefold() not in watch or oid is None or not gid or submitted is None:
            continue
        cutoff=max(
            default_cutoff,
            int(account_cutoffs.get(username.casefold(),default_cutoff)),
            int(asset_cutoffs.get(asset,default_cutoff)),
        )
        if submitted<cutoff or submitted>now_ms-MIN_AGE_SECONDS*1000:
            continue
        issues,unverified=record_findings(
            asset,a,fields,domains,line_rules,phase_expectations
        )
        if unverified:
            raise RuntimeError(
                f"Cannot safely alert for {asset}: unresolved required template "
                f"checks {unverified}. Correct the live field mapping first."
            )
        if not issues:
            state.clear_fixed(asset,oid,gid)
            continue
        digest=state.should_alert(asset,oid,gid,issues,username)
        if digest:
            output.append({
                "asset":asset,"objectid":int(oid),"globalid":str(gid),
                "username":username,"event_type":event_type,
                "created_user":str(a.get("created_user") or ""),
                "last_edited_user":str(a.get("last_edited_user") or ""),
                "event_time_utc_ms":submitted,"issues":issues,"issue_digest":digest,
            })
    return output


def _feature_rows(layer,version,where,fields,asset):
    records=query_attributes_in_batches(
        layer,where,version,fields,[("Selected surveyor activity (national)",None)],
        _query_with_retry,batch_size=120,asset_label=asset,
        duplicate_globalid_policy="report",
    )
    if len(records)>MAX_PER_ASSET:
        raise RuntimeError(
            f"{asset}: {len(records)} changed features exceed {MAX_PER_ASSET}. "
            "Narrow monitored accounts; no alerts sent for partial scans."
        )
    return records


def _monitor_gis(config, gis=None):
    """Use ArcGIS Pro credentials or an explicitly configured local profile.

    The profile stores no password in REPORTAPP's configuration. ArcGIS API
    for Python manages its stored credentials via the OS credential manager.
    """
    if gis is not None:
        return gis
    profile = str(
        config.get("arcgis_profile") or
        os.environ.get("REPORTAPP_ARCGIS_PROFILE") or ""
    ).strip()
    if profile:
        from arcgis.gis import GIS
        try:
            return GIS(profile=profile)
        except Exception as exc:
            raise RuntimeError(
                f"Saved ArcGIS profile {profile!r} failed to authenticate. "
                "Check the profile under this Windows account; do not put "
                "the portal password in the REPORTAPP JSON."
            ) from exc
    try:
        return _get_gis(None)
    except Exception as exc:
        raise RuntimeError(
            "ArcGIS Pro authentication unavailable in this standalone "
            "monitor process. Sign in to the correct Enterprise portal in "
            "ArcGIS Pro with 'Sign me in automatically', then retry "
            "--preflight with the ArcGIS Pro Python interpreter. "
            "Alternatively configure a secured local ArcGIS profile using "
            "arcgis_profile in monitor_config.json or the "
            "REPORTAPP_ARCGIS_PROFILE user environment variable. "
            "Never store a password in the JSON."
        ) from exc


def collect(config,now_ms=None,gis=None,source_url=None):
    """Return complete current quality findings across all eligible assets.

    Every layer must finish successfully before sending any notifications.
    """
    from arcgis.features import FeatureLayer
    now_ms=now_ms or int(_dt.datetime.now(_dt.timezone.utc).timestamp()*1000)
    start_ms=max(
        int(config["enabled_at_utc_ms"]),
        now_ms-LOOKBACK_HOURS*3600*1000,
    )
    start=_dt.datetime.fromtimestamp(start_ms/1000,_dt.timezone.utc)
    # The existing ArcGIS Enterprise layer supports TIMESTAMP predicates.
    # Widen a day, then exact-filter client-side to avoid timezone cutoffs.
    start_day=(start-_dt.timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    accounts=sorted(set(config["usernames"]),key=str.casefold)
    if not accounts:
        raise ValueError("Choose at least one surveyor to watch.")
    quoted=",".join("'"+user.replace("'","''")+"'" for user in accounts)
    base=str(source_url or config.get("feature_service_url") or DEFAULT_LINE_SERVICE_URL).rstrip("/")
    active=_monitor_gis(config,gis)
    result={}
    for asset in config.get("assets",["line","transformer","pole"]):
        if asset not in ("line","transformer","pole"):
            raise ValueError(f"Unsupported monitored asset: {asset}")
        if asset=="line":
            spec_group=(9,10);lid=10
            rules=load_quality_rules()
        else:
            lid=ASSETS[asset]["layer_id"]
            spec_group=(ASSETS[asset]["asset_group"],)
            rules=None
        layer=FeatureLayer(_layer_url(base,lid),active)
        schema=[dict(f) for f in layer.properties.fields]
        available={f["name"].casefold():f["name"] for f in schema}
        required=["OBJECTID","GLOBALID","ASSETGROUP","ASSETTYPE",
                  "created_user","created_date","last_edited_date","last_edited_user"]
        if asset=="line":
            required.extend(x["field"] for x in rules["scored_attributes"])
            required.extend(["Notes"])
        else:
            fieldmap=resolve_fields(schema,asset)
            if any(not fieldmap.get(key) for key in ASSETS[asset]["priority"]):
                raise RuntimeError(
                    f"{asset} live schema does not resolve priority fields. "
                    "Monitor not started; no misleading alerts."
                )
            if asset=="pole" and not fieldmap.get("height"):
                raise RuntimeError(
                    "Pole height field cannot be verified; configure live height "
                    "attribute before pole monitoring. No alerts sent."
                )
            required.extend(field for field in fieldmap.values() if field)
        missing=[f for f in required if f.casefold() not in available]
        if missing:
            raise RuntimeError(f"{asset} missing live template columns: {missing}")
        groups=",".join(map(str,spec_group))
        where=(
            f"ASSETGROUP IN ({groups}) AND "
            f"(created_user IN ({quoted}) OR last_edited_user IN ({quoted})) AND "
            "((created_date >= TIMESTAMP '"+start_day+"') OR "
            "(last_edited_date >= TIMESTAMP '"+start_day+"'))"
        )
        if asset in ("pole","transformer"):
            where+=" AND ASSETTYPE IN ("+",".join(map(str,sorted(ASSETS[asset]["types"])))+")"
        fields=list(dict.fromkeys(available[name.casefold()] for name in required))
        records=_feature_rows(layer,config.get("version","sde.DEFAULT"),where,fields,asset)
        records=[r for r in records if (event_timestamp(r) or 0)>=start_ms]
        if asset=="line":
            domains=_domain_maps(layer)
            expectations=_verified_phase_expectations(domains)
        else:
            domains=domain_map(layer.properties,ASSETS[asset]["asset_group"])
            expectations=None
        result[asset]=(records,schema,domains,rules,expectations)
    return result


def preflight(config_path, *, collector=None, now_ms=None, check_delivery=True):
    """Verify standalone GIS/schema access without alerts or SQLite changes."""
    path=Path(config_path).resolve()
    config=json.loads(path.read_text(encoding="utf-8"))
    if config.get("enabled") is not True:
        raise ValueError("Monitoring config is disabled.")
    if not config.get("usernames") or not config.get("assets"):
        raise ValueError("Select monitored usernames and assets first.")
    if check_delivery and config.get("channel","desktop") == "desktop":
        import importlib.util
        if importlib.util.find_spec("winotify") is None:
            raise RuntimeError(
                "winotify unavailable in this Python environment. "
                "Install it in the ArcGIS Pro Python environment before "
                "activating desktop notifications."
            )
    now_ms=int(now_ms if now_ms is not None else _dt.datetime.now(_dt.timezone.utc).timestamp()*1000)
    snapshots=(collector or collect)(config,now_ms=now_ms)
    expected=set(config["assets"])
    if set(snapshots)!=expected:
        raise RuntimeError(
            f"Incomplete monitoring scan: expected {sorted(expected)}, "
            f"received {sorted(snapshots)}. No alerts sent."
        )
    counts={}
    for asset, (records, fields, domains, rules, expectations) in snapshots.items():
        counts[asset]=len(records)
        # Check QA mappings on a real record where available; the collector
        # already validates source fields even when there are zero matches.
        if records:
            _,unverified=record_findings(
                asset,records[0],fields,domains,rules,expectations
            )
            if unverified:
                raise RuntimeError(
                    f"{asset} has unresolved live template checks: {unverified}"
                )
    return {
        "status":"PREFLIGHT_OK",
        "monitoring_is_active":False,
        "data_source_modified":False,
        "notifications_sent":0,
        "selected_accounts":list(config["usernames"]),
        "asset_record_counts":counts,
        "authentication_test":"FeatureServer reads succeeded" if collector is None
                               else "Injected test collector",
        "next_step":"Perform --send-test then install the scheduled monitor.",
    }


def _alert_text(alert):
    source_date=_dt.datetime.fromtimestamp(
        int(alert.get("event_time_utc_ms") or 0)/1000,
        _dt.timezone(_dt.timedelta(hours=2))
    ).strftime("%Y-%m-%d %H:%M Rwanda time")
    prefix=(
        "HISTORICAL RECORD — for retrospective review.\n"
        if alert.get("deferred_historical") else ""
    )
    version=str(alert.get("source_gdb_version") or "sde.DEFAULT")
    return (
        prefix+f"Source event: {source_date} [GIS version: {version}]\n"
        f"{alert['asset'].upper()} | {alert['username']} ({alert['event_type']}) | "
        f"ObjectID {alert['objectid']}\n"
        f"GlobalID {alert['globalid']}\n"
        +"Missing/invalid: "+"; ".join(alert["issues"])
        +f"\nCreated by: {alert['created_user']} | Last edited by: {alert['last_edited_user']}"
        +"\nLogin attribution may require historical account transfer review."
    )


def deliver(alert,config):
    """Selected local desktop notification or recipient email. Never silent."""
    channel=config.get("channel","desktop")
    subject=(
        f"REG QA HISTORICAL: {alert['asset']} - {alert['username']}"
        if alert.get("deferred_historical") else
        f"REG QA: {alert['asset']} gaps - {alert['username']}"
    )
    message=_alert_text(alert)
    if channel=="desktop":
        try:
            from winotify import Notification
        except ImportError as exc:
            raise RuntimeError(
                "Windows desktop alert library not installed. Run "
                "'python -m pip install winotify' in arcgispro-py3, "
                "or choose SMTP email channel."
            ) from exc
        # Only advertise click-to-zoom after the current Windows user has
        # registered the reportapp:// handler. The ArcGIS Pro add-in is a
        # separate required component; without it the request stays queued.
        from .alert_navigation import is_registered,zoom_uri
        launch=""
        if is_registered():
            context={
                "globalid":alert.get("globalid"),
                "event_time_utc_ms":alert.get("event_time_utc_ms"),
                "actor":alert.get("username"),
                "gdb_version":config.get("version","sde.DEFAULT"),
            }
            if all(context.values()):
                launch=zoom_uri(alert["asset"],alert["objectid"],**context)
            # Do not show an unverified clickable link for a legacy alert
            # missing source-event identity.
        popup=Notification(
            app_id="REPORTAPP Quality Alerts",title=subject,
            msg=message[:400],duration="long",launch=launch,
        )
        if launch:
            popup.add_actions(label="Zoom in ArcGIS Pro",launch=launch)
        popup.show()
    elif channel=="smtp":
        host=os.environ.get("REPORTAPP_ALERT_SMTP_HOST")
        user=os.environ.get("REPORTAPP_ALERT_SMTP_USER")
        secret=os.environ.get("REPORTAPP_ALERT_SMTP_PASSWORD")
        recipient=config.get("recipient_email")
        sender=os.environ.get("REPORTAPP_ALERT_SMTP_FROM") or user
        if not all((host,secret,recipient,sender)):
            raise RuntimeError("SMTP recipient or secure environment configuration missing.")
        email=EmailMessage()
        email["From"]=sender
        email["To"]=recipient
        email["Subject"]=subject
        email.set_content(message)
        port=int(os.environ.get("REPORTAPP_ALERT_SMTP_PORT","587"))
        with smtplib.SMTP(host,port,timeout=15) as smtp:
            smtp.starttls()
            if user:smtp.login(user,secret)
            smtp.send_message(email)
    else:
        raise ValueError("Notification channel must be desktop or smtp.")


def run_once(config_path,now_ms=None,collector=None,sender=None,
             activity_sender=None,heartbeat_sender=None):
    """One atomic-quality survey cycle; source scan succeeds before deliveries.

    Existing issues prior to monitor enable time are not notified. Desktop
    Task Scheduler must run once each minute for ~5-6 minute maturity.
    """
    path=Path(config_path).resolve()
    config=json.loads(path.read_text(encoding="utf-8"))
    if config.get("enabled") is not True:
        raise ValueError("Notification monitoring disabled in configuration.")
    now_ms=now_ms or int(_dt.datetime.now(_dt.timezone.utc).timestamp()*1000)
    state=State(path.with_suffix(".sqlite3"))
    logfile=path.with_suffix(".events.jsonl")
    collector=collector or collect
    sender=sender or deliver
    try:
        # Migrate historical real SENT events without reissuing notifications.
        from .notification_inbox import (record_alert, mark_delivery,
                                         import_legacy_events)
        import_legacy_events(path,state.db)
        # Fetch and validate ALL monitored services before alert delivery.
        snapshots=collector(config,now_ms=now_ms)
        if set(snapshots)!=set(config.get("assets",[])):
            raise RuntimeError("Incomplete monitored asset scan; no alerts sent.")
        scanned={asset:len(snapshot[0]) for asset,snapshot in snapshots.items()}
        notices=[]
        for asset,(records,fields,domains,rules,phase_expectations) in snapshots.items():
            notices.extend(ready_alerts(
                records,asset,fields,domains,config,now_ms,state,
                rules,phase_expectations
            ))
        # Previous-day (Rwanda local date) notifications are retained for
        # off-site delivery; today's alerts remain immediate.
        from .deferred_notifications import plan_delivery, mark_delivered, is_historical
        deliveries,deferred_count=plan_delivery(
            notices,snapshots,config,now_ms,state.db
        )
        sent=0
        failed=0
        historical_sent=0
        for item in deliveries:
            # Persist first so any transient popup cannot be the only record.
            inbox_id=record_alert(state.db,item,now_ms)
            try:
                sender(item,config)
            except Exception as exc:
                mark_delivery(state.db,inbox_id,"SEND_FAILED",str(exc))
                with logfile.open("a",encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "at_utc_ms":now_ms,"status":"SEND_FAILED",
                        "asset":item["asset"],"objectid":item["objectid"],
                        "reason":str(exc),
                    })+"\n")
                failed+=1
                continue
            state.mark_sent(
                item["asset"],item["objectid"],item["globalid"],
                item["issue_digest"],now_ms
            )
            mark_delivered(state.db,item)
            mark_delivery(state.db,inbox_id,"SENT")
            with logfile.open("a",encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "at_utc_ms":now_ms,"status":"SENT",
                    "asset":item["asset"],"objectid":item["objectid"],
                    "globalid":item["globalid"],"username":item["username"],
                    "source_event_utc_ms":item["event_time_utc_ms"],
                    "source_gdb_version":config.get("version","sde.DEFAULT"),
                    "source_event_type":item["event_type"],
                    "source_last_editor":item["last_edited_user"],
                    "issues":item["issues"],
                },ensure_ascii=False)+"\n")
            sent+=1
            if is_historical(item["event_time_utc_ms"],now_ms):
                historical_sent+=1
        activity_result={}
        if config.get("activity_notifications_enabled"):
            from .surveyor_activity import process_activity
            activity_result=process_activity(
                snapshots,config,now_ms,state.db,
                {"records_scanned":scanned,"qa_alerts_sent":sent},
                clean_sender=activity_sender,
                heartbeat_sender=heartbeat_sender,
            )
        return {"alerts_sent":sent,"alerts_considered":len(notices),
                "alerts_delivery_failed":failed+activity_result.get("clean_notifications_failed",0)
                                     +activity_result.get("heartbeat_failed",0),
                "records_scanned":scanned,
                "channel":config.get("channel","desktop"),
                "historical_alerts_queued":deferred_count,
                "historical_alerts_released_this_scan":historical_sent,
                **activity_result}
    finally:
        state.close()


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",required=True)
    operation=parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--send-test",action="store_true",
        help="Send one marked TEST alert to the configured channel (no GIS query).",
    )
    operation.add_argument(
        "--preflight",action="store_true",
        help="Verify GIS access, schemas and delivery dependency without alerts.",
    )
    operation.add_argument(
        "--enable-activity",action="store_true",
        help="Start desktop notifications for newly clean surveyor events, from NOW; keep error alerts unchanged.",
    )
    operation.add_argument(
        "--disable-activity",action="store_true",
        help="Stop clean activity and heartbeat popups; keep watcher and error alerts running.",
    )
    operation.add_argument(
        "--send-activity-test",action="store_true",
        help="One clearly marked Windows TEST popup; no scan, no QA result, no database change.",
    )
    operation.add_argument(
        "--list-activity",action="store_true",
        help="List previously delivered clean feature activity without changing QA alert inbox.",
    )
    parser.add_argument("--test-asset",choices=("line","pole","transformer"),
                        default="line",help="Navigation asset for --send-activity-test")
    parser.add_argument("--test-objectid",type=int,
                        help="Navigation OBJECTID for --send-activity-test")
    parser.add_argument("--heartbeat-minutes",type=int,default=60,
                        help="When enabling activity, send watcher status every 10–240 minutes (default 60).")
    options=parser.parse_args(argv)
    path=Path(options.config).resolve()
    log=path.with_suffix(".monitor.log")
    try:
        if options.send_activity_test:
            if options.test_objectid is None or options.test_objectid<=0:
                raise ValueError("--send-activity-test requires --test-objectid (a positive integer).")
            from .surveyor_activity import deliver_activity_test
            deliver_activity_test(options.test_asset,options.test_objectid)
            print("REPORTAPP_ACTIVITY_TEST_SENT (no QA evaluation or history write)")
            return 0
        if options.enable_activity or options.disable_activity:
            from .surveyor_activity import change_activity_mode
            result=change_activity_mode(
                path,options.enable_activity,
                heartbeat_minutes=options.heartbeat_minutes,
            )
            print(json.dumps(result,indent=2,ensure_ascii=False))
            return 0
        if options.list_activity:
            from .surveyor_activity import list_recent_activity
            state=State(path.with_suffix(".sqlite3"))
            try:
                print(json.dumps({"clean_activity":list_recent_activity(state.db)},
                                 indent=2,ensure_ascii=False))
            finally:
                state.close()
            return 0
        if options.send_test:
            config=json.loads(path.read_text(encoding="utf-8"))
            test={
                "asset":"TEST","username":"REPORTAPP","event_type":"TEST",
                "objectid":0,"globalid":"TEST-ONLY",
                "created_user":"TEST","last_edited_user":"TEST",
                "issues":["Delivery test only; no real surveyor record"],
            }
            deliver(test,config)
            with log.open("a",encoding="utf-8") as fh:
                fh.write(f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} TEST_NOTIFICATION_SENT\n")
            return 0
        if options.preflight:
            result=preflight(path)
            print(json.dumps(result,indent=2,ensure_ascii=False))
            with log.open("a",encoding="utf-8") as fh:
                fh.write(f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} {result}\n")
            return 0
        result=run_once(path)
        with log.open("a",encoding="utf-8") as fh:
            fh.write(f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} {result}\n")
        return 0
    except Exception as exc:
        # Always report the *original* failure to the command-line operator.
        # Failure to write the optional log must never hide a GIS/auth error.
        print(
            f"REPORTAPP MONITOR ERROR ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        try:
            with log.open("a",encoding="utf-8") as fh:
                fh.write(
                    f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} "
                    f"ERROR {type(exc).__name__}: {exc}\n"
                )
        except Exception as log_exc:
            print(
                f"REPORTAPP monitor log unavailable: {log_exc}",
                file=sys.stderr,
            )
        return 1


if __name__=="__main__":
    sys.exit(main())

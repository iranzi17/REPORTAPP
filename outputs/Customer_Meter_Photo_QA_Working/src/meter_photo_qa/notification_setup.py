"""Explicit local setup of selected-user five-minute quality notifications."""
from __future__ import annotations

from datetime import datetime,timezone
from pathlib import Path
import json
import os
import re
import sys
import shutil
import tempfile

from .smart_query import USER_NAMES_PATH,resolve_surveyor_name

TASK_NAME="REPORTAPP Surveyor Quality Alerts"
POLL_MINUTES=1


def _ps_single(text):
    return "'"+str(text).replace("'","''")+"'"

def chosen_usernames(raw):
    """Accept selected portal logins or display names, never partial names."""
    known=json.loads(USER_NAMES_PATH.read_text(encoding="utf-8"))
    choices=[x.strip() for x in raw if str(x).strip()]
    if not choices:
        raise ValueError("Choose at least one surveyor to monitor.")
    accounts=[]
    for item in choices:
        if item in known:
            user=item
        else:
            prefix=item.split(" — ",1)[0].strip()
            if prefix in known:
                user=prefix
            else:
                user=resolve_surveyor_name(item,None)
        if user not in accounts:
            accounts.append(user)
    return accounts


def _standalone_python(python_path):
    """Avoid scheduling ArcGISPro.exe from its embedded Python session."""
    supplied=Path(python_path or sys.executable).expanduser().resolve()
    if supplied.name.casefold() in ("python.exe", "pythonw.exe") and supplied.is_file():
        return supplied
    for prefix in (sys.prefix, sys.exec_prefix):
        candidate=Path(prefix).expanduser().resolve()/"python.exe"
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        f"Cannot identify a standalone Python interpreter from {supplied}. "
        "Run setup from an ArcGIS Pro Python environment containing python.exe; "
        "do not register ArcGISPro.exe as a scheduled Python task."
    )


def _powershell(config_path,python_path,src_path):
    executable=_standalone_python(python_path)
    pyw=executable.with_name("pythonw.exe")
    if not pyw.exists():
        pyw=executable
    return f"""# REPORTAPP scheduled notification checker — install once while signed into Windows.
# Triggers every minute. An alert is eligible 5 minutes after a created/edited event.
# Task runs only when this Windows user is logged in (desktop notification visible).
$ErrorActionPreference = 'Stop'
$Action = New-ScheduledTaskAction -Execute {_ps_single(str(pyw))} -Argument {_ps_single('-m meter_photo_qa.surveyor_notifications --config "'+str(config_path)+'"')} -WorkingDirectory {_ps_single(str(src_path))}
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName {_ps_single(TASK_NAME)} -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Host 'REPORTAPP monitoring scheduled every minute. Check the .monitor.log and .events.jsonl files alongside the config.'
"""


def configure_monitoring(
    usernames,output_folder,
    channel="desktop",recipient_email=None,
    assets=("line","transformer","pole"),
    python_path=None,src_path=None,
    now_ms=None,
    replace_existing=False,
):
    if channel not in ("desktop","smtp"):
        raise ValueError("Channel must be desktop or smtp.")
    if channel=="smtp":
        if not recipient_email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",recipient_email):
            raise ValueError("SMTP notifications require a valid recipient email.")
    if not set(assets).issubset({"line","transformer","pole"}) or not assets:
        raise ValueError("Select a valid non-empty set of monitored asset classes.")
    selected=chosen_usernames(usernames)
    target=Path(output_folder).expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"Notification output folder does not exist: {target}")
    dest=target/"REPORTAPP_Surveyor_Notifications"
    dest.mkdir(parents=True,exist_ok=True)
    config=dest/"monitor_config.json"
    install=dest/"Install_One_Minute_Monitor.ps1"
    if config.exists() and not replace_existing:
        raise FileExistsError(
            "Monitoring config already exists and Replace existing was not enabled. "
            "For adding/removing surveyors, open the REPORTAPP Quality "
            "Notification Inbox and click Manage Surveyors. The existing "
            "configuration, monitoring start date, and inbox are preserved. "
            "Use full replacement only when explicitly resetting the setup."
        )
    enable=int(now_ms or datetime.now(timezone.utc).timestamp()*1000)
    data={
        "enabled":True,
        "enabled_at_utc_ms":enable,
        "usernames":selected,
        "assets":list(assets),
        "channel":channel,
        "recipient_email":recipient_email if channel=="smtp" else None,
        "version":"sde.DEFAULT",
        "feature_service_url":"https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer",
        "poll_interval_seconds":60,
        "minimum_notification_age_seconds":300,
        "lookback_hours":24,
        "notices_sent_at_setup":0,
        "source_data_edits":False,
    }
    source=Path(src_path or Path(__file__).resolve().parents[1]).resolve()
    py=_standalone_python(python_path or sys.executable)
    config.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    install.write_text(_powershell(config,py,source),encoding="utf-8-sig")
    return {
        "configuration":str(config),
        "installation_script":str(install),
        "python_executable":str(py),
        "watching_usernames":selected,
        "selected_asset_classes":list(assets),
        "notification_channel":channel,
        "next_step":"Run installation script in Windows PowerShell under your logged-in account.",
        "task_name":TASK_NAME,
        "actively_running":False,
        "alerts_sent":0,
    }


def update_monitored_surveyors(config_path, *, add=(), remove=(), now_ms=None):
    """Add/remove existing monitor accounts without touching notification history.

    Preserves the original activation cutoff for existing users. New accounts
    receive their own activation cutoff, so past bad records never generate a
    retroactive burst of alerts. Atomic replacement tolerates Task Scheduler
    reading the config at the same time.
    """
    path=Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Existing REPORTAPP monitor config not found: {path}")
    current=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(current,dict) or not isinstance(current.get("usernames"),list):
        raise ValueError("Existing monitoring config is invalid; not overwritten.")
    if not current.get("assets") or "enabled_at_utc_ms" not in current:
        raise ValueError("Monitoring assets or original start time unavailable.")
    original=list(current["usernames"])
    if not original:
        raise ValueError("Existing monitoring accounts missing.")
    new_accounts=chosen_usernames(add) if add else []
    removals={str(value).strip().casefold() for value in remove if str(value).strip()}
    if any(" — " in x for x in removals):
        raise ValueError("Remove surveyors by exact portal username.")
    if not new_accounts and not removals:
        raise ValueError("Select at least one surveyor to add or remove.")
    original_lower={s.casefold():s for s in original}
    missing=removals-original_lower.keys()
    if missing:
        raise ValueError("Cannot remove accounts not monitored: "+", ".join(sorted(missing)))
    preserved=[s for s in original if s.casefold() not in removals]
    seen={s.casefold() for s in preserved}
    added=[]
    for username in new_accounts:
        if username.casefold() not in seen:
            preserved.append(username)
            added.append(username)
            seen.add(username.casefold())
    if not preserved:
        raise ValueError("Cannot remove the last monitored surveyor.")
    if preserved==original:
        return {
            "status":"UNCHANGED","usernames":preserved,
            "added":[],"removed":[],"config_path":str(path),
            "original_enabled_at_utc_ms":int(current["enabled_at_utc_ms"]),
        }
    cutoff=int(current["enabled_at_utc_ms"])
    stamp=int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp()*1000)
    if stamp<cutoff:
        raise ValueError("New account start time precedes monitor activation.")
    prior=current.get("enabled_at_by_username_utc_ms") or {}
    if not isinstance(prior,dict):
        raise ValueError("Existing per-surveyor activation map invalid.")
    # Existing accounts inherit the old activation timestamp if the config
    # was created before per-surveyor timestamps were introduced.
    times={s.casefold():int(prior.get(s.casefold(),cutoff))
           for s in preserved if s.casefold() in original_lower}
    for username in added:
        times[username.casefold()]=stamp
    current["usernames"]=preserved
    current["enabled_at_by_username_utc_ms"]=times
    tmp_path=None
    # The timestamped backup keeps only configuration data, not SQLite state.
    backup=path.with_name(
        path.stem+"_backup_"+datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        +path.suffix
    )
    shutil.copy2(path,backup)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",encoding="utf-8",dir=path.parent,
            prefix="."+path.stem+"_",suffix=".tmp",delete=False
        ) as stream:
            tmp_path=Path(stream.name)
            json.dump(current,stream,indent=2,ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path,path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    return {
        "status":"UPDATED","usernames":preserved,
        "added":added,
        "removed":[s for s in original if s.casefold() in removals],
        "config_path":str(path),"backup":str(backup),
        "original_enabled_at_utc_ms":cutoff,
        "new_account_start_utc_ms":stamp if added else None,
    }

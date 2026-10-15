"""Explicit local setup of selected-user five-minute quality notifications."""
from __future__ import annotations

from datetime import datetime,timezone
from pathlib import Path
import json
import os
import re
import sys

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
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -LogonType Interactive -RunLevel LeastPrivilege
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
            "Monitoring config already exists. Back up current notification "
            "state and stop the scheduled task before reconfiguring monitored accounts."
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

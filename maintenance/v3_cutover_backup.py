"""Read-only REPORTAPP office cutover backup: task XML and URL protocol.

Creates LOCAL, PRIVATE, byte-verified rollback evidence. Never changes any
Scheduled Task, registry key, REG GIS feature, existing SQLite or source file.
This is backup preparation, NOT permission or proof to perform a cutover.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

TASK_NAME = "REPORTAPP Surveyor Quality Alerts"
REG_KEY = r"Software\Classes\reportapp"
MAX_TASK_XML = 512_000


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _write_new_file(path, data):
    # Refuse overwrite and linked files, avoiding modifications to an earlier
    # known-good backup after a later unsuccessful attempt.
    path = Path(path)
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def _get_task_xml():
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler export requires Windows")
    command = (
        "$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
        "Export-ScheduledTask -TaskName 'REPORTAPP Surveyor Quality Alerts'"
    )
    run = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if run.returncode:
        raise RuntimeError("Unable to export original task; no task changes attempted")
    result = run.stdout
    if not result.strip() or len(result.encode("utf-8")) > MAX_TASK_XML:
        raise RuntimeError("Original Task Scheduler definition missing or oversized")
    return result


def _get_registry():
    if os.name != "nt":
        raise RuntimeError("Windows HKCU registry inspection requires Windows")
    import winreg

    def item(subkey, name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0,
                                winreg.KEY_READ) as key:
                value, kind = winreg.QueryValueEx(key, name)
                return {"present": True, "value": value, "value_type": int(kind)}
        except FileNotFoundError:
            return {"present": False}

    return {
        "root_default": item(REG_KEY, ""),
        "url_protocol": item(REG_KEY, "URL Protocol"),
        "open_command": item(REG_KEY + r"\shell\open\command", ""),
    }


def _first(parent, local_name):
    return next((node for node in parent.iter()
                 if node.tag.split("}")[-1] == local_name), None)


def analyze_task_xml(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("Cannot parse original Task Scheduler export") from exc
    if root.tag.split("}")[-1] != "Task":
        raise ValueError("Unexpected Task Scheduler XML root")
    actions = _first(root, "Actions")
    if actions is None:
        raise ValueError("Original task export has no Actions")
    execs = [node for node in actions
             if node.tag.split("}")[-1] == "Exec"]
    info = {"has_single_exec": len(execs) == 1,
            "pythonw_executable": False,
            "legacy_watcher_module": False,
            "original_config_argument": False,
            "working_directory_present": False,
            "interval_one_minute": False,
            "ignore_overlapping_runs": False}
    if len(execs) == 1:
        exec_node = execs[0]
        val = lambda key: next(
            (str(ch.text or "").strip() for ch in exec_node
             if ch.tag.split("}")[-1] == key), "")
        command = val("Command").strip('"')
        args = val("Arguments")
        info.update({
            "pythonw_executable": Path(command.replace("\\", "/")).name.casefold() == "pythonw.exe",
            "legacy_watcher_module": "meter_photo_qa.surveyor_notifications" in args,
            "original_config_argument": "--config" in args and "monitor_config.json" in args,
            "working_directory_present": bool(val("WorkingDirectory")),
        })
    for node in root.iter():
        simple = node.tag.split("}")[-1]
        value = str(node.text or "").strip()
        if simple == "Interval" and value == "PT1M":
            info["interval_one_minute"] = True
        if simple == "MultipleInstancesPolicy" and value == "IgnoreNew":
            info["ignore_overlapping_runs"] = True
    return info


def analyze_registry(snapshot):
    key = snapshot.get("open_command") or {}
    root = snapshot.get("url_protocol") or {}
    cmd = key.get("value", "") if key.get("present") else ""
    return {
        "url_protocol_registered": bool(root.get("present")),
        "handler_present": bool(key.get("present")),
        "python_handler_target": (
            isinstance(cmd, str)
            and "alert_navigation.py" in cmd
            and '--uri "%1"' in cmd
        ),
    }


def capture(directory=None, *, task_xml_supplier=_get_task_xml,
            registry_supplier=_get_registry):
    """Save original configuration only. No live changes and no restore attempt."""
    if directory is None:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        directory = local / "REPORTAPP" / "Maintenance" / "v3" / "cutover_backups"
    directory = Path(directory)
    # Read first. Failure of either read never creates a misleading backup.
    xml = task_xml_supplier()
    xml_bytes = xml.encode("utf-8")
    if not (0 < len(xml_bytes) <= MAX_TASK_XML):
        raise ValueError("Task XML invalid or oversized")
    checks = analyze_task_xml(xml)
    registry = registry_supplier()
    reg_checks = analyze_registry(registry)
    snapshot = json.dumps(registry, indent=2, sort_keys=True).encode("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / (stamp + "-" + uuid.uuid4().hex[:8])
    target.mkdir(exist_ok=False)
    task_backup = target / "task_before.xml"
    handler_backup = target / "protocol_before.json"
    _write_new_file(task_backup, xml_bytes)
    _write_new_file(handler_backup, snapshot)
    receipts = {"format": 1, "task_filename": "task_before.xml",
                "task_sha256": _hash(xml_bytes),
                "protocol_filename": "protocol_before.json",
                "protocol_sha256": _hash(snapshot),
                "backed_up_utc": datetime.now(timezone.utc).isoformat(),
                "task_checks": checks, "handler_checks": reg_checks,
                "backup_verified": False, "rollback_rehearsed": False,
                "changes_to_live_task": False, "changes_to_registry": False,
                "cutover_authorized": False}
    _write_new_file(target / "manifest.json",
                    json.dumps(receipts, indent=2, sort_keys=True).encode("utf-8"))
    return verify_backup(target)


def verify_backup(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("task_filename") != "task_before.xml"
            or manifest.get("protocol_filename") != "protocol_before.json"):
        raise ValueError("Untrusted rollback manifest file name")
    task = folder / "task_before.xml"
    protocol = folder / "protocol_before.json"
    if task.is_symlink() or protocol.is_symlink():
        raise ValueError("Backup files cannot be symbolic links")
    if (_hash(task.read_bytes()) != manifest["task_sha256"] or
            _hash(protocol.read_bytes()) != manifest["protocol_sha256"]):
        raise ValueError("Local rollback backup checksum mismatch")
    task_checks = analyze_task_xml(task.read_text(encoding="utf-8"))
    reg_checks = analyze_registry(json.loads(protocol.read_text(encoding="utf-8")))
    if task_checks != manifest["task_checks"] or reg_checks != manifest["handler_checks"]:
        raise ValueError("Original backup no longer matches its audited checks")
    all_ready = all(task_checks.values()) and all(reg_checks.values())
    return {
        "status": "BACKUP_VERIFIED_ONLY" if all_ready else "BACKUP_REQUIRES_REVIEW",
        "original_task_evidence_saved": True,
        "original_registry_evidence_saved": True,
        "task_checks": task_checks,
        "protocol_checks": reg_checks,
        "backup_task_sha256": manifest["task_sha256"],
        "backup_protocol_sha256": manifest["protocol_sha256"],
        "backup_folder": str(folder),
        "rollback_rehearsed": False,
        "production_task_changed": False,
        "production_registry_changed": False,
        "cutover_authorized": False,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Back up REPORTAPP task and handler without changing either")
    parser.add_argument("--backup-only", action="store_true")
    arguments = parser.parse_args()
    if not arguments.backup_only:
        parser.error("--backup-only required")
    outcome = capture()
    # Do not print actual registry command or XML to a console/log.
    print(json.dumps(outcome, indent=2))
    return 0 if outcome["status"] == "BACKUP_VERIFIED_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

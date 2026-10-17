"""Read-only V2 deployment forensic summary for V3 pilot.

No GIS calls, Git operations, process changes, task changes or writes.
Only safe, explicitly enumerated fields are returned from office JSON.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

TAG = re.compile(r"^reportapp-(?:safe|watcher)-v[0-9]{8}-[0-9]{3,9}$")
REASON = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


def _read(path):
    try:
        item = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return item if isinstance(item, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def inspect_office(v2_root):
    """Return a shareable, minimized summary; never include paths or sensitive GIS data."""
    root = Path(v2_root)
    health = _read(root / "health_latest.json")
    cycle = _read(root / "cycle_latest.json")
    installed = _read(root / "last_deployment.json")
    status = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "status_source": "READ_ONLY_OFFICE_FILES",
        "snapshot_present": {
            "health": health is not None,
            "cycle": cycle is not None,
            "last_deployment": installed is not None,
        },
        "watcher": {
            "state_at_snapshot": health.get("status") if health else "UNKNOWN",
            "snapshot_utc": health.get("checked_utc") if health else None,
            "task_state": health.get("watcher_task_state") if health else None,
            "task_last_result": health.get("task_last_result") if health else None,
            "scan_age_minutes_at_snapshot": health.get("scan_age_minutes") if health else None,
            "delivery_failures_at_snapshot": health.get("delivery_failures_last_scan") if health else None,
        },
        "legacy_maintenance": {
            "deployment": cycle.get("deployment") if cycle else "UNKNOWN",
            "installed_tag": installed.get("tag") if installed else None,
            "installed_status": installed.get("status") if installed else None,
            "installed_at_utc": installed.get("installed_utc") if installed else None,
            "installed_component_files": [
                Path(item).name
                for item in (installed.get("updated_files", []) if installed else [])
                if isinstance(item, str) and item.endswith(".py")
            ][:25],
            "backup_folder_present": None,
        },
        "blocked_releases": [],
        "diagnostic_codes": [],
        "office_bridge_version": "UNVERIFIED",
        "production_change_performed": False,
    }

    if installed:
        backup = installed.get("backup_folder")
        if isinstance(backup, str) and backup:
            status["legacy_maintenance"]["backup_folder_present"] = Path(backup).is_dir()

    blocked_dir = root / "blocked_releases"
    if blocked_dir.is_dir():
        for marker in sorted(blocked_dir.iterdir(), key=lambda p: p.name)[:40]:
            if not TAG.fullmatch(marker.name) or not marker.is_file() or marker.is_symlink():
                continue
            note = _read(marker)
            reason = note.get("reason") if note else None
            reason = reason if isinstance(reason, str) and REASON.fullmatch(reason) else "UNAVAILABLE"
            status["blocked_releases"].append({
                "tag": marker.name,
                "reason_code": reason,
                "has_actionable_detail": bool(note and any(
                    isinstance(note.get(key), str) and note[key].strip()
                    for key in ("stage", "failure_test", "details", "traceback_sanitized")
                )),
            })

    codes = status["diagnostic_codes"]
    if not health:
        codes.append("HEALTH_SNAPSHOT_MISSING")
    if not cycle:
        codes.append("CYCLE_SNAPSHOT_MISSING")
    if not installed:
        codes.append("INSTALL_RECEIPT_MISSING")
    if status["legacy_maintenance"]["deployment"] == "BLOCKED_AFTER_FAILURE":
        codes.append("LEGACY_DEPLOYMENT_BLOCKED")
        if not status["blocked_releases"]:
            codes.append("BLOCK_MARKER_MISSING_FROM_DIAGNOSTIC")
        elif not any(marker["has_actionable_detail"] for marker in status["blocked_releases"]):
            codes.append("BLOCKED_RELEASE_HAS_NO_FAILURE_DETAILS")
    if status["legacy_maintenance"]["backup_folder_present"] is False:
        codes.append("LAST_INSTALL_BACKUP_NOT_FOUND")
    if health and health.get("status") != "HEALTHY":
        codes.append("WATCHER_REQUIRES_REVIEW")
    codes.append("ARCGIS_BRIDGE_OFFICE_VERSION_UNVERIFIED")
    return status


def readable_summary(item):
    return (
        f"V2 watcher snapshot: {item['watcher']['state_at_snapshot']}\n"
        f"Last successful V2 release: {item['legacy_maintenance']['installed_tag']}\n"
        f"Last component files: {', '.join(item['legacy_maintenance']['installed_component_files']) or 'none'}\n"
        f"Latest maintenance cycle: {item['legacy_maintenance']['deployment']}\n"
        f"Blocked release markers: {len(item['blocked_releases'])}\n"
        + "\n".join(
            "  " + marker["tag"] + ": " + marker["reason_code"]
            + (" (detail available)" if marker["has_actionable_detail"]
               else " (root cause not recorded)")
            for marker in item["blocked_releases"]
        )
        + "\nDiagnostic codes: " + ", ".join(item["diagnostic_codes"])
    )

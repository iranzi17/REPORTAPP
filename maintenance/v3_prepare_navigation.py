"""Guarded manual switch of only REPORTAPP's Windows URL handler to the
previously staged, office-tested 83-file V3 snapshot.

Intentionally DOES NOT change watcher Scheduled Tasks, Bridge add-in, any
REG records, SQLite, monitor configuration, or V3 active pointer.
Requires the saved prior registry command and a PAUSED navigation queue.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from maintenance.v3_core import Manager, read_json

TAG = "reportapp-v3-v20261017-000032"
ARCHIVE_SHA = "1dac15a37682c79f11508aaea80c344a50dfdb08d7dfede7a19b2ed7575cd948"
ORIGINAL_BACKUP_ID = "20261017T143905Z-716105f6"
ORIGINAL_PROTOCOL_SHA = "be00e87806ab9afcaf290a14d7f4d3f218733742a6c13de24a2c5cd10b4681b5"
REG_KEY = r"Software\Classes\reportapp\shell\open\command"
APPROVE = "SWITCH URI HANDLER TO STAGED V3"


class NavigationSwitchError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _is_windows():
    return os.name == "nt"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def local_paths(localappdata):
    root = Path(localappdata) / "REPORTAPP"
    return root, root / "Maintenance" / "v3"


def _check_saved_original(v3):
    folder = v3 / "cutover_backups" / ORIGINAL_BACKUP_ID
    protocol_path = folder / "protocol_before.json"
    manifest_path = folder / "manifest.json"
    if any(f.is_symlink() for f in (protocol_path, manifest_path)):
        raise NavigationSwitchError("ORIGINAL_BACKUP_SYMLINK")
    try:
        content = protocol_path.read_bytes()
        backup_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        original = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise NavigationSwitchError("ORIGINAL_REGISTRY_BACKUP_UNAVAILABLE") from exc
    if (digest(content) != ORIGINAL_PROTOCOL_SHA
            or backup_manifest.get("protocol_sha256") != ORIGINAL_PROTOCOL_SHA):
        raise NavigationSwitchError("ORIGINAL_REGISTRY_BACKUP_CHECKSUM_MISMATCH")
    record = original.get("open_command")
    if not isinstance(record, dict) or record.get("present") is not True:
        raise NavigationSwitchError("ORIGINAL_REGISTRY_HANDLER_MISSING")
    command = record.get("value")
    if (not isinstance(command, str) or "alert_navigation.py" not in command
            or '--uri "%1"' not in command):
        raise NavigationSwitchError("ORIGINAL_REGISTRY_HANDLER_NOT_REPORTAPP")
    return command, int(record.get("value_type"))


def verified_handler(localappdata, python):
    root, v3 = local_paths(localappdata)
    policy = read_json(root / "Maintenance" / "policy.json", {})
    if not isinstance(policy, dict) or policy.get("auto_deploy") is not False:
        raise NavigationSwitchError("V2_AUTODEPLOY_NOT_HELD")
    if not (root / "Navigation" / "navigation-paused.flag").is_file():
        raise NavigationSwitchError("MAP_ZOOM_MUST_REMAIN_PAUSED")
    manager = Manager(v3, python=python)
    if manager.active.exists() or manager.journal.exists():
        raise NavigationSwitchError("UNEXPECTED_V3_ACTIVATION")
    receipt = read_json(v3 / "receipts" / (TAG + ".json"), {})
    if (not isinstance(receipt, dict)
            or receipt.get("status") != "STAGED_TESTED"
            or receipt.get("archive_sha256") != ARCHIVE_SHA
            or (receipt.get("component_checks") or {}).get("status") != "COMPATIBLE"
            or sum(receipt.get("tests", {}).values()) != 71):
        raise NavigationSwitchError("PINNED_STAGE_RECEIPT_NOT_VERIFIED")
    try:
        version = manager._verify_version(TAG)
    except Exception as exc:
        raise NavigationSwitchError("PINNED_SNAPSHOT_CORRUPT") from exc
    handler = version / "outputs" / "Customer_Meter_Photo_QA_Working" / "src" / "meter_photo_qa" / "alert_navigation.py"
    if not handler.is_file():
        raise NavigationSwitchError("PINNED_HANDLER_MISSING")
    python = Path(python)
    if python.name.lower() not in ("python.exe", "pythonw.exe"):
        raise NavigationSwitchError("PYTHON_EXECUTABLE_INVALID")
    pythonw = python.with_name("pythonw.exe")
    if not pythonw.is_file():
        raise NavigationSwitchError("PYTHONW_NOT_AVAILABLE")
    command = f'"{pythonw}" "{handler}" --uri "%1"'
    return command


def _registry_read():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ) as key:
            value, value_type = winreg.QueryValueEx(key, "")
    except (FileNotFoundError, OSError) as exc:
        raise NavigationSwitchError("URI_HANDLER_REGISTRY_MISSING") from exc
    return value, value_type


def _registry_write(command, kind):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "", 0, kind, command)


def switch(*, localappdata, python, read=_registry_read, write=_registry_write,
           confirmation=None):
    if confirmation != APPROVE:
        raise NavigationSwitchError("EXPLICIT_APPROVAL_REQUIRED")
    if not _is_windows():
        raise NavigationSwitchError("WINDOWS_REQUIRED")
    _, v3 = local_paths(localappdata)
    previous, kind = _check_saved_original(v3)
    requested = verified_handler(localappdata, python)
    current, current_kind = read()
    if (current, current_kind) == (requested, kind):
        return {"status": "ALREADY_ON_STAGED_HANDLER", "watcher_task_unchanged": True}
    if (current, current_kind) != (previous, kind):
        raise NavigationSwitchError("CURRENT_URI_HANDLER_DIFFERS_FROM_BACKUP")
    # Private immutable copy for per-operation rollback, BEFORE registry write.
    audit_dir = v3 / "navigation_backups"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_dir / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                         + "-" + uuid.uuid4().hex[:8] + ".json")
    with audit.open("x", encoding="utf-8") as fp:
        json.dump({"tag": TAG, "previous_command": previous, "kind": kind,
                   "previous_sha256": digest(previous.encode("utf-8")),
                   "next_sha256": digest(requested.encode("utf-8")),
                   "rollback_rehearsed": False}, fp)
    try:
        write(requested, kind)
        if read() != (requested, kind):
            raise NavigationSwitchError("NEW_URI_HANDLER_NOT_VERIFIED")
    except Exception:
        try:
            write(previous, kind)
        except Exception as exc:
            raise NavigationSwitchError("URI_HANDLER_RESTORE_FAILED") from exc
        raise
    return {
        "status": "STAGED_URI_HANDLER_REGISTERED_ZOOM_PAUSED",
        "tag": TAG, "backup_id": audit.stem,
        "old_command_digest": digest(previous.encode("utf-8")),
        "new_command_digest": digest(requested.encode("utf-8")),
        "watcher_task_unchanged": True,
        "map_zoom_paused": True, "bridge_unchanged": True,
        "v3_activated": False,
    }


def status(*, localappdata, python, read=_registry_read):
    _, v3 = local_paths(localappdata)
    original, kind = _check_saved_original(v3)
    expected = verified_handler(localappdata, python)
    current = read()
    return {
        "status": ("STAGED_HANDLER_REGISTERED" if current == (expected, kind)
                   else "ORIGINAL_HANDLER_REGISTERED" if current == (original, kind)
                   else "UNEXPECTED_HANDLER"),
        "map_zoom_paused": True,
        "v3_activated": False,
        "watcher_task_unchanged": True,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--switch", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ["LOCALAPPDATA"])
    python = sys.executable
    result = None
    try:
        if args.switch:
            if not sys.stdin.isatty():
                raise NavigationSwitchError("INTERACTIVE_TERMINAL_REQUIRED")
            print("Only HKCU reportapp:// URI handler will switch to VERIFIED V3.")
            print("Zoom must stay PAUSED; current scheduled watcher is unchanged.")
            answer = input("Type exactly " + APPROVE + " to approve:\n> ")
            result = switch(localappdata=root, python=python,
                            confirmation=answer)
        else:
            result = status(localappdata=root, python=python)
        outcome = 0 if result["status"] != "UNEXPECTED_HANDLER" else 2
    except Exception as exc:
        result = {"status": "FAILED_SAFE", "error_code":
                  getattr(exc, "code", type(exc).__name__), "watcher_task_unchanged": True}
        outcome = 2
    report_dir = root / "REPORTAPP" / "Diagnostics"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / ("office_v3_navigation_" +
                           time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) +
                           "_" + uuid.uuid4().hex[:8] + ".json")
    with report.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, indent=2, sort_keys=True)
    print(json.dumps(result, indent=2))
    print("Share only diagnostic:", report)
    return outcome


if __name__ == "__main__":
    raise SystemExit(main())

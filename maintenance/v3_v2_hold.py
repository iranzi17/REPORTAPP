"""Operator-controlled hold on *V2 auto-deploy only*, NOT the surveyor watcher.

Default command is read-only. Applying the hold is a separate interactive,
explicitly confirmed action once the user authorizes it. The independently
scheduled REPORTAPP Self Maintenance task is briefly disabled ONLY to
prevent an in-flight policy race, then re-enabled for health reporting.
Never calls Stop/Disable on REPORTAPP Surveyor Quality Alerts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

MAINTENANCE_TASK = "REPORTAPP Self Maintenance"
WATCHER_TASK = "REPORTAPP Surveyor Quality Alerts"
APPROVAL = "HOLD V2 AUTO DEPLOY ONLY"
MAX_BYTES = 100_000


class HoldError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _save_new(path, data):
    with Path(path).open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _read_policy(root):
    path = Path(root) / "policy.json"
    if not path.is_file() or path.is_symlink():
        raise HoldError("V2_POLICY_MISSING")
    raw = path.read_bytes()
    if not (0 < len(raw) < MAX_BYTES):
        raise HoldError("V2_POLICY_SIZE")
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise HoldError("V2_POLICY_INVALID") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("auto_deploy"), bool):
        raise HoldError("V2_POLICY_INVALID")
    return raw, parsed


class WindowsTask:
    """Minimal exact-name adapter; never invoke the watcher task itself."""

    def _command(self, script):
        if os.name != "nt":
            raise HoldError("WINDOWS_REQUIRED")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-Command", "$ErrorActionPreference='Stop';" + script],
                capture_output=True, text=True, encoding="utf-8", timeout=35,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HoldError("TASK_CONTROL_UNAVAILABLE") from exc
        if result.returncode:
            raise HoldError("TASK_CONTROL_FAILED")
        return result.stdout

    def state(self):
        result = self._command(
            "$t=Get-ScheduledTask -TaskName 'REPORTAPP Self Maintenance' "
            "-ErrorAction Stop;[string]$t.State"
        ).strip()
        if result not in ("Ready", "Running", "Disabled"):
            raise HoldError("V2_TASK_UNKNOWN_STATE")
        return result

    def export(self):
        result = self._command(
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
            "Export-ScheduledTask -TaskName 'REPORTAPP Self Maintenance'"
        )
        if not result.strip() or len(result.encode("utf-8")) > MAX_BYTES:
            raise HoldError("V2_TASK_XML_INVALID")
        return result.encode("utf-8")

    def disable(self):
        self._command("Disable-ScheduledTask -TaskName 'REPORTAPP Self Maintenance' | Out-Null")

    def enable(self):
        self._command("Enable-ScheduledTask -TaskName 'REPORTAPP Self Maintenance' | Out-Null")


def inspect(maintenance_root, *, task=None):
    root = Path(maintenance_root)
    raw, policy = _read_policy(root)
    task = task or WindowsTask()
    state = task.state()
    return {
        "status": "READ_ONLY",
        "v2_auto_deploy_enabled": policy["auto_deploy"],
        "v2_maintenance_task_state": state,
        "v2_github_issue_reporting": policy.get("github_issue_reporting"),
        "watcher_task_touched": False,
        "task_changed": False,
        "policy_changed": False,
        "hold_is_ready": state == "Ready" and policy["auto_deploy"] is True,
    }


def hold(maintenance_root, *, task=None, operator_confirmation=None):
    """Change only V2 policy auto_deploy, while safeguarding task execution."""
    if operator_confirmation != APPROVAL:
        raise HoldError("EXPLICIT_OPERATOR_APPROVAL_REQUIRED")
    root = Path(maintenance_root)
    task = task or WindowsTask()
    original, policy = _read_policy(root)
    if policy["auto_deploy"] is False:
        return {"status": "ALREADY_HEALTH_ONLY", "watcher_task_touched": False}
    if task.state() != "Ready":
        raise HoldError("V2_MAINTENANCE_TASK_MUST_BE_READY")
    original_task_xml = task.export()
    if not original_task_xml.startswith(b"<?xml") and b"<Task " not in original_task_xml[:300]:
        raise HoldError("V2_TASK_BACKUP_INVALID")
    # Immutable, private rollback evidence BEFORE any task or policy changes.
    dest = root / "v3" / "v2_hold_backups" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    dest.mkdir(parents=True, exist_ok=False)
    _save_new(dest / "v2_policy_before.json", original)
    _save_new(dest / "v2_maintenance_task_before.xml", original_task_xml)
    meta = {
        "policy_sha256": _sha(original),
        "task_xml_sha256": _sha(original_task_xml),
        "was_enabled": True,
        "operation": "V2_AUTODEPLOY_HEALTH_ONLY_HOLD",
        "production_watcher_task_unchanged": True,
        "rollback_rehearsed": False,
    }
    _save_new(dest / "hold_manifest.json", json.dumps(meta, sort_keys=True, indent=2).encode())
    if (_sha((dest / "v2_policy_before.json").read_bytes()) != meta["policy_sha256"]
            or _sha((dest / "v2_maintenance_task_before.xml").read_bytes()) != meta["task_xml_sha256"]):
        raise HoldError("V2_HOLD_BACKUP_UNVERIFIED")
    policy_path = root / "policy.json"
    disabled = False
    policy_replaced = False
    try:
        # V2 maintenance task only. Existing one-minute watcher untouched.
        task.disable()
        disabled = True
        if task.state() != "Disabled":
            raise HoldError("V2_MAINTENANCE_TASK_DID_NOT_DISABLE")
        if policy_path.read_bytes() != original:
            raise HoldError("V2_POLICY_CHANGED_DURING_HOLD")
        updated = dict(policy)
        updated["auto_deploy"] = False
        new_data = (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        temporary = root / ("." + policy_path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            _save_new(temporary, new_data)
            os.replace(temporary, policy_path)
            policy_replaced = True
        finally:
            temporary.unlink(missing_ok=True)
        if _read_policy(root)[1]["auto_deploy"] is not False:
            raise HoldError("V2_AUTODEPLOY_DISABLE_NOT_VERIFIED")
        task.enable()
        disabled = False
        after = task.state()
        if after not in ("Ready", "Running"):
            raise HoldError("V2_MAINTENANCE_HEALTH_TASK_NOT_ENABLED")
    except Exception:
        # Fail closed: if the policy was updated to False, keep it False.
        # Attempt to restore the maintenance health task, but NEVER silently
        # re-enable automatic deployment on rollback.
        if disabled:
            try:
                task.enable()
            except Exception:
                pass
        raise
    return {
        "status": "V2_AUTO_DEPLOY_DISABLED_HEALTH_TASK_PRESERVED",
        "auto_deploy": False,
        "maintenance_task_state": after,
        "private_backup_id": dest.name,
        "policy_sha256_before": meta["policy_sha256"],
        "policy_sha256_after": _sha(policy_path.read_bytes()),
        "watcher_task_touched": False,
        "v3_watcher_activated": False,
        "bridge_changed": False,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Inspect V2 updater without edits")
    parser.add_argument("--hold", action="store_true", help="Explicitly disable only V2 auto-deploy")
    args = parser.parse_args()
    if args.hold and args.status:
        parser.error("Use one operation at a time")
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "REPORTAPP" / "Maintenance"
    if not args.hold:
        print(json.dumps(inspect(root), indent=2))
        return 0
    if not sys.stdin.isatty():
        raise HoldError("INTERACTIVE_CONFIRMATION_REQUIRED")
    print("This will briefly disable and restore only REPORTAPP Self Maintenance,")
    print("and set V2 auto_deploy=false while preserving its health checks.")
    print("It will NOT touch REPORTAPP Surveyor Quality Alerts.")
    phrase = input("To approve, type exactly: " + APPROVAL + "\n> ")
    result = hold(root, operator_confirmation=phrase)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Manual, reversible REPORTAPP watcher cutover on the office PC.

Never run automatically or from GitHub Actions. Applies only to existing
'REPORTAPP Surveyor Quality Alerts' Scheduled Task after PINNED V3 staging,
verified REPORTAPP Bridge 1.0.4, verified URI handler, V2 updater hold, and
user-approved Map Zoom pause. Reverts the Scheduled Task action on failure.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from maintenance.v3_core import Manager, WORK_REL, atomic_json, read_json
from maintenance.v3_bridge_audit import scan_installed_bridge, BridgeAuditError
from maintenance.v3_prepare_navigation import status as uri_status

TAG = "reportapp-v3-v20261017-000032"
ARCHIVE_SHA = "1dac15a37682c79f11508aaea80c344a50dfdb08d7dfede7a19b2ed7575cd948"
BACKUP_ID = "20261017T143905Z-716105f6"
ORIGINAL_TASK_SHA = "0ca421512f726929c4dd1363ea8da0a19f2bc2bf06c587af7b12491125ee5632"
TASK_NAME = "REPORTAPP Surveyor Quality Alerts"
CONSENT = "ACTIVATE REPORTAPP V3 WATCHER"
TESTS = {"test_alert_navigation.py": 15, "test_notification_inbox.py": 9,
         "test_surveyor_notifications.py": 22, "test_surveyor_activity.py": 10,
         "test_deferred_notifications.py": 11, "test_combined_qa_report.py": 4}


class CutoverError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def sha(data):
    return hashlib.sha256(data).hexdigest()


def xml_element(root, tag):
    return next((x for x in root.iter() if x.tag.rsplit("}", 1)[-1] == tag), None)


def read_task_action(xml):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CutoverError("TASK_XML_INVALID") from exc
    actions = xml_element(root, "Actions")
    execs = [x for x in actions if x.tag.rsplit("}", 1)[-1] == "Exec"] if actions is not None else []
    if len(execs) != 1:
        raise CutoverError("TASK_ACTION_COUNT_UNEXPECTED")
    x = execs[0]
    def value(name):
        return next(((v.text or "").strip() for v in x
                     if v.tag.rsplit("}", 1)[-1] == name), "")
    command, arguments, workdir = value("Command"), value("Arguments"), value("WorkingDirectory")
    if not command or not arguments or not workdir:
        raise CutoverError("TASK_ACTION_INCOMPLETE")
    interval = any((x.text or "").strip() == "PT1M" for x in root.iter()
                   if x.tag.rsplit("}", 1)[-1] == "Interval")
    overlap = any((x.text or "").strip() == "IgnoreNew" for x in root.iter()
                  if x.tag.rsplit("}", 1)[-1] == "MultipleInstancesPolicy")
    return {"exe": command.strip('"'), "args": arguments, "cwd": workdir,
            "interval_1min": interval, "ignore_new": overlap}


def original_configuration(backup):
    root = Path(backup)
    xml = root / "task_before.xml"
    manifest = root / "manifest.json"
    if xml.is_symlink() or manifest.is_symlink():
        raise CutoverError("ORIGINAL_TASK_BACKUP_LINKED")
    try:
        raw = xml.read_bytes()
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise CutoverError("ORIGINAL_TASK_BACKUP_MISSING") from exc
    if (sha(raw) != ORIGINAL_TASK_SHA or data.get("task_sha256") != ORIGINAL_TASK_SHA):
        raise CutoverError("ORIGINAL_TASK_BACKUP_MISMATCH")
    action = read_task_action(raw)
    if (Path(action["exe"]).name.casefold() != "pythonw.exe"
            or "-m meter_photo_qa.surveyor_notifications" not in action["args"]
            or "--config" not in action["args"]
            or not action["interval_1min"] or not action["ignore_new"]):
        raise CutoverError("ORIGINAL_TASK_NOT_EXPECTED")
    # Task Scheduler emits --config "C:\...\monitor_config.json"
    match = re.search(r'--config\s+(?:"([^"]+)"|(\S+))', action["args"], flags=re.I)
    if not match:
        raise CutoverError("ORIGINAL_CONFIG_ARG_INVALID")
    config = match.group(1) or match.group(2)
    if Path(config).name.casefold() != "monitor_config.json":
        raise CutoverError("ORIGINAL_CONFIG_UNEXPECTED")
    return action, Path(config), Path(action["cwd"])


def _psquote(value):
    return "'" + str(value).replace("'", "''") + "'"


class WindowsTask:
    def _ps(self, script, *, timeout=35):
        if os.name != "nt":
            raise CutoverError("WINDOWS_REQUIRED")
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                               "$ErrorActionPreference='Stop';" + script],
                              capture_output=True, text=True, timeout=timeout, encoding="utf-8")
        if proc.returncode != 0:
            raise CutoverError("TASK_SCHEDULER_COMMAND_FAILED")
        return proc.stdout

    def state(self):
        value = self._ps("$t=Get-ScheduledTask -TaskName " + _psquote(TASK_NAME) +
                         " -ErrorAction Stop;[string]$t.State").strip()
        if value not in ("Ready", "Running", "Disabled"):
            raise CutoverError("TASK_STATE_UNEXPECTED")
        return value

    def definition(self):
        return self._ps("[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
                        "Export-ScheduledTask -TaskName " + _psquote(TASK_NAME))

    def set_action(self, action):
        script = ("$a=New-ScheduledTaskAction -Execute " + _psquote(action["exe"]) +
                  " -Argument " + _psquote(action["args"]) +
                  " -WorkingDirectory " + _psquote(action["cwd"]) +
                  ";Set-ScheduledTask -TaskName " + _psquote(TASK_NAME) +
                  " -Action $a | Out-Null")
        self._ps(script)


def check_prerequisites(localappdata, python, *, task=None):
    localappdata = Path(localappdata)
    root = localappdata / "REPORTAPP"
    v3 = root / "Maintenance" / "v3"
    manager = Manager(v3, python=python)
    prior_action, config, legacy_src = original_configuration(
        v3 / "cutover_backups" / BACKUP_ID)
    if not config.is_file() or not (legacy_src / "meter_photo_qa" /
                                     "surveyor_notifications.py").is_file():
        raise CutoverError("ORIGINAL_WATCHER_OR_CONFIG_MISSING")
    policy = read_json(root / "Maintenance" / "policy.json", {})
    if not isinstance(policy, dict) or policy.get("auto_deploy") is not False:
        raise CutoverError("V2_AUTO_DEPLOY_NOT_DISABLED")
    if not (root / "Navigation" / "navigation-paused.flag").is_file():
        raise CutoverError("MAP_ZOOM_NOT_PAUSED")
    receipt = read_json(v3 / "receipts" / (TAG + ".json"), {})
    if (receipt.get("status") != "STAGED_TESTED" or
            receipt.get("archive_sha256") != ARCHIVE_SHA or
            (receipt.get("component_checks") or {}).get("status") != "COMPATIBLE" or
            any(receipt.get("tests", {}).get(k, 0) != v for k, v in TESTS.items())):
        raise CutoverError("V3_STAGING_RECEIPT_INVALID")
    if manager.active.exists() or manager.journal.exists():
        raise CutoverError("V3_POINTER_OR_JOURNAL_ALREADY_PRESENT")
    try:
        stage_path = manager._verify_version(TAG)
    except Exception as exc:
        raise CutoverError("V3_STAGE_HASH_MISMATCH") from exc
    try:
        bridge = scan_installed_bridge()
    except (BridgeAuditError, OSError) as exc:
        raise CutoverError("BRIDGE_104_NOT_VERIFIED") from exc
    if bridge.get("status") != "VERIFIED_ON_DISK":
        raise CutoverError("BRIDGE_104_NOT_VERIFIED")
    try:
        navigation = uri_status(localappdata=localappdata, python=python)
    except Exception as exc:
        raise CutoverError("URI_HANDLER_NOT_V3") from exc
    if navigation.get("status") != "STAGED_HANDLER_REGISTERED":
        raise CutoverError("URI_HANDLER_NOT_V3")
    task = task or WindowsTask()
    if task.state() != "Ready":
        raise CutoverError("WATCHER_TASK_MUST_BE_READY")
    current_action = read_task_action(task.definition())
    for name in ("exe", "args", "cwd", "interval_1min", "ignore_new"):
        if current_action[name] != prior_action[name]:
            raise CutoverError("WATCHER_TASK_CHANGED_SINCE_BACKUP")
    return {"root": root, "v3": v3, "config": config, "legacy_src": legacy_src,
            "manager": manager, "original_action": prior_action,
            "current_action": current_action, "task": task,
            "stage_path": stage_path}


def new_task_action(prior, stable_runner, config, legacy_src):
    return {
        "exe": prior["exe"],
        "cwd": prior["cwd"],
        "args": ('"' + str(stable_runner) + '" --config "' + str(config) +
                 '" --legacy-src "' + str(legacy_src) + '"')
    }


def _install_if_new(source, dest):
    source = Path(source)
    dest = Path(dest)
    content = source.read_bytes()
    if dest.exists():
        if dest.is_symlink() or sha(dest.read_bytes()) != sha(content):
            raise CutoverError("STABLE_LAUNCHER_ALREADY_DIFFERENT")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name("." + dest.name + "-" + uuid.uuid4().hex)
    with temp.open("xb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, dest)


def _receipt(report, localappdata):
    d = Path(localappdata) / "REPORTAPP" / "Diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    p = d / ("office_v3_watcher_cutover_" +
             time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) +
             "_" + uuid.uuid4().hex[:8] + ".json")
    with p.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    return p


def activate(*, localappdata, python, kit_root, approval=None, task=None,
             wait_seconds=190, sleeping=time.sleep):
    if approval != CONSENT:
        raise CutoverError("EXPLICIT_USER_APPROVAL_REQUIRED")
    stage = check_prerequisites(localappdata, python, task=task)
    v3, manager, task = stage["v3"], stage["manager"], stage["task"]
    # Scripts remain in stable LOCALAPPDATA, never a disposable Desktop ZIP.
    files = {
        "v3_core.py": "v3_core.py",
        "v3_persistent_watcher.py": "run_v3_once.py",
    }
    for from_name, to_name in files.items():
        _install_if_new(Path(kit_root) / "maintenance" / from_name, v3 / to_name)
    runner = v3 / "run_v3_once.py"
    original = stage["original_action"]
    requested = new_task_action(original, runner, stage["config"], stage["legacy_src"])
    report = {"tool": "REPORTAPP_V3_GUARDED_WATCHER_CUTOVER",
              "release": TAG, "watcher_status": "NOT_SWITCHED",
              "previous_task_backed_up": True, "map_zoom_paused": True,
              "v2_auto_deploy_disabled": True, "registry_unchanged": True,
              "bridge_unchanged": True, "rollback": "NOT_NEEDED"}
    policy_file = manager.policy
    old_policy = policy_file.read_bytes()
    # Preserve ALL exact original inputs privately, including policy and XML.
    private = v3 / "cutover_transactions" / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                                             + "-" + uuid.uuid4().hex[:8])
    private.mkdir(parents=True, exist_ok=False)
    (private / "policy_before.json").write_bytes(old_policy)
    (private / "original_task_before.xml").write_text(task.definition(), encoding="utf-8")
    (private / "transaction.json").write_text(
        json.dumps({"status": "PREPARING", "release": TAG,
                    "task_before_sha256": sha((private / "original_task_before.xml").read_bytes()),
                    "policy_before_sha256": sha(old_policy)}), encoding="utf-8")
    pointer_enabled = False
    task_attempted = False
    changed_policy = False
    try:
        policy = json.loads(old_policy.decode("utf-8"))
        policy.update({"office_cutover_approved": True,
                       "bridge_version_confirmed": "1.0.4",
                       "bridge_restart_confirmed": True,
                       "runtime_python_confirmed": str(python)})
        atomic_json(policy_file, policy)
        changed_policy = True
        manager.activate(TAG)
        pointer_enabled = True
        # Re-read task state just before any modification.
        if task.state() != "Ready":
            raise CutoverError("TASK_BECAME_BUSY")
        task_attempted = True
        task.set_action(requested)
        check = read_task_action(task.definition())
        if (check["exe"], check["args"], check["cwd"]) != (
                requested["exe"], requested["args"], requested["cwd"]):
            raise CutoverError("NEW_TASK_ACTION_NOT_VERIFIED")
        if not check["interval_1min"] or not check["ignore_new"]:
            raise CutoverError("TASK_INTERVAL_OR_OVERLAP_CHANGED")
        switched_at = time.time()
        # Observe the actual scheduled task; DO NOT manually launch a second
        # watcher process or add duplicate notifications.
        deadline = switched_at + max(0, wait_seconds)
        while time.time() < deadline:
            current = read_json(v3 / "launcher_latest.json", {})
            if (current.get("started_epoch_seconds", 0) >= switched_at and
                    current.get("mode") == "V3_VERIFIED" and
                    current.get("status") == "OK" and
                    current.get("exit_code") == 0):
                atomic_json(private / "transaction.json", {
                    "status": "VERIFIED_SWITCHED", "release": TAG,
                    "policy_before_sha256": sha(old_policy),
                    "task_before_sha256": sha((private / "original_task_before.xml").read_bytes()),
                    "verified_epoch_seconds": time.time()})
                report.update({"watcher_status": "V3_FIRST_SCHEDULED_CYCLE_OK",
                               "rollback": "NOT_NEEDED",
                               "config": "ORIGINAL_UNCHANGED",
                               "original_task_trigger_preserved": True})
                return report
            sleeping(4)
        raise CutoverError("FIRST_SCHEDULED_V3_CYCLE_NOT_CONFIRMED")
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        rollback = "RESTORE_PENDING"
        if task_attempted:
            try:
                task.set_action(original)
                action = read_task_action(task.definition())
                if (action["exe"], action["args"], action["cwd"]) != (
                        original["exe"], original["args"], original["cwd"]):
                    raise CutoverError("TASK_RESTORE_VERIFY_FAILED")
                rollback = "TASK_ACTION_RESTORED"
            except Exception:
                rollback = "TASK_RESTORE_FAILED"
        if pointer_enabled:
            try:
                manager.active.unlink(missing_ok=True)
                if manager.active.exists():
                    raise CutoverError("V3_POINTER_REVERT_FAILED")
            except Exception:
                rollback += "_POINTER_RESTORE_FAILED"
        if changed_policy:
            try:
                if policy_file.read_bytes() != old_policy:
                    tmp = policy_file.with_name(policy_file.name + "." + uuid.uuid4().hex + ".tmp")
                    tmp.write_bytes(old_policy)
                    os.replace(tmp, policy_file)
            except Exception:
                rollback += "_POLICY_RESTORE_FAILED"
        report.update({"watcher_status": "CUTOVER_FAILED_SAFE",
                       "error_code": code, "rollback": rollback})
        return report


def restore_legacy(*, localappdata, python, confirmation=None, task=None):
    """Restore original one-minute watcher action after a successful cutover."""
    if confirmation != "RESTORE ORIGINAL REPORTAPP WATCHER":
        raise CutoverError("EXPLICIT_ROLLBACK_APPROVAL_REQUIRED")
    localappdata = Path(localappdata)
    v3 = localappdata / "REPORTAPP" / "Maintenance" / "v3"
    original, config, legacy_src = original_configuration(
        v3 / "cutover_backups" / BACKUP_ID)
    if not (localappdata / "REPORTAPP" / "Navigation" / "navigation-paused.flag").is_file():
        raise CutoverError("MAP_ZOOM_NOT_PAUSED")
    task = task or WindowsTask()
    if task.state() != "Ready":
        raise CutoverError("WATCHER_TASK_MUST_BE_READY")
    current = read_task_action(task.definition())
    expected = new_task_action(original, v3 / "run_v3_once.py", config, legacy_src)
    if (current["exe"], current["args"], current["cwd"]) == (
            original["exe"], original["args"], original["cwd"]):
        return {"watcher_status": "ORIGINAL_WATCHER_ALREADY_ACTIVE",
                "rollback": "NOT_NEEDED"}
    if (current["exe"], current["args"], current["cwd"]) != (
            expected["exe"], expected["args"], expected["cwd"]):
        raise CutoverError("WATCHER_ACTION_NOT_EXPECTED")
    if not current["interval_1min"] or not current["ignore_new"]:
        raise CutoverError("SCHEDULE_DRIFTED")
    manager = Manager(v3, python=python)
    if manager.journal.exists():
        raise CutoverError("V3_TRANSACTION_INCOMPLETE")
    active = read_json(manager.active, {})
    if active.get("tag") != TAG:
        raise CutoverError("CURRENT_ACTIVE_RELEASE_NOT_PINNED")
    txfolder = v3 / "cutover_transactions"
    valid = []
    for folder in txfolder.iterdir() if txfolder.exists() else []:
        policy_file = folder / "policy_before.json"
        txfile = folder / "transaction.json"
        if not policy_file.is_file() or not txfile.is_file():
            continue
        tx = read_json(txfile, {})
        policybytes = policy_file.read_bytes()
        if (tx.get("release") == TAG and
                tx.get("policy_before_sha256") == sha(policybytes)):
            valid.append((folder.name, policybytes))
    if len(valid) != 1:
        # Require exact backup identity instead of guessing between
        # multiple previous cutover attempts.
        raise CutoverError("CUTOVER_POLICY_BACKUP_AMBIGUOUS")
    old_policy = valid[0][1]
    task.set_action(original)
    restored = read_task_action(task.definition())
    if (restored["exe"], restored["args"], restored["cwd"]) != (
            original["exe"], original["args"], original["cwd"]):
        raise CutoverError("ORIGINAL_TASK_RESTORE_NOT_VERIFIED")
    # Exact legacy task action restored before V3 pointer is retired.
    manager.active.unlink(missing_ok=True)
    if manager.active.exists():
        raise CutoverError("V3_POINTER_RETIRE_FAILED")
    tmp = manager.policy.with_name(manager.policy.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_bytes(old_policy)
    os.replace(tmp, manager.policy)
    atomic_json(v3 / "rollback_latest.json", {
        "status": "ORIGINAL_TASK_RESTORED",
        "tag": TAG,
        "at_epoch_seconds": time.time(),
        "map_zoom_paused": True,
        "URI_handler_unchanged": True,
    })
    return {"watcher_status": "ORIGINAL_WATCHER_RESTORED",
            "rollback": "ORIGINAL_TASK_ACTION_AND_V3_POINTER_RESTORED",
            "v2_auto_deploy_disabled": True, "map_zoom_paused": True,
            "bridge_unchanged": True, "registry_unchanged": True}



def main():
    import argparse
    parser = argparse.ArgumentParser()
    operations = parser.add_mutually_exclusive_group(required=True)
    operations.add_argument("--activate", action="store_true")
    operations.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    report = {"watcher_status": "NOT_STARTED"}
    if not sys.stdin.isatty():
        report = {"watcher_status": "FAILED_SAFE",
                  "error_code": "EXPLICIT_INTERACTIVE_APPROVAL_REQUIRED"}
    else:
        phrase = (CONSENT if args.activate
                  else "RESTORE ORIGINAL REPORTAPP WATCHER")
        if args.activate:
            print("Switch only the existing one-minute watcher to V3.")
            print("Map Zoom stays PAUSED; V2 auto-deploy stays OFF.")
            print("Wait for the first successful scheduled V3 cycle.")
        else:
            print("Restore the exact original watcher action from your verified backup.")
            print("Bridge and Windows navigation handler will not change.")
        answer = input("Type exactly " + phrase + "\\n> ")
        try:
            if args.activate:
                report = activate(localappdata=local, python=sys.executable,
                                  kit_root=Path(__file__).resolve().parents[1],
                                  approval=answer)
            else:
                report = restore_legacy(localappdata=local, python=sys.executable,
                                        confirmation=answer)
        except Exception as exc:
            report = {"watcher_status": "FAILED_SAFE",
                      "error_code": getattr(exc, "code", type(exc).__name__)}
    filename = _receipt(report, local)
    print("Watcher cutover status:", report["watcher_status"])
    print("Rollback:", report.get("rollback", "NO_TASK_CHANGE"))
    print("Shareable report:", filename)
    return 0 if report["watcher_status"] in (
        "V3_FIRST_SCHEDULED_CYCLE_OK", "ORIGINAL_WATCHER_RESTORED",
        "ORIGINAL_WATCHER_ALREADY_ACTIVE") else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Reversible one-minute watcher cutover without touching a real Scheduled Task."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maintenance import v3_office_watcher_cutover as cutover
from maintenance.v3_core import atomic_json


def xml_for(action):
    return f'''<?xml version="1.0"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><TimeTrigger><Repetition><Interval>PT1M</Interval></Repetition></TimeTrigger></Triggers>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings>
<Actions><Exec><Command>{action["exe"]}</Command>
<Arguments>{action["args"].replace("&","&amp;")}</Arguments>
<WorkingDirectory>{action["cwd"]}</WorkingDirectory></Exec></Actions>
</Task>'''


class FakeTask:
    def __init__(self, action, on_new=None):
        self.action = dict(action)
        self.operations = []
        self.on_new = on_new
        self.fail_switch = False
        self.state_sequence = []

    def state(self):
        return self.state_sequence.pop(0) if self.state_sequence else "Ready"

    def definition(self):
        return xml_for(self.action)

    def set_action(self, action):
        self.operations.append(dict(action))
        self.action = dict(action)
        if self.on_new:
            self.on_new(action)
        if self.fail_switch and len(self.operations) == 1:
            raise RuntimeError("injected partial action modification")


class FakeManager:
    def __init__(self, root, action_fail=False):
        self.local = Path(root)
        self.local.mkdir(parents=True, exist_ok=True)
        self.policy = self.local / "v3_policy.json"
        atomic_json(self.policy, {
            "repository": "iranzi17/REPORTAPP",
            "enabled": True,
            "approved_tag": cutover.TAG,
            "approved_sha256": cutover.ARCHIVE_SHA,
            "office_cutover_approved": False,
        })
        self.active = self.local / "active.json"
        self.journal = self.local / "transaction.json"
        self.action_fail = action_fail

    def activate(self, tag):
        if tag != cutover.TAG:
            raise ValueError("unexpected tag")
        atomic_json(self.active, {"tag": tag})
        return {"status": "ACTIVATED"}


class CutoverTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.local = Path(tmp.name)
        self.v3 = self.local / "REPORTAPP" / "Maintenance" / "v3"
        self.manager = FakeManager(self.v3)
        self.original = {
            "exe": "C:\\ArcGIS\\pythonw.exe",
            "args": '-m meter_photo_qa.surveyor_notifications --config "C:\\REG\\monitor_config.json"',
            "cwd": "C:\\REPORTAPP\\src",
        }
        self.previous_policy = self.manager.policy.read_bytes()
        self.config = Path("C:/REG/monitor_config.json")
        self.src = Path("C:/REPORTAPP/src")
        self.task = FakeTask(self.original)
        self.kit = self.local / "kit"
        files = self.kit / "maintenance"
        files.mkdir(parents=True)
        (files / "v3_core.py").write_text("VALUE=1\n", encoding="utf-8")
        (files / "v3_persistent_watcher.py").write_text("VALUE=2\n", encoding="utf-8")
        self.stage = {
            "v3": self.v3, "manager": self.manager, "task": self.task,
            "original_action": dict(self.original),
            "config": self.config, "legacy_src": self.src,
        }

    def approved(self, wait_seconds=12, sleeping=lambda _: None, **kwargs):
        with patch.object(cutover, "check_prerequisites", return_value=self.stage):
            return cutover.activate(
                localappdata=self.local, python="C:/ArcGIS/python.exe",
                kit_root=self.kit, approval=cutover.CONSENT,
                wait_seconds=wait_seconds, sleeping=sleeping, **kwargs)

    def test_read_xml_preserves_original_trigger_and_overlap(self):
        entry = cutover.read_task_action(xml_for(self.original))
        self.assertEqual(entry["exe"], self.original["exe"])
        self.assertEqual(entry["args"], self.original["args"])
        self.assertTrue(entry["interval_1min"])
        self.assertTrue(entry["ignore_new"])

    def test_powershell_saved_utf8_bytes_with_utf16_declaration(self):
        # The office backup exports an XML text declaration saying UTF-16,
        # but PowerShell returns a decoded string, saved as UTF-8 bytes.
        payload = ('<?xml version="1.0" encoding="UTF-16"?>\r\n' +
                   xml_for(self.original).split("?>", 1)[1]).encode("utf-8")
        result = cutover.read_task_action(payload)
        self.assertEqual(result["exe"], self.original["exe"])
        self.assertEqual(result["args"], self.original["args"])
        self.assertTrue(result["interval_1min"])
        self.assertTrue(result["ignore_new"])

    def test_native_utf16_bom_task_export(self):
        payload = ('<?xml version="1.0" encoding="UTF-16"?>\n' +
                   xml_for(self.original).split("?>", 1)[1]).encode("utf-16")
        self.assertEqual(cutover.read_task_action(payload)["args"],
                         self.original["args"])

    def test_utf8_bom_task_export(self):
        payload = ('<?xml version="1.0" encoding="UTF-8"?>\n' +
                   xml_for(self.original).split("?>", 1)[1]).encode("utf-8-sig")
        self.assertEqual(cutover.read_task_action(payload)["cwd"],
                         self.original["cwd"])

    def test_export_str_unicode_with_utf16_declaration(self):
        payload = '<?xml version="1.0" encoding="UTF-16"?>\n' + xml_for(
            self.original).split("?>", 1)[1]
        self.assertTrue(cutover.read_task_action(payload)["ignore_new"])

    def test_bad_task_xml_still_fails_closed(self):
        with self.assertRaises(cutover.CutoverError) as caught:
            cutover.read_task_action(b'<?xml version="1.0" encoding="UTF-16"?>\n<Task><Actions>')
        self.assertEqual(caught.exception.code, "TASK_XML_INVALID")

    def test_xml_wrong_root_is_not_accepted(self):
        with self.assertRaises(cutover.CutoverError) as caught:
            cutover.read_task_action('<NotATask><Actions/></NotATask>')
        self.assertEqual(caught.exception.code, "TASK_XML_UNEXPECTED_ROOT")

    def test_unknown_or_corrupt_xml_encoding_is_rejected(self):
        with self.assertRaises(cutover.CutoverError) as caught:
            cutover.read_task_action(b'\xff\x00\xff')
        self.assertEqual(caught.exception.code, "TASK_XML_ENCODING_INVALID")

    def test_refuses_without_explicit_phrase_before_inspection(self):
        with self.assertRaises(cutover.CutoverError) as caught:
            cutover.activate(localappdata=self.local, python="python.exe",
                             kit_root=self.kit, approval="Y")
        self.assertEqual(caught.exception.code, "EXPLICIT_USER_APPROVAL_REQUIRED")
        self.assertEqual(self.task.operations, [])
        self.assertFalse(self.manager.active.exists())

    def test_first_scheduled_cycle_confirmed_without_manual_second_watcher(self):
        def on_switch(action):
            if "run_v3_once.py" in action["args"]:
                atomic_json(self.v3 / "launcher_latest.json", {
                    "started_epoch_seconds": 999999999999,
                    "mode": "V3_VERIFIED", "status": "OK", "exit_code": 0})
        self.task.on_new = on_switch
        result = self.approved()
        self.assertEqual(result["watcher_status"], "V3_FIRST_SCHEDULED_CYCLE_OK")
        self.assertTrue(self.manager.active.exists())
        self.assertEqual(len(self.task.operations), 1)
        self.assertIn("run_v3_once.py", self.task.action["args"])
        self.assertNotEqual(self.manager.policy.read_bytes(), self.previous_policy)
        trans = list((self.v3 / "cutover_transactions").glob("*/transaction.json"))
        self.assertEqual(len(trans), 1)
        self.assertEqual(json.loads(trans[0].read_text())["status"],
                         "VERIFIED_SWITCHED")

    def test_failed_first_cycle_restores_old_task_pointer_and_policy(self):
        # Do not sleep for real; advance time by waiting zero once then force
        # a timeout by mocking time.time to move monotonically.
        calls = [1000, 1000, 1200, 1200, 1400]
        with patch.object(cutover.time, "time",
                          side_effect=lambda: calls.pop(0) if calls else 1500):
            result = self.approved(wait_seconds=50)
        self.assertEqual(result["watcher_status"], "CUTOVER_FAILED_SAFE")
        self.assertEqual(result["rollback"], "ORIGINAL_TASK_RESTORED")
        self.assertEqual(len(self.task.operations), 2)
        self.assertEqual(self.task.action, self.original)
        self.assertFalse(self.manager.active.exists())
        self.assertEqual(self.manager.policy.read_bytes(), self.previous_policy)

    def test_running_watcher_finishes_naturally_before_task_action_switch(self):
        # The office failure TASK_BECAME_BUSY happened between preflight and
        # Set-ScheduledTask. Running -> Running -> Ready is expected in a
        # one-minute monitoring task and must not interrupt the old watcher.
        self.task.state_sequence = ["Running", "Running", "Ready"]
        self.task.on_new = lambda action: atomic_json(
            self.v3 / "launcher_latest.json", {
                "started_epoch_seconds": 999999999999,
                "mode": "V3_VERIFIED", "status": "OK", "exit_code": 0})
        waits = []
        result = self.approved(sleeping=waits.append)
        self.assertEqual(result["watcher_status"], "V3_FIRST_SCHEDULED_CYCLE_OK")
        self.assertEqual(result["busy_window_polls"], 3)
        self.assertEqual(len(waits), 2)
        self.assertEqual(len(self.task.operations), 1)
        self.assertIn("run_v3_once.py", self.task.action["args"])

    def test_running_watcher_timeout_refuses_task_change_and_restores_pointer(self):
        # Controlled fake monotonic clock makes timeout deterministic without
        # sleeping 145 seconds. Original task must remain entirely unchanged.
        self.task.state_sequence = ["Running"] * 8
        ticks = iter([0, 4, 8, 12, 16])
        result = self.approved(
            ready_wait_seconds=10, ready_clock=lambda: next(ticks),
            sleeping=lambda _: None)
        self.assertEqual(result["error_code"], "WATCHER_BUSY_TIMEOUT_NO_TASK_CHANGE")
        self.assertEqual(result["watcher_status"], "CUTOVER_FAILED_SAFE")
        self.assertEqual(result["rollback"], "ORIGINAL_TASK_CONFIRMED_NO_TASK_CHANGE")
        self.assertFalse(result["task_change_attempted"])
        self.assertTrue(result["original_task_action_confirmed"])
        self.assertTrue(result["v3_pointer_inactive"])
        self.assertTrue(result["v3_policy_restored"])
        self.assertEqual(self.task.operations, [])
        self.assertEqual(self.task.action, self.original)
        self.assertFalse(self.manager.active.exists())
        self.assertEqual(self.manager.policy.read_bytes(), self.previous_policy)

    def test_disabled_task_never_triggered_or_reconfigured(self):
        self.task.state_sequence = ["Disabled"]
        result = self.approved()
        self.assertEqual(result["watcher_status"], "CUTOVER_FAILED_SAFE")
        self.assertEqual(result["error_code"], "WATCHER_TASK_DISABLED_OR_UNAVAILABLE")
        self.assertEqual(self.task.operations, [])
        self.assertFalse(self.manager.active.exists())

    def test_busy_wait_function_uses_ready_without_action_change(self):
        self.task.state_sequence = ["Running", "Ready"]
        checks = cutover.wait_for_safe_task_window(
            self.task, max_wait_seconds=20, sleeping=lambda _: None)
        self.assertEqual(checks["status"], "READY")
        self.assertEqual(checks["polls"], 2)
        self.assertEqual(self.task.operations, [])

    def test_partial_set_action_failure_restores_original(self):
        self.task.fail_switch = True
        result = self.approved(wait_seconds=10)
        self.assertEqual(result["watcher_status"], "CUTOVER_FAILED_SAFE")
        self.assertEqual(result["error_code"], "RuntimeError")
        self.assertEqual(self.task.action, self.original)
        self.assertFalse(self.manager.active.exists())

    def test_restore_original_after_success_and_archive_policy(self):
        self.task.on_new = lambda action: (
            atomic_json(self.v3 / "launcher_latest.json", {
                "started_epoch_seconds": 999999999999, "mode": "V3_VERIFIED",
                "status": "OK", "exit_code": 0})
            if "run_v3_once.py" in action["args"] else None)
        self.assertEqual(self.approved()["watcher_status"],
                         "V3_FIRST_SCHEDULED_CYCLE_OK")
        fake_root = self.local / "REPORTAPP"
        paused = fake_root / "Navigation" / "navigation-paused.flag"
        paused.parent.mkdir(parents=True)
        paused.write_text("paused", encoding="utf-8")
        self.task.on_new = None
        with patch.object(cutover, "original_configuration",
                          return_value=(self.original, self.config, self.src)):
            result = cutover.restore_legacy(
                localappdata=self.local, python="python.exe",
                task=self.task,
                confirmation="RESTORE ORIGINAL REPORTAPP WATCHER")
        self.assertEqual(result["watcher_status"], "ORIGINAL_WATCHER_RESTORED")
        self.assertEqual(self.task.action, self.original)
        self.assertEqual(self.manager.policy.read_bytes(), self.previous_policy)
        self.assertFalse(self.manager.active.exists())
        self.assertEqual(
            json.loads((self.v3 / "last_deployment.json").read_text())["status"],
            "ROLLED_BACK_TO_LEGACY")


if __name__ == "__main__":
    unittest.main()

"""No-real-task tests for explicit V2 health-only hold during V3 preparation."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from maintenance import v3_v2_hold as hold


TASK_XML = b'<?xml version="1.0"?><Task version="1.4"><Actions><Exec/></Actions></Task>'


class Task:
    def __init__(self, initial="Ready", fail_on=None):
        self.current = initial
        self.fail_on = fail_on
        self.operations = []

    def state(self):
        self.operations.append("get_state")
        return self.current

    def export(self):
        self.operations.append("read_export")
        return TASK_XML

    def disable(self):
        self.operations.append("disable_v2_maintenance")
        self.current = "Disabled"
        if self.fail_on == "disable":
            raise hold.HoldError("SIMULATED_DISABLE_ERROR")

    def enable(self):
        self.operations.append("enable_v2_maintenance")
        if self.fail_on == "enable":
            raise hold.HoldError("SIMULATED_ENABLE_ERROR")
        self.current = "Ready"


class V2HoldTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "Maintenance"
        self.root.mkdir()
        self.policy_file = self.root / "policy.json"
        self.initial = {"auto_deploy": True, "github_issue_reporting": False,
                        "custom_policy_key": "MUST_SURVIVE"}
        self.policy_file.write_text(json.dumps(self.initial), encoding="utf-8")
        self.task = Task()

    def test_status_never_writes_policy_or_tasks(self):
        before = self.policy_file.read_bytes()
        result = hold.inspect(self.root, task=self.task)
        self.assertTrue(result["v2_auto_deploy_enabled"])
        self.assertTrue(result["hold_is_ready"])
        self.assertEqual(self.task.operations, ["get_state"])
        self.assertEqual(self.policy_file.read_bytes(), before)
        self.assertFalse((self.root / "v3").exists())

    def test_operator_approval_phrase_required(self):
        with self.assertRaises(hold.HoldError) as err:
            hold.hold(self.root, task=self.task,
                      operator_confirmation="I approve")
        self.assertEqual(err.exception.code, "EXPLICIT_OPERATOR_APPROVAL_REQUIRED")
        self.assertEqual(self.task.operations, [])
        self.assertTrue(json.loads(self.policy_file.read_text())["auto_deploy"])

    def test_health_only_hold_preserves_other_flags_and_original_evidence(self):
        out = hold.hold(self.root, task=self.task,
                        operator_confirmation=hold.APPROVAL)
        self.assertEqual(out["status"], "V2_AUTO_DEPLOY_DISABLED_HEALTH_TASK_PRESERVED")
        saved = json.loads(self.policy_file.read_text())
        self.assertIs(saved["auto_deploy"], False)
        self.assertEqual(saved["github_issue_reporting"], False)
        self.assertEqual(saved["custom_policy_key"], "MUST_SURVIVE")
        self.assertEqual(self.task.current, "Ready")
        self.assertEqual(self.task.operations,
                         ["get_state", "read_export", "disable_v2_maintenance",
                          "get_state", "enable_v2_maintenance", "get_state"])
        self.assertTrue(out["watcher_task_touched"] is False)
        back = self.root / "v3" / "v2_hold_backups" / out["private_backup_id"]
        self.assertEqual(json.loads((back / "v2_policy_before.json").read_text()),
                         self.initial)
        self.assertEqual((back / "v2_maintenance_task_before.xml").read_bytes(),
                         TASK_XML)

    def test_cannot_proceed_if_maintenance_task_running(self):
        self.task.current = "Running"
        with self.assertRaises(hold.HoldError) as err:
            hold.hold(self.root, task=self.task,
                      operator_confirmation=hold.APPROVAL)
        self.assertEqual(err.exception.code, "V2_MAINTENANCE_TASK_MUST_BE_READY")
        self.assertTrue(json.loads(self.policy_file.read_text())["auto_deploy"])
        self.assertFalse((self.root / "v3").exists())

    def test_policy_invalid_fails_without_any_task_changes(self):
        self.policy_file.write_text("{wrong", encoding="utf-8")
        with self.assertRaises(hold.HoldError) as err:
            hold.hold(self.root, task=self.task,
                      operator_confirmation=hold.APPROVAL)
        self.assertEqual(err.exception.code, "V2_POLICY_INVALID")
        self.assertEqual(self.task.operations, [])

    def test_disable_failure_restores_maintenance_task_without_rewriting_policy(self):
        self.task.fail_on = "disable"
        with self.assertRaises(hold.HoldError):
            hold.hold(self.root, task=self.task,
                      operator_confirmation=hold.APPROVAL)
        # Implementations must restore a task that became disabled even when
        # the underlying controller reports failure after making that change.
        self.assertEqual(self.task.current, "Ready")
        self.assertTrue(json.loads(self.policy_file.read_text())["auto_deploy"])

    def test_failure_after_policy_change_remains_safe_without_auto_deploy(self):
        self.task.fail_on = "enable"
        with self.assertRaises(hold.HoldError):
            hold.hold(self.root, task=self.task,
                      operator_confirmation=hold.APPROVAL)
        self.assertIs(json.loads(self.policy_file.read_text())["auto_deploy"], False)
        self.assertEqual(self.task.current, "Disabled")

    def test_idempotent_on_existing_health_only_policy(self):
        self.initial["auto_deploy"] = False
        self.policy_file.write_text(json.dumps(self.initial), encoding="utf-8")
        out = hold.hold(self.root, task=self.task,
                        operator_confirmation=hold.APPROVAL)
        self.assertEqual(out["status"], "ALREADY_HEALTH_ONLY")
        self.assertEqual(self.task.operations, [])
        self.assertFalse((self.root / "v3").exists())


if __name__ == "__main__":
    unittest.main()

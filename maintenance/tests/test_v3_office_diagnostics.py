"""Read-only office receipt audit; no secrets, source edits or task operations."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from maintenance.v3_office_diagnostics import inspect_office, readable_summary


class OfficeDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name) / "Maintenance"
        self.root.mkdir()

    def write(self, name, item):
        dest = self.root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(item), encoding="utf-8")

    def office_sample(self):
        self.write("health_latest.json", {
            "checked_utc": "2026-10-17T13:01:53+00:00",
            "status": "HEALTHY", "watcher_task_state": "Ready",
            "task_last_result": 0, "scan_age_minutes": 0.5,
            "delivery_failures_last_scan": 0,
            "scanned_counts": {"pole": 2191, "line": 240, "transformer": 52},
            "usernames": ["THIS_MUST_NOT_BE_EXPORTED"],
            "feature_service_password": "THIS_MUST_NOT_BE_EXPORTED",
        })
        self.write("cycle_latest.json", {
            "deployment": "BLOCKED_AFTER_FAILURE",
            "debug": "THIS_MUST_NOT_BE_EXPORTED",
        })
        self.write("last_deployment.json", {
            "tag": "reportapp-safe-v20261016-002",
            "status": "DEPLOYED_TESTED",
            "installed_utc": "2026-10-16T12:11:59+00:00",
            "updated_files": [
                "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/notification_inbox.py",
            ],
            "backup_folder": str(self.root / "backups" / "reportapp-safe-v20261016-002"),
            "private_details": "THIS_MUST_NOT_BE_EXPORTED",
        })

    def test_healthy_watcher_and_blocked_deploy_are_independent(self):
        self.office_sample()
        result = inspect_office(self.root)
        self.assertEqual(result["watcher"]["state_at_snapshot"], "HEALTHY")
        self.assertEqual(result["legacy_maintenance"]["deployment"], "BLOCKED_AFTER_FAILURE")
        self.assertEqual(result["legacy_maintenance"]["installed_component_files"],
                         ["notification_inbox.py"])
        self.assertIn("BLOCK_MARKER_MISSING_FROM_DIAGNOSTIC", result["diagnostic_codes"])
        self.assertFalse(result["production_change_performed"])
        self.assertEqual(result["office_bridge_version"], "UNVERIFIED")

    def test_generic_block_record_cannot_claim_actual_root_cause(self):
        self.office_sample()
        self.write("blocked_releases/reportapp-watcher-v20261016-000006", {
            "tag": "reportapp-watcher-v20261016-000006",
            "reason": "RuntimeError",
        })
        item = inspect_office(self.root)
        self.assertEqual(item["blocked_releases"][0]["reason_code"], "RuntimeError")
        self.assertFalse(item["blocked_releases"][0]["has_actionable_detail"])
        self.assertIn("BLOCKED_RELEASE_HAS_NO_FAILURE_DETAILS", item["diagnostic_codes"])
        self.assertIn("root cause not recorded", readable_summary(item))

    def test_structured_failure_is_reported_without_leaking_raw_details(self):
        self.office_sample()
        self.write("blocked_releases/reportapp-watcher-v20261016-000006", {
            "tag": "reportapp-watcher-v20261016-000006",
            "reason": "RuntimeError",
            "stage": "STAGING_TESTS",
            "details": "SECRET private GIS connection token",
        })
        item = inspect_office(self.root)
        self.assertTrue(item["blocked_releases"][0]["has_actionable_detail"])
        text = json.dumps(item)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("token", text)
        self.assertNotIn("THIS_MUST_NOT_BE_EXPORTED", text)

    def test_corrupt_json_or_untrusted_file_names_do_not_abort_inspection(self):
        self.root.joinpath("health_latest.json").write_bytes(b"{\xff\x00")
        self.write("blocked_releases/not-a-release", {"reason": "RuntimeError"})
        self.write("cycle_latest.json", {"deployment": "UNKNOWN"})
        item = inspect_office(self.root)
        self.assertIn("HEALTH_SNAPSHOT_MISSING", item["diagnostic_codes"])
        self.assertEqual(item["blocked_releases"], [])

    def test_receipt_backup_exists_check_is_read_only(self):
        self.office_sample()
        backup = self.root / "backups" / "reportapp-safe-v20261016-002"
        backup.mkdir(parents=True)
        item = inspect_office(self.root)
        self.assertIs(item["legacy_maintenance"]["backup_folder_present"], True)
        self.assertNotIn("LAST_INSTALL_BACKUP_NOT_FOUND", item["diagnostic_codes"])


if __name__ == "__main__":
    unittest.main()

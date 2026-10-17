"""Safety checks for pinned REPORTAPP V3 office staging."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maintenance import v3_office_stage as stage


class PinnedStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.appdata = Path(self.temp.name)
        self.maintenance = self.appdata / "REPORTAPP" / "Maintenance"
        self.maintenance.mkdir(parents=True)
        self.package = self.appdata / "candidate.zip"
        self.package.write_bytes(b"not a production candidate")

    def policy(self, auto_deploy):
        (self.maintenance / "policy.json").write_text(
            json.dumps({"auto_deploy": auto_deploy}), encoding="utf-8")

    def test_no_stage_when_v2_auto_deploy_enabled(self):
        self.policy(True)
        result = stage.stage(self.package, appdata=self.appdata, runtime_check=False)
        self.assertEqual(result["status"], "FAILED_SAFE")
        self.assertEqual(result["error_code"], "V2_AUTO_DEPLOY_STILL_ENABLED")
        self.assertFalse((self.maintenance / "v3" / "active.json").exists())
        self.assertFalse((self.maintenance / "v3" / "v3_policy.json").exists())

    def test_v2_held_does_not_authorize_unpinned_package(self):
        self.policy(False)
        result = stage.stage(self.package, appdata=self.appdata, runtime_check=False)
        self.assertEqual(result["status"], "FAILED_SAFE")
        self.assertEqual(result["error_code"], "UNAPPROVED_PACKAGE_SHA256")
        self.assertTrue(result["v2_auto_deploy_disabled"])
        self.assertFalse((self.maintenance / "v3" / "active.json").exists())

    def test_missing_policy_fails_closed(self):
        result = stage.stage(self.package, appdata=self.appdata, runtime_check=False)
        self.assertEqual(result["error_code"], "V2_AUTO_DEPLOY_STILL_ENABLED")
        self.assertFalse((self.maintenance / "v3" / "v3_policy.json").exists())

    def test_prior_v3_activation_refuses_stage_without_change(self):
        self.policy(False)
        v3 = self.maintenance / "v3"
        v3.mkdir()
        pointer = v3 / "active.json"
        pointer.write_text('{"tag":"some-version"}', encoding="utf-8")
        result = stage.stage(self.package, appdata=self.appdata, runtime_check=False)
        self.assertEqual(result["error_code"], "V3_ACTIVATION_STATE_EXISTS")
        self.assertEqual(pointer.read_text(), '{"tag":"some-version"}')

    def test_manager_initialization_attribute_error_is_reported_not_lost(self):
        self.policy(False)
        class BrokenManager:
            def __init__(self, *_args, **_kwargs):
                raise AttributeError("simulated manager constructor failure")
        result = stage.stage(self.package, appdata=self.appdata,
                             runtime_check=False, staging_class=BrokenManager)
        self.assertEqual(result["status"], "FAILED_SAFE")
        self.assertEqual(result["phase"], "MANAGER_INITIALIZATION")
        self.assertEqual(result["error_type"], "AttributeError")
        self.assertEqual(result["error_code"], "AttributeError")
        self.assertEqual(result["failure_origin"]["function"], "__init__")
        self.assertFalse((self.maintenance / "v3" / "active.json").exists())

    def test_failed_stage_has_sanitized_phase_and_shareable_receipt(self):
        self.policy(True)
        outcome = stage.stage(self.package, appdata=self.appdata,
                              runtime_check=False)
        self.assertEqual(outcome["phase"], "V2_POLICY_CHECK")
        self.assertEqual(outcome["status"], "FAILED_SAFE")
        path = stage._safe_report(outcome, local=self.appdata)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["error_code"], "V2_AUTO_DEPLOY_STILL_ENABLED")
        self.assertEqual(saved["phase"], "V2_POLICY_CHECK")
        self.assertFalse(saved["v3_activated"])

    def test_read_only_receipt_does_not_include_private_paths(self):
        report = {"status": "FAILED_SAFE", "error_code": "V2_AUTO_DEPLOY_STILL_ENABLED"}
        path = stage._safe_report(report, local=self.appdata)
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text()), report)
        self.assertNotIn("C:\\Users", path.read_text())


if __name__ == "__main__":
    unittest.main()

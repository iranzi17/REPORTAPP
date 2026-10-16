"""Safe updater regression: allowlist, digest, no alerts touched, rollback."""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from maintenance import self_monitor as m
from maintenance.build_safe_release import build

TARGET = next(iter(m.ALLOWED))
TAG = "reportapp-safe-v20261016-001"


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.target = self.root / TARGET
        self.target.parent.mkdir(parents=True)
        self.target.write_text("ORIGINAL = 1\n", encoding="utf-8")
        self.work = self.root / "outputs" / "Customer_Meter_Photo_QA_Working"
        self.local = Path(self.temp.name) / "local"
        self.nav = Path(self.temp.name) / "navigation"
        self.patchers = [
            patch.object(m, "ROOT", self.root),
            patch.object(m, "WORK", self.work),
            patch.object(m, "LOCAL", self.local),
            patch.object(m, "POLICY", self.local / "policy.json"),
            patch.object(m, "REPORT", self.local / "health_latest.json"),
            patch.object(m, "LAST_UPDATE", self.local / "last_deployment.json"),
            patch.object(m, "CONFIG", self.work / "outputs" / "REPORTAPP_Surveyor_Notifications" / "monitor_config.json"),
            patch.object(m, "NAV", self.nav),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def package(self, source=None):
        self.target.write_text(source or "IMPROVED = 2\n", encoding="utf-8")
        archive = self.root / "artifact.zip"
        build(TAG, self.root, archive)
        self.target.write_text("ORIGINAL = 1\n", encoding="utf-8")
        return archive.read_bytes()

    def test_valid_release_package(self):
        payload = m._validate_zip(self.package(), TAG)
        self.assertEqual(list(payload), [TARGET])
        self.assertEqual(payload[TARGET], b"IMPROVED = 2\n")

    def test_different_tag_and_tampered_content_rejected(self):
        data = self.package()
        with self.assertRaisesRegex(ValueError, "metadata mismatch"):
            m._validate_zip(data, "reportapp-safe-v20261016-002")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            original = json.loads(z.read("manifest.json"))
            blob = z.read(TARGET)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("manifest.json", json.dumps(original))
            z.writestr(TARGET, blob + b"# modified")
        with self.assertRaisesRegex(ValueError, "hash"):
            m._validate_zip(archive.getvalue(), TAG)

    def test_forbidden_files_not_accepted(self):
        forbidden = [
            "outputs/Customer_Meter_Photo_QA_Working/outputs/REPORTAPP_Surveyor_Notifications/monitor_config.json",
            "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/surveyor_notifications.py",
            "outputs/Customer_Meter_Photo_QA_Working/addins/ReportappNavigationBridge/BridgeModule.cs",
            "../other.py",
        ]
        for path in forbidden:
            with self.subTest(path=path):
                blob = b'print("not approved")\n'
                manifest = {
                    "format": 1, "repository": m.REPO, "tag": TAG,
                    "files": {path: hashlib.sha256(blob).hexdigest()},
                }
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("manifest.json", json.dumps(manifest))
                    z.writestr(path, blob)
                with self.assertRaises(ValueError):
                    m._validate_zip(archive.getvalue(), TAG)

    def test_successful_install_preserves_unrelated_files(self):
        data = self.package()
        confidential = self.work / "outputs" / "REPORTAPP_Surveyor_Notifications" / "monitor_config.json"
        confidential.parent.mkdir(parents=True)
        confidential.write_text("LOCAL-CONFIG", encoding="utf-8")
        with patch.object(m, "_smoke_test") as smoke:
            receipt = m.apply_update({"tag_name": TAG}, data)
        smoke.assert_called_once()
        self.assertEqual(self.target.read_text(), "IMPROVED = 2\n")
        self.assertEqual(confidential.read_text(), "LOCAL-CONFIG")
        self.assertEqual(receipt["status"], "DEPLOYED_TESTED")
        self.assertTrue((self.local / "backups" / TAG / "notification_inbox.py").is_file())

    def test_failed_smoke_test_rolls_back(self):
        data = self.package()
        with patch.object(m, "_smoke_test", side_effect=RuntimeError("smoke")):
            with self.assertRaisesRegex(RuntimeError, "smoke"):
                m.apply_update({"tag_name": TAG}, data)
        self.assertEqual(self.target.read_text(), "ORIGINAL = 1\n")
        self.assertFalse(m.LAST_UPDATE.exists())

    def test_no_release_download_without_explicit_consent(self):
        with patch.object(m, "_task_health", return_value=("Disabled", 0)):
            with patch.object(m, "_last_scan", return_value=None):
                with patch.object(m, "_load_approved_release", side_effect=AssertionError("should not contact GitHub")):
                    outcome = m.cycle()
        self.assertEqual(outcome["deployment"], "DISABLED")
        self.assertTrue(m.REPORT.exists())

    def test_healthy_and_paused_state(self):
        now = dt.datetime.now(dt.timezone.utc)
        with patch.object(m, "_task_health", return_value=("Disabled", 0)):
            with patch.object(m, "_last_scan", return_value=(now, {"records_scanned": {"pole": 1503, "line": 145, "transformer": 45}, "alerts_sent": 0, "alerts_delivery_failed": 0})):
                info = m.collect_health(now=now)
        self.assertEqual(info["status"], "PAUSED")
        self.assertEqual(info["scanned_counts"]["line"], 145)
        self.assertNotIn("WATCHER_SCAN_STALE", info["issues"])

    def test_missing_log_is_diagnosed(self):
        with patch.object(m, "_task_health", return_value=("Ready", 0)):
            with patch.object(m, "_last_scan", return_value=None):
                info = m.collect_health()
        self.assertEqual(info["status"], "DEGRADED")
        self.assertIn("NO_RECENT_SCAN_LOG", info["issues"])

    def test_failed_release_is_blocked_against_auto_retry(self):
        m.POLICY.parent.mkdir(parents=True)
        m.POLICY.write_text('{"auto_deploy":true}', encoding="utf-8")
        release = {"tag_name": TAG}
        asset = {"name": m.ASSET_NAME}
        with patch.object(m, "_task_health", return_value=("Disabled", 0)):
            with patch.object(m, "_last_scan", return_value=None):
                with patch.object(m, "_load_approved_release", return_value=(release, asset)):
                    with patch.object(m, "apply_update", side_effect=RuntimeError("smoke")):
                        result = m.cycle(download=lambda _: self.package())
                        self.assertEqual(result["deployment"], "FAILED_SAFE")
                        again = m.cycle(download=lambda _: self.fail("unexpected download"))
        self.assertEqual(again["deployment"], "BLOCKED_AFTER_FAILURE")

    def test_release_requires_asset_digest(self):
        bad = {"tag_name": TAG, "draft": False, "prerelease": False,
               "published_at": "2026-10-16T08:00:00Z",
               "assets": [{"name": m.ASSET_NAME, "digest": None}]}
        with self.assertRaisesRegex(ValueError, "SHA256"):
            m._load_approved_release(lambda _: [bad])

if __name__ == "__main__":
    unittest.main()

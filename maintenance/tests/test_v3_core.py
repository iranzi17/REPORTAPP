"""Adversarial tests for V3: archive identity, staging, compatibility and recovery."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from maintenance import v3_core as v3
from maintenance.v3_build import build

TAG1 = "reportapp-v3-v20261017-000001"
TAG2 = "reportapp-v3-v20261017-000002"


class V3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.local = Path(self.temp.name) / "local"
        self.work = self.root / v3.WORK_REL
        self.work.mkdir(parents=True)
        for path in v3.REQUIRED_FILES:
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("OK = True\n", encoding="utf-8")
        bridge_source = self.work / "addins" / "ReportappNavigationBridge" / "BridgeModule.cs"
        bridge_source.parent.mkdir(parents=True, exist_ok=True)
        bridge_source.write_text("// Test-only reference, not an installed add-in.\n", encoding="utf-8")
        tracked_map = self.work / "config" / "report_user_names.json"
        tracked_map.parent.mkdir(parents=True, exist_ok=True)
        tracked_map.write_text('{"accounts":[]}', encoding="utf-8")
        for name in v3.REQUIRED_TESTS:
            file = self.work / "tests" / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(
                "import unittest\n"
                "class Verify(unittest.TestCase):\n"
                "    def test_passes(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
        self.config = self.work / "outputs" / "REPORTAPP_Surveyor_Notifications" / "monitor_config.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"watched":["someone"]}', encoding="utf-8")
        self.manager = v3.Manager(self.local)

    def archive(self, tag=TAG1):
        name = self.root / (tag + ".zip")
        result = build(tag, self.root, name)
        return name.read_bytes(), result["sha256"]

    def approve(self, tag, sha, **extras):
        v3.atomic_json(self.manager.policy, {
            "enabled": True, "repository": v3.REPO,
            "approved_tag": tag, "approved_sha256": sha, **extras
        })

    def test_build_and_staging_do_not_touch_working_checkout_or_monitor(self):
        before = self.config.read_bytes()
        data, sha = self.archive()
        self.approve(TAG1, sha)
        result = self.manager.stage(TAG1, data, sha)
        self.assertEqual(result["status"], "STAGED_TESTED")
        self.assertTrue(all(n >= 1 for n in result["tests"].values()))
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse(self.manager.active.exists())
        self.assertFalse((self.root / "maintenance" / "policy.json").exists())
        self.assertEqual(self.manager.status()["active"], None)

    def test_archive_hash_must_match_operator_approval(self):
        data, sha = self.archive()
        with self.assertRaisesRegex(ValueError, "SHA256"):
            v3.validate_archive(data, "0"*64, TAG1)
        self.approve(TAG1, "0"*64)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.manager.stage(TAG1, data, "0"*64)
        self.assertTrue((self.local / "blocked_releases" / TAG1).exists())

    def test_traversal_and_unmanaged_data_paths_refused(self):
        for path in ("../bad.py", "/tmp/bad.py",
                     v3.WORK_REL + "/outputs/monitor_config.json",
                     v3.WORK_REL + "/tests/../../invalid.py",
                     v3.WORK_REL + "/src/meter_photo_qa/../../secret.py"):
            with self.subTest(path=path):
                self.assertFalse(v3.safe_path(path))

    def test_reject_missing_required_test_and_reject_zero_test_execution(self):
        (self.work / "tests" / v3.REQUIRED_TESTS[0]).unlink()
        with self.assertRaisesRegex(ValueError, "Mandatory"):
            self.archive()
        for name in v3.REQUIRED_TESTS:
            (self.work / "tests" / name).write_text("NOT_A_TEST = True\n")
        data, sha = self.archive()
        self.approve(TAG1, sha)
        with self.assertRaisesRegex(v3.ReleaseError, "0 tests"):
            self.manager.stage(TAG1, data, sha)
        failure = v3.read_json(self.local / "blocked_releases" / TAG1)
        self.assertEqual(failure["stage"], "STAGING_TESTS")
        self.assertEqual(failure["code"], "TEST_FAILED")
        self.assertEqual(failure["rollback"], "NOT_NEEDED")

    def test_reject_tampered_file_without_touching_checkout(self):
        data, sha = self.archive()
        name = f"{v3.WORK_REL}/src/meter_photo_qa/notification_inbox.py"
        source = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as old, zipfile.ZipFile(source, "w") as new:
            for filename in old.namelist():
                content = old.read(filename)
                new.writestr(filename, content + b"tampered" if filename == name else content)
        tampered = source.getvalue()
        with self.assertRaisesRegex(ValueError, "SHA256"):
            v3.validate_archive(tampered, hashlib.sha256(tampered).hexdigest(), TAG1)

    def test_approved_release_does_not_imply_permission_to_activate(self):
        data, sha = self.archive()
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        with self.assertRaisesRegex(v3.ReleaseError, "Pilot staging"):
            self.manager.activate(TAG1)
        self.assertFalse(self.manager.active.exists())

    def test_manual_cutover_still_requires_verified_bridge_and_python(self):
        data, sha = self.archive()
        self.approve(TAG1, sha, office_cutover_approved=True)
        self.manager.stage(TAG1, data, sha)
        with self.assertRaisesRegex(v3.ReleaseError, "navigation bridge"):
            self.manager.activate(TAG1)
        self.assertFalse(self.manager.active.exists())

    def test_activation_and_reversible_second_release(self):
        data, sha = self.archive(TAG1)
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        with patch.object(self.manager, "_precheck"), patch.object(self.manager, "_probe"):
            first = self.manager.activate(TAG1)
        self.assertEqual(first["status"], "ACTIVATED")
        data2, sha2 = self.archive(TAG2)
        self.approve(TAG2, sha2)
        self.manager.stage(TAG2, data2, sha2)
        with patch.object(self.manager, "_precheck"), patch.object(self.manager, "_probe"):
            second = self.manager.activate(TAG2)
        self.assertEqual(second["previous"], TAG1)
        self.assertEqual(self.manager.status()["active"], TAG2)
        self.assertEqual(self.manager.rollback()["tag"], TAG1)
        self.assertEqual(self.manager.status()["active"], TAG1)

    def test_postcheck_failure_returns_to_previous_immutable_version(self):
        data, sha = self.archive(TAG1)
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        with patch.object(self.manager, "_precheck"), patch.object(self.manager, "_probe"):
            self.manager.activate(TAG1)
        data2, sha2 = self.archive(TAG2)
        self.approve(TAG2, sha2)
        self.manager.stage(TAG2, data2, sha2)
        with patch.object(self.manager, "_precheck"), patch.object(
            self.manager, "_probe", side_effect=v3.ReleaseError("POSTCHECK", "IMPORT_PROBE_FAILED")
        ):
            with self.assertRaises(v3.ReleaseError):
                self.manager.activate(TAG2)
        self.assertEqual(self.manager.status()["active"], TAG1)
        self.assertFalse(self.manager.journal.exists())
        blocked = v3.read_json(self.local / "blocked_releases" / TAG2)
        self.assertEqual(blocked["rollback"], "RESTORED_PREVIOUS")

    def test_recover_interrupted_activation_does_not_replay_it(self):
        data, sha = self.archive(TAG1)
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        with patch.object(self.manager, "_precheck"), patch.object(self.manager, "_probe"):
            self.manager.activate(TAG1)
        v3.atomic_json(self.manager.active, {"tag": TAG2})
        v3.atomic_json(self.manager.journal, {
            "state": "SWITCHING", "tag": TAG2, "previous": TAG1
        })
        result = self.manager.recover()
        self.assertEqual(result["status"], "RESTORED_PREVIOUS")
        self.assertEqual(self.manager.status()["active"], TAG1)
        self.assertTrue((self.local / "blocked_releases" / TAG2).exists())

    def test_snapshot_hash_drift_blocks_activation(self):
        data, sha = self.archive()
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        file = self.manager.versions / TAG1 / v3.WORK_REL / "src" / "meter_photo_qa" / "notification_inbox.py"
        file.write_text("MALICIOUS = True\n")
        with self.assertRaisesRegex(v3.ReleaseError, "Snapshot file hash mismatch"):
            self.manager.activate(TAG1)
        self.assertFalse(self.manager.active.exists())

    def test_new_approved_release_can_follow_blocked_older_release(self):
        data, sha = self.archive(TAG1)
        self.approve(TAG1, "0"*64)
        with self.assertRaises(ValueError):
            self.manager.stage(TAG1, data, "0"*64)
        data2, sha2 = self.archive(TAG2)
        self.approve(TAG2, sha2)
        self.assertEqual(self.manager.stage(TAG2, data2, sha2)["status"], "STAGED_TESTED")
        self.assertEqual(self.manager.status()["blocked"], [TAG1])

    def test_package_has_no_watch_config_or_generated_reports(self):
        data, _ = self.archive()
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            names = bundle.namelist()
        self.assertFalse(any("/outputs/" in name[len(v3.WORK_REL):] for name in names))
        self.assertFalse(any(name.endswith(".xlsx") for name in names))
        self.assertFalse(any(name.endswith(".esriAddInX") for name in names))


if __name__ == "__main__":
    unittest.main()

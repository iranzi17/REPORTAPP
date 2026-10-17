"""Adversarial tests for V3: archive identity, staging, compatibility and recovery."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from maintenance import v3_launcher as launcher
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
        # Synthetic unit fixtures use stubs; the real archive has a
        # separate full integration probe on Windows and Linux CI.
        self.compatibility_patch = patch(
            "maintenance.v3_component_compatibility.check_components",
            return_value={"status": "COMPATIBLE", "verified_components": 3},
        )
        self.compatibility_patch.start()
        self.addCleanup(self.compatibility_patch.stop)

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

    def test_combined_qa_regression_is_mandatory_even_when_other_tests_pass(self):
        suite = self.work / "tests" / "test_combined_qa_report.py"
        suite.unlink()
        with self.assertRaisesRegex(ValueError, "Mandatory"):
            self.archive()

    def test_kmz_code_without_test_is_rejected_before_approval(self):
        module = self.root / v3.KMZ_SOURCE
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("VALUE = 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "KMZ module/test mismatch"):
            self.archive()

    def test_kmz_test_without_feature_module_is_rejected(self):
        suite = self.root / v3.KMZ_TEST
        suite.parent.mkdir(parents=True, exist_ok=True)
        suite.write_text("import unittest\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "KMZ module/test mismatch"):
            self.archive()

    def test_kmz_module_and_test_must_be_executed_in_staging(self):
        module = self.root / v3.KMZ_SOURCE
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("VALUE = 1\n", encoding="utf-8")
        suite = self.root / v3.KMZ_TEST
        suite.write_text(
            "import unittest\n"
            "class Companion(unittest.TestCase):\n"
            "    def test_map(self): self.assertTrue(True)\n",
            encoding="utf-8",
        )
        data, sha = self.archive()
        manifest, _ = v3.validate_archive(data, sha, TAG1)
        self.assertIn("test_gap_kmz.py", manifest["required_tests"])
        self.approve(TAG1, sha)
        receipt = self.manager.stage(TAG1, data, sha)
        self.assertGreaterEqual(receipt["tests"]["test_gap_kmz.py"], 1)

    def test_manifest_cannot_discard_combined_qa_test(self):
        data, _ = self.archive()
        replacement = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(replacement, "w") as made:
            for filename in original.namelist():
                payload = original.read(filename)
                if filename == "manifest.json":
                    manifest = json.loads(payload)
                    manifest["required_tests"].remove("test_combined_qa_report.py")
                    payload = json.dumps(manifest).encode("utf-8")
                made.writestr(filename, payload)
        altered = replacement.getvalue()
        with self.assertRaisesRegex(ValueError, "mandatory code/tests"):
            v3.validate_archive(altered, hashlib.sha256(altered).hexdigest(), TAG1)

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

    def test_v2_autodeploy_enabled_blocks_v3_even_with_approved_bridge(self):
        from maintenance.v3_bridge_audit import scan_installed_bridge
        v3.atomic_json(self.manager.local.parent / "policy.json",
                       {"auto_deploy": True, "github_issue_reporting": False})
        policy = {"office_cutover_approved": True,
                  "bridge_version_confirmed": "1.0.4",
                  "bridge_restart_confirmed": True,
                  "runtime_python_confirmed": self.manager.python}
        with patch("maintenance.v3_bridge_audit.scan_installed_bridge",
                   return_value={"status": "VERIFIED_ON_DISK"}):
            with self.assertRaises(v3.ReleaseError) as blocked:
                self.manager._precheck(TAG1, policy)
        self.assertEqual(blocked.exception.code, "V2_AUTODEPLOY_NOT_DISABLED")
        self.assertTrue(v3.read_json(
            self.manager.local.parent / "policy.json")["auto_deploy"])

    def test_missing_or_corrupt_v2_policy_blocks_v3_cutover(self):
        policy = {"office_cutover_approved": True,
                  "bridge_version_confirmed": "1.0.4",
                  "bridge_restart_confirmed": True,
                  "runtime_python_confirmed": self.manager.python}
        with patch("maintenance.v3_bridge_audit.scan_installed_bridge",
                   return_value={"status": "VERIFIED_ON_DISK"}):
            with self.assertRaises(v3.ReleaseError) as missing:
                self.manager._precheck(TAG1, policy)
        self.assertEqual(missing.exception.code, "V2_AUTODEPLOY_NOT_DISABLED")
        (self.manager.local.parent / "policy.json").write_text("{ invalid",
                                                               encoding="utf-8")
        with patch("maintenance.v3_bridge_audit.scan_installed_bridge",
                   return_value={"status": "VERIFIED_ON_DISK"}):
            with self.assertRaises(v3.ReleaseError) as corrupt:
                self.manager._precheck(TAG1, policy)
        self.assertEqual(corrupt.exception.code, "V2_POLICY_UNREADABLE")

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

    def test_stable_launcher_falls_back_to_unchanged_legacy_watcher(self):
        calls = []
        def fake_run(argv, **kw):
            calls.append((argv, kw))
            return SimpleNamespace(returncode=0)
        with patch.object(launcher, "ORIGINAL_CONFIG", self.config):
            with patch.object(launcher, "LEGACY_WORK", self.work):
                code = launcher.run_watcher(
                    self.manager, config=self.config,
                    legacy_work=self.work, runner=fake_run,
                )
        self.assertEqual(code, 0)
        self.assertIn(str(self.work / "src"), calls[0][1]["env"]["PYTHONPATH"])
        self.assertEqual(calls[0][0][-1], str(self.config.resolve()))
        self.assertEqual(self.manager.status()["active"], None)
        self.assertEqual(v3.read_json(self.local / "launcher_latest.json")["mode"],
                         "LEGACY_NO_ACTIVE_V3")

    def test_stable_launcher_uses_only_verified_immutable_release(self):
        data, sha = self.archive()
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        with patch.object(self.manager, "_precheck"), patch.object(self.manager, "_probe"):
            self.manager.activate(TAG1)
        seen = []
        def fake_run(argv, **kw):
            seen.append(kw["env"]["PYTHONPATH"])
            return SimpleNamespace(returncode=0)
        with patch.object(launcher, "ORIGINAL_CONFIG", self.config):
            with patch.object(launcher, "LEGACY_WORK", self.work):
                self.assertEqual(launcher.run_watcher(
                    self.manager, config=self.config,
                    legacy_work=self.work, runner=fake_run), 0)
        self.assertIn(TAG1, seen[0])
        self.assertEqual(v3.read_json(self.local / "launcher_latest.json")["mode"],
                         "V3_" + TAG1)

    def test_corrupt_active_snapshot_falls_back_without_running_corrupt_code(self):
        data, sha = self.archive()
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        with patch.object(self.manager, "_precheck"), patch.object(self.manager, "_probe"):
            self.manager.activate(TAG1)
        bad = self.manager.versions / TAG1 / v3.WORK_REL / "src" / "meter_photo_qa" / "__init__.py"
        bad.write_text("CORRUPTED = True\n")
        seen = []
        def fake_run(argv, **kw):
            seen.append(kw["env"]["PYTHONPATH"])
            return SimpleNamespace(returncode=0)
        with patch.object(launcher, "ORIGINAL_CONFIG", self.config):
            with patch.object(launcher, "LEGACY_WORK", self.work):
                launcher.run_watcher(
                    self.manager, config=self.config, legacy_work=self.work,
                    runner=fake_run)
        self.assertEqual(seen, [str(self.work / "src")])
        self.assertEqual(v3.read_json(self.local / "launcher_latest.json")["mode"],
                         "LEGACY_SNAPSHOT_INVALID")

    def test_incompatible_notification_components_never_seal_candidate(self):
        data, sha = self.archive()
        self.approve(TAG1, sha)
        with patch(
            "maintenance.v3_component_compatibility.check_components",
            side_effect=v3.ReleaseError(
                "COMPONENT_COMPATIBILITY", "NAV_HANDLER_MISSING_EVENT_CONTEXT"
            ),
        ):
            with self.assertRaisesRegex(v3.ReleaseError, "NAV_HANDLER_MISSING_EVENT_CONTEXT"):
                self.manager.stage(TAG1, data, sha)
        self.assertFalse((self.manager.versions / TAG1).exists())
        self.assertFalse(self.manager.active.exists())
        failure = v3.read_json(self.local / "blocked_releases" / TAG1)
        self.assertEqual(failure["stage"], "COMPONENT_COMPATIBILITY")
        self.assertEqual(failure["code"], "NAV_HANDLER_MISSING_EVENT_CONTEXT")

    def test_three_component_receipt_is_required_for_activation(self):
        data, sha = self.archive()
        self.approve(TAG1, sha)
        self.manager.stage(TAG1, data, sha)
        receipt_file = self.local / "receipts" / (TAG1 + ".json")
        receipt = v3.read_json(receipt_file)
        receipt.pop("component_checks")
        v3.atomic_json(receipt_file, receipt)
        with self.assertRaisesRegex(v3.ReleaseError, "NOT_TESTED_OR_NOT_COMPATIBLE"):
            self.manager.activate(TAG1)
        self.assertFalse(self.manager.active.exists())

    def test_package_has_no_watch_config_or_generated_reports(self):
        data, _ = self.archive()
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            names = bundle.namelist()
        self.assertFalse(any("/outputs/" in name[len(v3.WORK_REL):] for name in names))
        self.assertFalse(any(name.endswith(".xlsx") for name in names))
        self.assertFalse(any(name.endswith(".esriAddInX") for name in names))


if __name__ == "__main__":
    unittest.main()

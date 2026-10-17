"""Persistent launcher must resolve immutable V3 without the Git checkout."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

# The launcher is designed to be copied beside v3_core.py in LOCALAPPDATA.
maintenance = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(maintenance))
spec = importlib.util.spec_from_file_location(
    "reportapp_stable_launcher_under_test", maintenance / "v3_persistent_watcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class ManagerFake:
    def __init__(self, root, active=None, journal=False, version=None):
        self.local = root
        self.journal = root / "transaction.json"
        if journal:
            self.journal.write_text('{"state":"SWITCHING"}', encoding="utf-8")
        self.active_tag = active
        self.version = version

    def status(self):
        return {"active": self.active_tag,
                "incomplete_transaction": self.journal.exists()}

    def _verify_version(self, name):
        if not self.version:
            raise ValueError("hash mismatch")
        return self.version


class LauncherTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.legacy = self.root / "legacy" / "src"
        (self.legacy / "meter_photo_qa").mkdir(parents=True)
        (self.legacy / "meter_photo_qa" / "surveyor_notifications.py").write_text(
            "raise RuntimeError('never import inside harness')\n", encoding="utf-8")
        self.config = self.root / "monitor_config.json"
        self.config.write_text('{"accounts":[]}', encoding="utf-8")
        self.version = self.root / "versions" / launcher.PINNED_TAG
        self.v3_src = self.version / launcher.WORK_REL / "src"
        (self.v3_src / "meter_photo_qa").mkdir(parents=True)
        (self.v3_src / "meter_photo_qa" / "surveyor_notifications.py").write_text(
            "raise RuntimeError('never import inside harness')\n", encoding="utf-8")

    def test_v3_exact_candidate_and_original_config_forwarded(self):
        manager = ManagerFake(self.root, active=launcher.PINNED_TAG,
                              version=self.version)
        original_manager = launcher.Manager
        launcher.Manager = lambda *_args, **_kwargs: manager
        self.addCleanup(lambda: setattr(launcher, "Manager", original_manager))
        seen = []
        def fake_run(command, cwd, env, timeout):
            seen.append((command, cwd, env, timeout))
            return types.SimpleNamespace(returncode=0)
        self.assertEqual(launcher.run_once(
            config=self.config, legacy_src=self.legacy,
            local=self.root, python="pythonw.exe", runner=fake_run), 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0][-2:], ["--config", str(self.config.resolve())])
        self.assertEqual(seen[0][2]["PYTHONPATH"], str(self.v3_src))
        self.assertEqual(seen[0][3], 240)
        receipt = json.loads((self.root / "launcher_latest.json").read_text())
        self.assertEqual(receipt["mode"], "V3_VERIFIED")
        self.assertEqual(receipt["status"], "OK")
        self.assertEqual(receipt["source"], "PINNED_IMMUTABLE")

    def test_bad_release_bytes_fall_back_to_existing_legacy_code(self):
        # Simulator's Manager uses actual files; monkeypatch to exercise
        # a corrupt pointer without importing or executing the modules.
        class CorruptManager(ManagerFake):
            def _verify_version(self, name):
                raise ValueError("corrupt staged hash")
        original_manager = launcher.Manager
        launcher.Manager = lambda *_args, **_kwargs: CorruptManager(
            self.root, active=launcher.PINNED_TAG)
        self.addCleanup(lambda: setattr(launcher, "Manager", original_manager))
        seen = []
        def fake_run(command, cwd, env, timeout):
            seen.append(env["PYTHONPATH"])
            return types.SimpleNamespace(returncode=0)
        self.assertEqual(launcher.run_once(
            config=self.config, legacy_src=self.legacy,
            local=self.root, runner=fake_run), 0)
        self.assertEqual(seen[0], str(self.legacy.resolve()))
        self.assertEqual(json.loads((self.root / "launcher_latest.json").read_text())["mode"],
                         "LEGACY_RELEASE_CORRUPT")

    def test_no_config_fails_before_any_watcher_execution(self):
        with self.assertRaisesRegex(RuntimeError, "ORIGINAL_CONFIG_MISSING"):
            launcher.run_once(config=self.root / "absent.json",
                              legacy_src=self.legacy, local=self.root,
                              runner=lambda *args, **kw: self.fail("must not run"))


if __name__ == "__main__":
    unittest.main()

"""Tests for guarded, rollback-aware HKCU REPORTAPP navigation transition."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maintenance import v3_prepare_navigation as nav


class Registry:
    def __init__(self):
        self.command = ('"C:\\Python\\pythonw.exe" "C:\\old\\alert_navigation.py" --uri "%1"', 1)
        self.writes = []
        self.fail_verify = False
        self.fail_write = False

    def read(self):
        if self.fail_verify and self.writes:
            return ("unexpected", 1)
        return self.command

    def write(self, command, kind):
        self.writes.append((command, kind))
        if self.fail_write and len(self.writes) == 1:
            # Simulate partial Windows registry change then exception.
            self.command = (command, kind)
            raise RuntimeError("injected SetValueEx failure")
        self.command = (command, kind)


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = Path(self.temp.name)
        self.reg = Registry()
        self.previous, self.kind = self.reg.read()
        self.new = ('"C:\\Python\\pythonw.exe" "C:\\staged\\alert_navigation.py" --uri "%1"')
        self.patch_windows = patch.object(nav, "_is_windows", return_value=True)
        self.patch_backup = patch.object(nav, "_check_saved_original",
                                         return_value=(self.previous, self.kind))
        self.patch_new = patch.object(nav, "verified_handler", return_value=self.new)
        for p in (self.patch_windows, self.patch_backup, self.patch_new):
            p.start()
            self.addCleanup(p.stop)

    def execute(self, phrase=None):
        return nav.switch(localappdata=self.local, python="python.exe",
                          read=self.reg.read, write=self.reg.write,
                          confirmation=phrase)

    def test_no_approval_never_writes_registry(self):
        with self.assertRaises(nav.NavigationSwitchError) as err:
            self.execute("yes")
        self.assertEqual(err.exception.code, "EXPLICIT_APPROVAL_REQUIRED")
        self.assertEqual(self.reg.writes, [])

    def test_one_command_changes_and_private_rollback_backup_saved(self):
        outcome = self.execute(nav.APPROVE)
        self.assertEqual(outcome["status"], "STAGED_URI_HANDLER_REGISTERED_ZOOM_PAUSED")
        self.assertTrue(outcome["watcher_task_unchanged"])
        self.assertFalse(outcome["v3_activated"])
        self.assertEqual(self.reg.command, (self.new, 1))
        self.assertEqual(self.reg.writes, [(self.new, 1)])
        store = self.local / "REPORTAPP" / "Maintenance" / "v3" / "navigation_backups"
        copies = list(store.glob("*.json"))
        self.assertEqual(len(copies), 1)
        evidence = json.loads(copies[0].read_text())
        self.assertEqual(evidence["previous_command"], self.previous)
        self.assertFalse(evidence["rollback_rehearsed"])

    def test_repeat_switch_is_idempotent(self):
        self.execute(nav.APPROVE)
        self.reg.writes.clear()
        result = self.execute(nav.APPROVE)
        self.assertEqual(result["status"], "ALREADY_ON_STAGED_HANDLER")
        self.assertEqual(self.reg.writes, [])

    def test_unrecognized_original_command_refused(self):
        self.reg.command = ("UNRELATED_URI_HANDLER", 1)
        with self.assertRaises(nav.NavigationSwitchError) as err:
            self.execute(nav.APPROVE)
        self.assertEqual(err.exception.code, "CURRENT_URI_HANDLER_DIFFERS_FROM_BACKUP")
        self.assertEqual(self.reg.writes, [])

    def test_failed_registry_write_restores_original_value(self):
        self.reg.fail_write = True
        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.execute(nav.APPROVE)
        self.assertEqual(self.reg.command, (self.previous, self.kind))
        self.assertEqual(self.reg.writes, [(self.new, 1), (self.previous, 1)])

    def test_postwrite_verification_mismatch_restores_previous(self):
        self.reg.fail_verify = True
        with self.assertRaises(nav.NavigationSwitchError):
            self.execute(nav.APPROVE)
        self.assertEqual(self.reg.command, (self.previous, self.kind))
        self.assertEqual(self.reg.writes, [(self.new, 1), (self.previous, 1)])

    def test_restore_original_handler_only_from_known_staged_value(self):
        self.execute(nav.APPROVE)
        self.reg.writes.clear()
        result = nav.restore(localappdata=self.local, python="python.exe",
                             read=self.reg.read, write=self.reg.write,
                             confirmation="RESTORE ORIGINAL REPORTAPP URI HANDLER")
        self.assertEqual(result["status"], "ORIGINAL_URI_HANDLER_RESTORED")
        self.assertEqual(self.reg.command, (self.previous, self.kind))
        self.assertEqual(self.reg.writes, [(self.previous, self.kind)])

    def test_restore_requires_explicit_separate_confirmation(self):
        self.execute(nav.APPROVE)
        self.reg.writes.clear()
        with self.assertRaises(nav.NavigationSwitchError) as err:
            nav.restore(localappdata=self.local, python="python.exe",
                        read=self.reg.read, write=self.reg.write,
                        confirmation="yes")
        self.assertEqual(err.exception.code, "EXPLICIT_RESTORE_APPROVAL_REQUIRED")
        self.assertEqual(self.reg.writes, [])

    def test_refuse_restore_over_unrelated_uri_handler(self):
        self.reg.command = ("UNRELATED URI HANDLER", 1)
        with self.assertRaises(nav.NavigationSwitchError) as err:
            nav.restore(localappdata=self.local, python="python.exe",
                        read=self.reg.read, write=self.reg.write,
                        confirmation="RESTORE ORIGINAL REPORTAPP URI HANDLER")
        self.assertEqual(err.exception.code, "UNEXPECTED_URI_HANDLER_REFUSE_RESTORE")
        self.assertEqual(self.reg.writes, [])

    def test_status_does_not_change_registry(self):
        result = nav.status(localappdata=self.local, python="python.exe",
                            read=self.reg.read)
        self.assertEqual(result["status"], "ORIGINAL_HANDLER_REGISTERED")
        self.assertEqual(self.reg.writes, [])


if __name__ == "__main__":
    unittest.main()

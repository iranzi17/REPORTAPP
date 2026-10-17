"""Cutover backup does not call task registration, registry setters or GIS."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from maintenance import v3_cutover_backup as backup


TASK_XML = """<?xml version="1.0" encoding="utf-8"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task" version="1.4">
 <Triggers>
  <TimeTrigger><Repetition><Interval>PT1M</Interval><Duration>P3650D</Duration></Repetition></TimeTrigger>
 </Triggers>
 <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings>
 <Actions Context="Author">
  <Exec>
   <Command>C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\pythonw.exe</Command>
   <Arguments>-m meter_photo_qa.surveyor_notifications --config "C:\\reportapp\\monitor_config.json"</Arguments>
   <WorkingDirectory>C:\\reportapp\\src</WorkingDirectory>
  </Exec>
 </Actions>
</Task>"""
REGISTRY = {
    "root_default": {"present": True, "value": "URL:REPORTAPP navigation", "value_type": 1},
    "url_protocol": {"present": True, "value": "", "value_type": 1},
    "open_command": {"present": True, "value": '"C:\\pythonw.exe" "C:\\reportapp\\alert_navigation.py" --uri "%1"', "value_type": 1},
}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "v3-local"
        self.calls = []

    def _task(self):
        self.calls.append("READ_TASK_XML")
        return TASK_XML

    def _reg(self):
        self.calls.append("READ_HKCU_PROTOCOL")
        return REGISTRY

    def test_exact_original_backup_and_digest_verification(self):
        result = backup.capture(self.folder, task_xml_supplier=self._task,
                                registry_supplier=self._reg)
        self.assertEqual(self.calls, ["READ_TASK_XML", "READ_HKCU_PROTOCOL"])
        self.assertEqual(result["status"], "BACKUP_VERIFIED_ONLY")
        self.assertTrue(result["original_task_evidence_saved"])
        self.assertTrue(result["original_registry_evidence_saved"])
        self.assertFalse(result["rollback_rehearsed"])
        self.assertFalse(result["production_task_changed"])
        self.assertFalse(result["production_registry_changed"])
        root = Path(result["backup_folder"])
        self.assertEqual((root / "task_before.xml").read_text(encoding="utf-8"), TASK_XML)
        self.assertEqual(json.loads((root / "protocol_before.json").read_text()), REGISTRY)
        self.assertEqual(backup.verify_backup(root)["status"], "BACKUP_VERIFIED_ONLY")

    def test_corrupted_task_backup_fails_before_any_cutover(self):
        result = backup.capture(self.folder, task_xml_supplier=self._task,
                                registry_supplier=self._reg)
        folder = Path(result["backup_folder"])
        (folder / "task_before.xml").write_text("TAMPERED", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            backup.verify_backup(folder)

    def test_corrupted_registry_backup_fails_before_any_cutover(self):
        result = backup.capture(self.folder, task_xml_supplier=self._task,
                                registry_supplier=self._reg)
        folder = Path(result["backup_folder"])
        (folder / "protocol_before.json").write_text("TAMPERED", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            backup.verify_backup(folder)

    def test_nonstandard_schedule_produces_review_not_false_authorization(self):
        result = backup.capture(self.folder, task_xml_supplier=lambda: TASK_XML.replace("PT1M", "PT5M"),
                                registry_supplier=self._reg)
        self.assertEqual(result["status"], "BACKUP_REQUIRES_REVIEW")
        self.assertFalse(result["task_checks"]["interval_one_minute"])
        self.assertFalse(result["cutover_authorized"])

    def test_unregistered_handler_is_backed_up_but_not_approved(self):
        result = backup.capture(self.folder, task_xml_supplier=self._task,
                                registry_supplier=lambda: {
                                    **REGISTRY, "open_command": {"present": False}
                                })
        self.assertEqual(result["status"], "BACKUP_REQUIRES_REVIEW")
        self.assertFalse(result["protocol_checks"]["handler_present"])

    def test_no_backup_folder_if_task_export_fails(self):
        with self.assertRaisesRegex(RuntimeError, "failed to read"):
            backup.capture(self.folder, task_xml_supplier=lambda: (_ for _ in ()).throw(
                RuntimeError("failed to read")), registry_supplier=self._reg)
        self.assertFalse(self.folder.exists())

    def test_second_backup_never_overwrites_original(self):
        one = backup.capture(self.folder, task_xml_supplier=self._task,
                             registry_supplier=self._reg)
        two = backup.capture(self.folder, task_xml_supplier=self._task,
                             registry_supplier=self._reg)
        self.assertNotEqual(one["backup_folder"], two["backup_folder"])
        self.assertEqual(backup.verify_backup(one["backup_folder"])["status"],
                         "BACKUP_VERIFIED_ONLY")

    def test_no_task_xml_uploaded_in_machine_readable_status(self):
        result = backup.capture(self.folder, task_xml_supplier=self._task,
                                registry_supplier=self._reg)
        reported = json.dumps({k: v for k, v in result.items() if k != "backup_folder"})
        self.assertNotIn("monitor_config.json", reported)
        self.assertNotIn("pythonw.exe", reported)
        self.assertNotIn("alert_navigation.py", reported)
        self.assertEqual(result["cutover_authorized"], False)


if __name__ == "__main__":
    unittest.main()

"""V3 bridge safety: validate REAL installed add-in, not operator-supplied version."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
from types import SimpleNamespace
from xml.sax.saxutils import escape
import zipfile

from maintenance import v3_bridge_audit as audit
from maintenance import v3_core as core


class BridgeAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = Path(self.tmp.name) / "Documents"
        self.esri = (self.doc / "ArcGIS" / "AddIns" / "ArcGISPro" /
                     audit.BRIDGE_ID / audit.BRIDGE_NAME)
        self.esri.parent.mkdir(parents=True)
        self.manager = core.Manager(Path(self.tmp.name) / "v3")

    def create_addin(self, version="1.0.4", name="REPORTAPP Alert Zoom Bridge",
                     addin_id=None):
        daml = (
            '<?xml version="1.0"?><ArcGIS xmlns="http://schemas.esri.com/DADF/Registry">'
            '<AddInInfo id="' + (addin_id or audit.BRIDGE_ID) +
            '" version="' + escape(version) + '" desktopVersion="3.4">'
            '<Name>' + escape(name) + '</Name></AddInInfo></ArcGIS>'
        )
        with zipfile.ZipFile(self.esri, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Config.daml", daml)
            archive.writestr("Install/ReportappNavigationBridge.dll", b"FAKE DLL - metadata only")
        return hashlib.sha256(self.esri.read_bytes()).hexdigest()

    def test_confirmed_office_103_is_rejected_even_with_package_hash(self):
        sha = self.create_addin(version="1.0.3")
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.scan_installed_bridge(documents_folders=[self.doc], expected_sha256=sha)
        self.assertEqual(caught.exception.code, "WRONG_VERSION")

    def test_expected_104_metadata_and_exact_sha_are_both_required(self):
        sha = self.create_addin(version="1.0.4")
        result = audit.scan_installed_bridge(documents_folders=[self.doc], expected_sha256=sha)
        self.assertEqual(result["bridge_version"], "1.0.4")
        self.assertEqual(result["status"], "VERIFIED_ON_DISK")
        self.assertFalse(result["arcgis_pro_restarted_verified"])
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.scan_installed_bridge(documents_folders=[self.doc], expected_sha256="0" * 64)
        self.assertEqual(caught.exception.code, "WRONG_RELEASE_BUILD")

    def test_bridge_104_with_numeric_suffix_is_found_and_verified(self):
        # Matches the office Add-In Manager screenshot:
        # ReportappNavigationBridge (1).esriAddInX
        new_sha = self.create_addin(version="1.0.4")
        renamed = self.esri.with_name("ReportappNavigationBridge (1).esriAddInX")
        self.esri.rename(renamed)
        result = audit.scan_installed_bridge(
            documents_folders=[self.doc], expected_sha256=new_sha)
        self.assertEqual(result["status"], "VERIFIED_ON_DISK")
        self.assertEqual(result["bridge_version"], "1.0.4")
        self.assertEqual(result["other_bridge_files_present"], 0)

    def test_stale_103_unsuffixed_cannot_mask_approved_104_with_suffix(self):
        old_sha = self.create_addin(version="1.0.3")
        old_bytes = self.esri.read_bytes()
        new_sha = self.create_addin(version="1.0.4")
        self.esri.rename(self.esri.with_name("ReportappNavigationBridge (1).esriAddInX"))
        self.esri.write_bytes(old_bytes)
        result = audit.scan_installed_bridge(
            documents_folders=[self.doc], expected_sha256=new_sha)
        self.assertEqual(result["bridge_version"], "1.0.4")
        self.assertEqual(result["other_bridge_files_present"], 1)
        self.assertNotEqual(old_sha, new_sha)

    def test_duplicate_identical_104_build_fails_closed(self):
        new_sha = self.create_addin()
        self.esri.with_name("ReportappNavigationBridge (1).esriAddInX").write_bytes(
            self.esri.read_bytes())
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.scan_installed_bridge(documents_folders=[self.doc],
                                        expected_sha256=new_sha)
        self.assertEqual(caught.exception.code, "AMBIGUOUS_ADDIN")

    def test_filename_suffix_not_a_substitute_for_verified_package(self):
        self.create_addin(version="1.0.3")
        self.esri.rename(self.esri.with_name(
            "ReportappNavigationBridge (1).esriAddInX"))
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.scan_installed_bridge(documents_folders=[self.doc])
        self.assertIn(caught.exception.code, ("WRONG_VERSION", "WRONG_RELEASE_BUILD"))

    def test_install_folder_only_rejects_download_file_even_with_suffix(self):
        sha = self.create_addin()
        external = Path(self.tmp.name) / "Downloads" / "ReportappNavigationBridge (1).esriAddInX"
        external.parent.mkdir()
        external.write_bytes(self.esri.read_bytes())
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.validate_installed_file(external, expected_sha256=sha)
        self.assertEqual(caught.exception.code, "NOT_INSTALLED")

    def test_downloads_copy_is_not_installed_esri_addin(self):
        sha = self.create_addin()
        copy = Path(self.tmp.name) / "Downloads" / audit.BRIDGE_NAME
        copy.parent.mkdir()
        copy.write_bytes(self.esri.read_bytes())
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.validate_installed_file(copy, expected_sha256=sha)
        self.assertEqual(caught.exception.code, "NOT_INSTALLED")

    def test_wrong_addin_identity_fails_closed(self):
        sha = self.create_addin(addin_id="{00000000-0000-0000-0000-000000000000}")
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.scan_installed_bridge(documents_folders=[self.doc], expected_sha256=sha)
        self.assertEqual(caught.exception.code, "WRONG_ADDIN")

    def test_no_addin_fails_without_modifying_office(self):
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.scan_installed_bridge(documents_folders=[self.doc])
        self.assertEqual(caught.exception.code, "NOT_INSTALLED")

    def test_activation_rejects_false_policy_flag_if_disk_shows_103(self):
        self.create_addin(version="1.0.3")
        p = {"office_cutover_approved": True,
             "bridge_version_confirmed": "1.0.4",
             "bridge_restart_confirmed": True,
             "runtime_python_confirmed": self.manager.python}
        with patch("maintenance.v3_bridge_audit.scan_installed_bridge",
                   side_effect=audit.BridgeAuditError("WRONG_VERSION",
                                                      "Installed REPORTAPP Bridge version: 1.0.3")):
            with self.assertRaises(core.ReleaseError) as caught:
                self.manager._precheck("reportapp-v3-v20261017-000001", p)
        self.assertEqual(caught.exception.code, "BRIDGE_WRONG_VERSION")

    def test_successful_disk_audit_still_requires_restart_and_python(self):
        self.create_addin()
        p = {"office_cutover_approved": True,
             "bridge_version_confirmed": "1.0.4",
             "bridge_restart_confirmed": False,
             "runtime_python_confirmed": self.manager.python}
        with patch("maintenance.v3_bridge_audit.scan_installed_bridge",
                   return_value={"status": "VERIFIED_ON_DISK"}):
            with self.assertRaises(core.ReleaseError) as caught:
                self.manager._precheck("reportapp-v3-v20261017-000001", p)
        self.assertEqual(caught.exception.code, "BRIDGE_RESTART_UNVERIFIED")

    def test_manual_policy_cannot_override_official_package_hash(self):
        sha = self.create_addin()
        self.assertNotEqual(sha, audit.EXPECTED_SHA256)
        with self.assertRaises(audit.BridgeAuditError) as caught:
            audit.scan_installed_bridge(documents_folders=[self.doc])
        self.assertEqual(caught.exception.code, "WRONG_RELEASE_BUILD")


if __name__ == "__main__":
    unittest.main()

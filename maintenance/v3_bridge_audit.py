"""Read-only validation of the ACTUALLY installed REPORTAPP ArcGIS Pro add-in.

The version claimed by policy.json, a release ZIP downloaded to Downloads, or
an unverified copy on disk must never authorize a V3 cutover.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

BRIDGE_ID = "{B5ED8B73-4944-47D7-B8DF-A4EE9D75C9C2}"
BRIDGE_NAME = "ReportappNavigationBridge.esriAddInX"
EXPECTED_VERSION = "1.0.4"
EXPECTED_SHA256 = "66e3688ba7bde34caf210108d3a73225dee7abb8cd39b4e14bd64b6892963a39"
OFFICIAL_RELEASE = "reportapp-bridge-v1.0.4"
MAX_ADDIN_SIZE = 5_000_000
# Esri may preserve a previous install and write an approved update as "(1)".
# The filename is NOT proof of identity: the SHA256 and AddInInfo must match.
_ALLOWED_ADDIN_NAME = re.compile(
    r"ReportappNavigationBridge(?: \\([1-9][0-9]*\\))?\\.esriAddInX", re.IGNORECASE
)


class BridgeAuditError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def document_folders():
    """Use Windows redirected Documents when configured; never write to it."""
    folders = []
    if os.name == "nt":
        try:
            import winreg
            keyname = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, keyname) as key:
                raw, _ = winreg.QueryValueEx(key, "Personal")
            if isinstance(raw, str) and raw:
                folders.append(Path(os.path.expandvars(raw)).expanduser())
        except (OSError, ValueError):
            pass
    folders.append(Path.home() / "Documents")
    return list(dict.fromkeys(path for path in folders))


def installed_candidates(folders=None):
    """Only the Esri installed-addins folder, NEVER a downloaded release ZIP."""
    bases = document_folders() if folders is None else list(folders)
    unique = {}
    for documents in bases:
        folder = (Path(documents) / "ArcGIS" / "AddIns" / "ArcGISPro" / BRIDGE_ID)
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if (_ALLOWED_ADDIN_NAME.fullmatch(path.name) and path.is_file()
                    and not path.is_symlink()):
                unique[str(path.resolve()).casefold()] = path
    return list(unique.values())


def validate_installed_file(path, *, expected_sha256=EXPECTED_SHA256):
    """Verify identity, package metadata and pinned bytes without executing code."""
    path = Path(path)
    # Only a nested Esri install is acceptable. Validate the parent structure,
    # not an arbitrary file copied into Downloads and renamed.
    if (not _ALLOWED_ADDIN_NAME.fullmatch(path.name)
            or path.parent.name.casefold() != BRIDGE_ID.casefold()
            or path.parent.parent.name.casefold() != "arcgispro"
            or path.parent.parent.parent.name.casefold() != "addins"
            or path.parent.parent.parent.parent.name.casefold() != "arcgis"):
        raise BridgeAuditError("NOT_INSTALLED", "File is not in the REPORTAPP Esri add-in folder")
    if path.is_symlink() or not path.is_file():
        raise BridgeAuditError("NOT_INSTALLED", "Installed bridge file is absent or linked")
    if path.stat().st_size > MAX_ADDIN_SIZE:
        raise BridgeAuditError("INVALID_PACKAGE", "Installed add-in package is oversized")
    with zipfile.ZipFile(path, "r") as archive:
        if "Config.daml" not in archive.namelist():
            raise BridgeAuditError("INVALID_PACKAGE", "Installed add-in manifest is missing")
        if "Install/ReportappNavigationBridge.dll" not in archive.namelist():
            raise BridgeAuditError("INVALID_PACKAGE", "Installed add-in assembly is missing")
        manifest = archive.read("Config.daml")
        if len(manifest) > 70_000:
            raise BridgeAuditError("INVALID_PACKAGE", "Installed add-in manifest is oversized")
    try:
        root = ET.fromstring(manifest)
    except ET.ParseError as exc:
        raise BridgeAuditError("INVALID_PACKAGE", "Installed add-in manifest is invalid") from exc
    items = [item for item in root.iter() if item.tag.split("}")[-1] == "AddInInfo"]
    if len(items) != 1:
        raise BridgeAuditError("INVALID_PACKAGE", "Ambiguous AddInInfo entries")
    item = items[0]
    name = next((node.text or "" for node in item
                 if node.tag.split("}")[-1] == "Name"), "")
    if (item.get("id", "").casefold() != BRIDGE_ID.casefold()
            or name.strip() != "REPORTAPP Alert Zoom Bridge"
            or item.get("desktopVersion") != "3.4"):
        raise BridgeAuditError("WRONG_ADDIN", "Installed add-in identity or target differs")
    version = item.get("version", "")
    if version != EXPECTED_VERSION:
        raise BridgeAuditError("WRONG_VERSION", "Installed REPORTAPP Bridge version: " + version)
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256.lower()):
        raise BridgeAuditError("WRONG_RELEASE_BUILD", "Installed add-in differs from approved 1.0.4 release bytes")
    return {"status": "VERIFIED_ON_DISK", "bridge_version": version,
            "release": OFFICIAL_RELEASE, "package_sha256": expected_sha256.lower(),
            "arcgis_pro_restarted_verified": False}


def scan_installed_bridge(*, documents_folders=None, expected_sha256=EXPECTED_SHA256):
    matches = installed_candidates(documents_folders)
    if not matches:
        raise BridgeAuditError("NOT_INSTALLED", "REPORTAPP add-in not found in Esri installed folder")
    # Select based on APPROVED BYTES, never numeric suffix or name alone.
    # Do not accept the legacy 1.0.3 add-in just because it has the unsuffixed
    # name. Refuse if two identical approved packages are installed.
    valid = []
    diagnostics = []
    for candidate in matches:
        try:
            result = validate_installed_file(candidate, expected_sha256=expected_sha256)
        except (BridgeAuditError, OSError, zipfile.BadZipFile) as exc:
            diagnostics.append(getattr(exc, "code", "INVALID_PACKAGE"))
        else:
            valid.append(result)
    if len(valid) > 1:
        raise BridgeAuditError("AMBIGUOUS_ADDIN", "Multiple approved 1.0.4 bridge packages found")
    if not valid:
        if len(matches) == 1:
            return validate_installed_file(matches[0], expected_sha256=expected_sha256)
        raise BridgeAuditError("NO_VERIFIED_RELEASE", "No installed bridge matches approved 1.0.4 bytes")
    selected = dict(valid[0])
    selected["other_bridge_files_present"] = len(matches) - 1
    return selected

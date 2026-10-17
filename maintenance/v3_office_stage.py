"""One-click staging of the office-accepted, immutable V3 candidate.

This does NOT activate a V3 pointer, alter existing Python source, Scheduled
Tasks, protocol registration, SQLite state, ArcGIS add-ins or REG records.
Requires approved V2 health-only policy (auto_deploy=false).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

from maintenance.v3_core import (
    Manager, REPO, WORK_REL, ReleaseError, atomic_json, read_json,
    validate_archive,
)

PINNED_TAG = "reportapp-v3-v20261017-000032"
PINNED_SHA256 = "1dac15a37682c79f11508aaea80c344a50dfdb08d7dfede7a19b2ed7575cd948"
EXPECTED_COUNT = 83
EXPECTED_TESTS = {
    "test_surveyor_notifications.py": 22,
    "test_notification_inbox.py": 9,
    "test_alert_navigation.py": 15,
    "test_surveyor_activity.py": 10,
    "test_deferred_notifications.py": 11,
    "test_combined_qa_report.py": 4,
}


def _safe_report(report, *, local=None):
    base = Path(local) if local else Path(os.environ["LOCALAPPDATA"]) / "REPORTAPP"
    reports = base / "Diagnostics"
    reports.mkdir(parents=True, exist_ok=True)
    name = ("office_v3_stage_" +
            time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) +
            "-" + uuid.uuid4().hex[:8] + ".json")
    path = reports / name
    # Create once, never overwrite historical acceptance receipts.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
    return path


def stage(package_path, *, appdata=None, python=None,
          runtime_check=True, staging_class=Manager):
    """Checks V2 safety, validates known bytes, then stages (never activates)."""
    local = Path(appdata if appdata is not None else os.environ["LOCALAPPDATA"])
    maintenance = local / "REPORTAPP" / "Maintenance"
    v3root = maintenance / "v3"
    report = {
        "tool": "REPORTAPP_V3_OFFICE_STAGE_V1",
        "tag": PINNED_TAG,
        "status": "NOT_STARTED",
        "v2_auto_deploy_disabled": False,
        "original_watcher_task_unchanged": True,
        "navigation_registry_unchanged": True,
        "arcgis_addin_unchanged": True,
        "GIS_data_unchanged": True,
        "v3_activated": False,
        "live_notification_sent": False,
        "checks": {},
    }
    manager = None
    report["phase"] = "MANAGER_INITIALIZATION"
    try:
        manager = staging_class(v3root, python=python or sys.executable)
        report["phase"] = "ARCGIS_PREFLIGHT"
        if os.name != "nt" and runtime_check:
            raise ReleaseError("PREFLIGHT", "WINDOWS_REQUIRED")
        if sys.version_info[:2] != (3, 11) and runtime_check:
            raise ReleaseError("PREFLIGHT", "PYTHON_3_11_REQUIRED")
        if runtime_check:
            try:
                import arcpy
                version = str(arcpy.GetInstallInfo().get("Version", ""))
            except (ImportError, OSError, AttributeError, KeyError, TypeError) as exc:
                raise ReleaseError("PREFLIGHT", "ARCGIS_RUNTIME_UNAVAILABLE") from exc
            if not version.startswith("3.4"):
                raise ReleaseError("PREFLIGHT", "ARCGIS_3_4_REQUIRED")
            report["checks"]["arcgis_python"] = "CONFIRMED_3_4"
        report["phase"] = "V2_POLICY_CHECK"
        try:
            v2_policy = read_json(maintenance / "policy.json")
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseError("PREFLIGHT", "V2_POLICY_UNREADABLE") from exc
        if not isinstance(v2_policy, dict) or v2_policy.get("auto_deploy") is not False:
            raise ReleaseError("PREFLIGHT", "V2_AUTO_DEPLOY_STILL_ENABLED")
        report["v2_auto_deploy_disabled"] = True

        # Staging never writes a live V3 pointer. A pre-existing pointer
        # means an earlier operator already attempted activation: stop.
        report["phase"] = "V3_POINTER_CHECK"
        if manager.active.exists() or manager.journal.exists():
            raise ReleaseError("PREFLIGHT", "V3_ACTIVATION_STATE_EXISTS")
        report["phase"] = "ARCHIVE_CHECK"
        archive = Path(package_path).read_bytes()
        digest = hashlib.sha256(archive).hexdigest()
        if digest != PINNED_SHA256:
            raise ReleaseError("PACKAGE", "UNAPPROVED_PACKAGE_SHA256")
        manifest, payload = validate_archive(archive, PINNED_SHA256, PINNED_TAG)
        if len(payload) != EXPECTED_COUNT or manifest.get("tag") != PINNED_TAG:
            raise ReleaseError("PACKAGE", "PACKAGE_CONTENT_COUNT_MISMATCH")
        report["checks"]["release_identity"] = "PINNED_TAG_AND_SHA256_VERIFIED"
        report["checks"]["files"] = len(payload)

        approved = {
            "repository": REPO, "enabled": True,
            "approved_tag": PINNED_TAG,
            "approved_sha256": PINNED_SHA256,
            "office_cutover_approved": False,
        }
        report["phase"] = "STAGING_POLICY"
        current_policy = read_json(manager.policy)
        if current_policy is None:
            atomic_json(manager.policy, approved)
        elif not isinstance(current_policy, dict) or any(
            current_policy.get(key) != value for key, value in approved.items()
        ):
            raise ReleaseError("PREFLIGHT", "V3_POLICY_ALREADY_DIFFERENT")

        report["phase"] = "ISOLATED_STAGING"
        version_dir = manager.versions / PINNED_TAG
        existing = read_json(manager.local / "receipts" / (PINNED_TAG + ".json"), {})
        if version_dir.exists():
            manager._verify_version(PINNED_TAG)
            if (existing.get("status") != "STAGED_TESTED"
                    or existing.get("archive_sha256") != PINNED_SHA256
                    or (existing.get("component_checks") or {}).get("status") != "COMPATIBLE"):
                raise ReleaseError("STAGING", "STAGE_EXISTS_WITHOUT_VERIFIED_RECEIPT")
            suite_counts = existing.get("tests", {})
            if any(suite_counts.get(name, 0) < n for name, n in EXPECTED_TESTS.items()):
                raise ReleaseError("STAGING", "PREVIOUS_STAGE_COUNTS_INSUFFICIENT")
            report["checks"]["stage_mode"] = "EXISTING_VERIFIED_NO_RETEST"
        else:
            receipt = manager.stage(PINNED_TAG, archive, PINNED_SHA256)
            suite_counts = receipt.get("tests", {})
            if any(suite_counts.get(name, 0) < n for name, n in EXPECTED_TESTS.items()):
                raise ReleaseError("STAGING", "EXPECTED_OFFICE_TEST_COUNTS_MISSING")
            manager._verify_version(PINNED_TAG)
            report["checks"]["stage_mode"] = "STAGED_AND_TESTED"
            report["checks"]["component_compatibility"] = (
                receipt.get("component_checks") or {}).get("status")

        if manager.active.exists() or manager.journal.exists():
            raise ReleaseError("STAGING", "UNEXPECTED_ACTIVATION_POINTER")
        report["checks"]["suite_counts"] = suite_counts
        report["status"] = "STAGED_TESTED_NOT_ACTIVATED"
        report["phase"] = "COMPLETE"
    except Exception as exc:
        report["status"] = "FAILED_SAFE"
        report["error_stage"] = getattr(exc, "stage", "PREFLIGHT")
        report["error_code"] = getattr(exc, "code", type(exc).__name__)
        # Save a privacy-safe failure origin, not the traceback or service data.
        import traceback
        frames = traceback.extract_tb(exc.__traceback__)
        if frames:
            last = frames[-1]
            report["failure_origin"] = {
                "module": Path(last.filename).name,
                "function": last.name,
                "line": last.lineno,
            }
        report["error_type"] = type(exc).__name__
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    arguments = parser.parse_args()
    from pathlib import Path
    import traceback
    try:
        result = stage(arguments.candidate)
        print("V3 staging:", result["status"])
        print("Phase:", result.get("phase", "UNKNOWN"))
        print("Result code:", result.get("error_code", "NONE"))
        if "failure_origin" in result:
            print("Failure origin:", result["failure_origin"])
        # Reaching staging success does NOT mean V3 was activated.
        destination = _safe_report(result)
        print("Shareable receipt:", destination)
        print("Original live watcher and navigation registration unchanged.")
        return 0 if result["status"] == "STAGED_TESTED_NOT_ACTIVATED" else 2
    except Exception as exc:
        # Previously this catch erased ALL evidence of the actual error.
        # Expose only function, module basename and line; never raw paths.
        frames = traceback.extract_tb(exc.__traceback__)
        last = frames[-1] if frames else None
        report = {
            "tool": "REPORTAPP_V3_OFFICE_STAGE_V2",
            "status": "WRAPPER_FAILED_SAFE",
            "error_type": type(exc).__name__,
            "phase": "CLI_OR_RECEIPT",
            "failure_origin": (
                {"module": Path(last.filename).name,
                 "function": last.name, "line": last.lineno}
                if last else None),
            "original_watcher_task_unchanged": True,
            "v3_activated": False,
        }
        print("Office staging wrapper failure:", report["error_type"])
        print("Failure origin:", report["failure_origin"])
        try:
            destination = _safe_report(report)
            print("Shareable receipt:", destination)
        except Exception as report_exc:
            print("Diagnostic receipt failure:", type(report_exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

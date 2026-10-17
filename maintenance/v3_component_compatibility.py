"""Read-only integration probe for the three source-event navigation components.

Runs in a subprocess with the versioned candidate's source as PYTHONPATH.
Never opens REG, sends a notification, edits a database or queues a live zoom.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from maintenance.v3_core import WORK_REL, ReleaseError

PROBE = r'''
import inspect, json
from pathlib import Path
from meter_photo_qa import surveyor_notifications as watcher
from meter_photo_qa import notification_inbox as inbox
from meter_photo_qa import alert_navigation as navigation

expected_root = Path(__import__("os").environ["REPORTAPP_V3_CANDIDATE_SRC"]).resolve()
for name, module in (("surveyor_notifications", watcher),
                     ("notification_inbox", inbox),
                     ("alert_navigation", navigation)):
    origin = Path(module.__file__).resolve()
    if expected_root not in origin.parents:
        raise AssertionError("MIXED_COMPONENT_SOURCE:" + name)

for name in ("globalid", "event_time_utc_ms", "actor", "gdb_version"):
    if name not in inspect.signature(navigation.zoom_uri).parameters:
        raise AssertionError("NAV_HANDLER_MISSING_EVENT_CONTEXT:" + name)
if not callable(getattr(inbox, "format_details", None)):
    raise AssertionError("INBOX_INTERFACE_MISSING")

created_ms = 1760000000000
edited_ms = 1790000000000
attrs = {
    "created_date": created_ms,
    "last_edited_date": edited_ms,
    "created_user": "original_surveyor",
    "last_edited_user": "new_surveyor",
}
if watcher.event_timestamp(attrs) != edited_ms:
    raise AssertionError("WATCHER_SOURCE_TIME_MISMATCH")
actor, event_type = watcher.submission_actor(attrs)
if (actor, event_type) != ("new_surveyor", "EDIT"):
    raise AssertionError("WATCHER_EVENT_ACTOR_MISMATCH")
gid = "{142A4DBA-F393-4597-90A9-3878A86827B9}"
url = navigation.zoom_uri(
    "pole", 891705, globalid=gid, event_time_utc_ms=edited_ms,
    actor=actor, gdb_version="sde.DEFAULT",
)
if "event_ms=" not in url or "gid=" not in url or "actor=" not in url:
    raise AssertionError("NAV_URI_OMITS_SOURCE_IDENTITY")
asset, oid, canonical = navigation.parse_uri(url)
if (asset, oid, canonical) != ("pole", 891705, url):
    raise AssertionError("NAV_URI_ROUNDTRIP_FAILED")
legacy = navigation.zoom_uri("pole", 891705)
if any(key in legacy for key in ("event_ms=", "gid=", "actor=")):
    raise AssertionError("LEGACY_URI_INCORRECTLY_VERIFIED")
if navigation._parse_components(legacy)[3]:
    raise AssertionError("LEGACY_URI_MISLABELED_AS_VERIFIED")
print(json.dumps({
    "status": "COMPATIBLE",
    "verified_components": 3,
    "source_time_and_actor_consistent": True,
    "validated_globalid_and_gdb_version": True,
    "live_navigation_triggered": False,
}))
'''


def check_components(version_root, *, python=None, timeout=60):
    version_root = Path(version_root).resolve()
    candidate_src = version_root / WORK_REL / "src"
    for component in ("surveyor_notifications.py",
                      "notification_inbox.py", "alert_navigation.py"):
        target = candidate_src / "meter_photo_qa" / component
        if not target.is_file():
            raise ReleaseError("COMPONENT_COMPATIBILITY", "MISSING_COMPONENT", component)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(candidate_src)
    env["REPORTAPP_V3_CANDIDATE_SRC"] = str(candidate_src)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run([str(python or sys.executable), "-c", PROBE],
                                cwd=str(version_root), env=env, text=True,
                                capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError("COMPONENT_COMPATIBILITY", "CHECK_RUNTIME_FAILED",
                           type(exc).__name__) from exc
    if result.returncode != 0:
        combined = result.stderr + result.stdout
        markers = ["MIXED_COMPONENT_SOURCE", "NAV_HANDLER_MISSING_EVENT_CONTEXT",
                   "INBOX_INTERFACE_MISSING", "WATCHER_SOURCE_TIME_MISMATCH",
                   "WATCHER_EVENT_ACTOR_MISMATCH", "NAV_URI_OMITS_SOURCE_IDENTITY",
                   "NAV_URI_ROUNDTRIP_FAILED", "LEGACY_URI_INCORRECTLY_VERIFIED",
                   "LEGACY_URI_MISLABELED_AS_VERIFIED"]
        issue = next((marker for marker in markers if marker in combined),
                     "PROBE_IMPORT_OR_INTERFACE_FAILED")
        raise ReleaseError("COMPONENT_COMPATIBILITY", issue,
                           "Source-verified watcher, Inbox and URI handler probe failed")
    try:
        receipt = json.loads(result.stdout.strip())
    except (ValueError, TypeError) as exc:
        raise ReleaseError("COMPONENT_COMPATIBILITY", "INVALID_PROBE_RESULT") from exc
    if receipt.get("status") != "COMPATIBLE" or receipt.get("verified_components") != 3:
        raise ReleaseError("COMPONENT_COMPATIBILITY", "INCOMPLETE_COMPATIBILITY")
    return receipt

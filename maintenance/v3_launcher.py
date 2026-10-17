"""Stable opt-in V3 watcher launcher; never edits or recreates Windows tasks.

Use only AFTER office acceptance and explicit Scheduled Task cutover.
Legacy code remains a safe fallback when V3 has no verified active snapshot.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maintenance.v3_core import Manager, WORK_REL, atomic_json

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_WORK = REPO_ROOT / WORK_REL
ORIGINAL_CONFIG = (LEGACY_WORK / "outputs" /
                   "REPORTAPP_Surveyor_Notifications" / "monitor_config.json")
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "REPORTAPP" / "Maintenance" / "v3"


def select_runtime(manager, legacy_work=LEGACY_WORK):
    """Verify immutable active snapshot before using its Python import path."""
    legacy_src = Path(legacy_work) / "src"
    required_legacy = legacy_src / "meter_photo_qa" / "surveyor_notifications.py"
    if not required_legacy.is_file():
        raise RuntimeError("Legacy watcher source unavailable; cannot launch safely")
    state = manager.status()
    active = state.get("active")
    if not active:
        return legacy_src, "LEGACY_NO_ACTIVE_V3"
    if state.get("incomplete_transaction"):
        # Crash recovery is performed before launching; never consume an
        # active pointer while a switch journal remains unresolved.
        raise RuntimeError("V3 activation journal is not resolved")
    try:
        base = manager._verify_version(active)
        return base / WORK_REL / "src", "V3_" + active
    except Exception:
        # Do not use a corrupted/unverified snapshot. Existing V2 source is
        # not overwritten by V3 and can continue monitoring during repair.
        return legacy_src, "LEGACY_SNAPSHOT_INVALID"


def run_watcher(manager=None, config=ORIGINAL_CONFIG, python=None,
                legacy_work=LEGACY_WORK, runner=subprocess.run):
    """Run one watcher cycle; retain original external SQLite/config path."""
    manager = manager or Manager(LOCAL)
    config = Path(config).resolve()
    if config != Path(ORIGINAL_CONFIG).resolve():
        raise ValueError("V3 watcher must use exact original monitor_config.json")
    if not config.is_file():
        raise FileNotFoundError("Original monitoring configuration not found")
    if manager.journal.exists():
        try:
            manager.recover()
        except Exception:
            # If a switch cannot be recovered, the previous checkout is
            # isolated from V3, so use it for this read-only watcher cycle.
            src = Path(legacy_work) / "src"
            state = "LEGACY_INCOMPLETE_SWITCH"
        else:
            src, state = select_runtime(manager, legacy_work)
    else:
        src, state = select_runtime(manager, legacy_work)
    if not (src / "meter_photo_qa" / "surveyor_notifications.py").is_file():
        raise RuntimeError("Selected watcher entrypoint unavailable")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    executable = str(python or sys.executable)
    result = runner(
        [executable, "-m", "meter_photo_qa.surveyor_notifications",
         "--config", str(config)],
        cwd=str(src.parent), env=env, timeout=240,
    )
    code = int(result.returncode)
    atomic_json(manager.local / "launcher_latest.json", {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": state,
        "status": "OK" if code == 0 else "WATCHER_RETURNED_ERROR",
        "exit_code": code,
        "config_location": "ORIGINAL_EXTERNAL",
    })
    return code


if __name__ == "__main__":
    raise SystemExit(run_watcher())

"""Persistent one-cycle REPORTAPP V3 launcher (runs from LOCALAPPDATA).

The launcher never depends on the Git checkout's maintenance Python modules.
An explicitly supplied original --config path retains the existing SQLite,
surveyor allowlist, and REG version. This file never changes Task Scheduler.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from v3_core import Manager, WORK_REL, atomic_json

PINNED_TAG = "reportapp-v3-v20261017-000032"


def run_once(*, config, legacy_src, local=None, python=None, runner=subprocess.run):
    root = Path(local) if local else Path(__file__).resolve().parent
    manager = Manager(root, python=python or sys.executable)
    config = Path(config).resolve()
    legacy_src = Path(legacy_src).resolve()
    if not config.is_file():
        raise RuntimeError("ORIGINAL_CONFIG_MISSING")
    if not (legacy_src / "meter_photo_qa" / "surveyor_notifications.py").is_file():
        raise RuntimeError("ORIGINAL_WATCHER_MISSING")
    state = manager.status()
    active = state.get("active")
    if state.get("incomplete_transaction"):
        raise RuntimeError("INCOMPLETE_V3_SWITCH")
    if active and active != PINNED_TAG:
        raise RuntimeError("UNAPPROVED_ACTIVE_RELEASE")
    if active:
        try:
            candidate = manager._verify_version(active)
            source = candidate / WORK_REL / "src"
            mode = "V3_VERIFIED"
        except Exception:
            # Hash validation failed: never execute questionable release bytes.
            source = legacy_src
            mode = "LEGACY_RELEASE_CORRUPT"
    else:
        source = legacy_src
        mode = "LEGACY_NO_ACTIVE_V3"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.time()
    status = "WATCHER_FAILED"
    exit_code = 99
    try:
        result = runner(
            [str(python or sys.executable), "-m",
             "meter_photo_qa.surveyor_notifications", "--config", str(config)],
            cwd=str(source.parent), env=env, timeout=240,
        )
        exit_code = int(result.returncode)
        status = "OK" if exit_code == 0 else "WATCHER_NONZERO_EXIT"
    except (OSError, subprocess.SubprocessError):
        status = "WATCHER_LAUNCH_ERROR"
    atomic_json(root / "launcher_latest.json", {
        "started_epoch_seconds": started,
        "finished_epoch_seconds": time.time(),
        "mode": mode,
        "status": status,
        "exit_code": exit_code,
        "config": "ORIGINAL_EXTERNAL",
        "source": "PINNED_IMMUTABLE" if mode == "V3_VERIFIED" else "ORIGINAL_LEGACY",
    })
    return exit_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--legacy-src", required=True)
    args = parser.parse_args()
    return run_once(config=args.config, legacy_src=args.legacy_src)


if __name__ == "__main__":
    raise SystemExit(main())

"""REPORTAPP local health and guarded, release-only updater.

No REG writes, account secrets, database migrations, or arbitrary git pull.
Automatic deployments are limited to explicitly published QA watcher and Inbox Python files.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "outputs" / "Customer_Meter_Photo_QA_Working"
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "REPORTAPP" / "Maintenance"
POLICY = LOCAL / "policy.json"
REPORT = LOCAL / "health_latest.json"
LAST_UPDATE = LOCAL / "last_deployment.json"
REPO = "iranzi17/REPORTAPP"
TAG_RE = re.compile(r"^reportapp-(?:safe|watcher)-v[0-9]{8}-[0-9]{3,9}$")
ASSET_NAME = "reportapp-safe-update.zip"
ALLOWED = frozenset({
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/notification_inbox.py",
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/surveyor_notifications.py",
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/surveyor_activity.py",
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/deferred_notifications.py",
    "outputs/Customer_Meter_Photo_QA_Working/tests/test_deferred_notifications.py",
    "maintenance/self_monitor.py",

})
CONFIG = WORK / "outputs" / "REPORTAPP_Surveyor_Notifications" / "monitor_config.json"
NAV = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "REPORTAPP" / "Navigation"
MAX_PACKAGE = 1_000_000
MAX_SOURCE = 300_000
# Exact names eligible to be created by a reviewed update release.
CREATE_ALLOWED = frozenset({
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/deferred_notifications.py",
    "outputs/Customer_Meter_Photo_QA_Working/tests/test_deferred_notifications.py",
})


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _task_health():
    if os.name != "nt":
        return "UNAVAILABLE", None
    command = (
        "$t=Get-ScheduledTask -TaskName 'REPORTAPP Surveyor Quality Alerts' "
        "-ErrorAction Stop; $i=$t | Get-ScheduledTaskInfo; "
        "[PSCustomObject]@{state=[string]$t.State;result=$i.LastTaskResult} "
        "| ConvertTo-Json -Compress"
    )
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            text=True, capture_output=True, timeout=20, check=True,
        )
        item = json.loads(p.stdout.strip())
        return str(item.get("state", "UNKNOWN")), item.get("result")
    except (OSError, subprocess.SubprocessError, ValueError):
        return "UNKNOWN", None


def _last_scan():
    file = CONFIG.with_suffix(".monitor.log")
    if not file.is_file():
        return None
    with file.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 32768))
        text = f.read().decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        match = re.match(r"^(\d{4}-\d\d-\d\dT\S+)\s+(\{.*\})\s*$", line)
        if not match:
            continue
        try:
            item = ast.literal_eval(match.group(2))
            if not isinstance(item, dict) or "records_scanned" not in item:
                continue
            timestamp = dt.datetime.fromisoformat(match.group(1))
            if timestamp.tzinfo is None:
                continue
            return timestamp, item
        except (ValueError, SyntaxError, TypeError):
            continue
    return None


def collect_health(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    state, last_result = _task_health()
    scan = _last_scan()
    issues = []
    if state == "Disabled":
        status = "PAUSED"
    elif state in ("Running", "Ready"):
        status = "HEALTHY"
    else:
        status = "DEGRADED"
        issues.append("WATCHER_TASK_NOT_READY")
    info = {
        "checked_utc": now.isoformat(),
        "status": status,
        "watcher_task_state": state,
        "task_last_result": last_result,
        "scan_age_minutes": None,
        "scanned_counts": {},
        "alerts_sent_last_scan": None,
        "delivery_failures_last_scan": None,
        "navigation_pending_count": 0,
        "issues": issues,
    }
    if scan is None:
        issues.append("NO_RECENT_SCAN_LOG")
    else:
        at, last = scan
        age = max(0, round((now - at).total_seconds() / 60, 1))
        info["scan_age_minutes"] = age
        counts = last.get("records_scanned") or {}
        info["scanned_counts"] = {
            k: int(counts.get(k, 0)) for k in ("pole", "line", "transformer")
            if isinstance(counts.get(k), int)
        }
        info["alerts_sent_last_scan"] = last.get("alerts_sent")
        info["delivery_failures_last_scan"] = last.get("alerts_delivery_failed")
        if status != "PAUSED" and age > 8:
            issues.append("WATCHER_SCAN_STALE")
        if (last.get("alerts_delivery_failed") or 0) > 0:
            issues.append("NOTIFICATION_DELIVERY_FAILURE")
    requests = NAV / "Requests"
    if requests.is_dir():
        info["navigation_pending_count"] = sum(1 for _ in requests.glob("*.json"))
        if info["navigation_pending_count"] > 20:
            issues.append("NAVIGATION_QUEUE_BACKLOG")
    if issues and status == "HEALTHY":
        status = "DEGRADED"
    info["status"] = status
    return info


def _load_policy():
    if not POLICY.exists():
        return {"auto_deploy": False}
    p = json.loads(POLICY.read_text(encoding="utf-8-sig"))
    return p if isinstance(p, dict) else {"auto_deploy": False}


def _load_approved_release(fetch_json):
    items = fetch_json(
        "https://api.github.com/repos/" + REPO + "/releases?per_page=30"
    )
    matches = [
        x for x in items
        if not x.get("draft") and not x.get("prerelease")
        and TAG_RE.fullmatch(str(x.get("tag_name", "")))
    ]
    if not matches:
        return None, None
    release = max(matches, key=lambda x: x.get("published_at") or "")
    assets = [a for a in release.get("assets", [])
              if a.get("name") == ASSET_NAME]
    if len(assets) != 1:
        raise ValueError("Approved release lacks exactly one safe-update package.")
    asset = assets[0]
    digest = str(asset.get("digest") or "")
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        raise ValueError("Release asset has no verifiable SHA256 digest.")
    return release, asset


def _read_json(url):
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "REPORTAPP-Safe-Update",
        }), timeout=20
    ) as r:
        return json.load(r)


def _download_asset(asset):
    url = str(asset["browser_download_url"])
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("Update download must originate from github.com.")
    if not parsed.path.startswith("/" + REPO + "/releases/download/"):
        raise ValueError("Unexpected release asset URL.")
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "REPORTAPP-Safe-Update"}),
        timeout=30
    ) as r:
        # GitHub's release CDN redirects to a githubusercontent.com host.
        final = urllib.parse.urlsplit(r.geturl())
        if final.scheme != "https" or final.hostname not in (
            "github.com", "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        ):
            raise ValueError("Unexpected release download redirect.")
        data = r.read(MAX_PACKAGE + 1)
    if len(data) > MAX_PACKAGE:
        raise ValueError("Update package exceeds size limit.")
    expected = str(asset["digest"]).split(":", 1)[1].lower()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("GitHub release SHA256 mismatch.")
    return data


def _validate_zip(data, tag):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = z.namelist()
        if len(entries) != len(set(entries)):
            raise ValueError("Duplicate file names in update archive.")
        if "manifest.json" not in entries:
            raise ValueError("Missing update manifest.")
        meta = json.loads(z.read("manifest.json"))
        if (not isinstance(meta, dict) or meta.get("format") != 1
                or meta.get("repository") != REPO or meta.get("tag") != tag):
            raise ValueError("Update package metadata mismatch.")
        hashes = meta.get("files")
        if (not isinstance(hashes, dict) or not hashes
                or not set(hashes).issubset(ALLOWED)
                or set(entries) != set(hashes) | {"manifest.json"}):
            raise ValueError("Update contains a forbidden or unexpected file.")
        payload = {}
        for path, expected in hashes.items():
            if z.getinfo(path).file_size > MAX_SOURCE:
                raise ValueError("Expanded file exceeds size limit.")
            content = z.read(path)
            if (len(content) > MAX_SOURCE
                    or not re.fullmatch(r"[0-9a-f]{64}", str(expected))
                    or hashlib.sha256(content).hexdigest() != expected):
                raise ValueError("Invalid file hash or oversized update.")
            if not path.endswith(".py"):
                raise ValueError("Updater permits Python UI source only.")
            compile(content, path, "exec")
            payload[path] = content
        return payload


def _smoke_test(python):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORK / "src")
    tests = WORK / "tests"
    for name in (
        "test_alert_navigation.py",
        "test_notification_inbox.py",
        "test_surveyor_notifications.py",
        "test_surveyor_activity.py",
        "test_deferred_notifications.py",
    ):
        result = subprocess.run(
            [str(python), "-m", "unittest", "discover",
             "-s", str(tests), "-p", name],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            timeout=120,
        )
        if result.returncode != 0:
            # Never expose raw test traces in exported health reports.
            raise RuntimeError("Post-install regression failed for " + name)


def apply_update(release, data, python=None):
    tag = str(release["tag_name"])
    payload = _validate_zip(data, tag)
    python = python or sys.executable
    backups = LOCAL / "backups" / tag
    backups.mkdir(parents=True, exist_ok=False)
    replaced = []
    try:
        for rel, content in payload.items():
            target = (ROOT / rel).resolve()
            if target.parent.is_symlink() or target.is_symlink():
                raise ValueError("Symlinked update target not allowed.")
            if ROOT.resolve() not in target.parents or (
                not target.is_file() and rel not in CREATE_ALLOWED
            ):
                raise ValueError("Target is missing or outside REPORTAPP.")
            if not target.parent.is_dir():
                raise ValueError("Update parent directory is missing.")
            prior = target.read_bytes() if target.is_file() else None
            backup = backups / Path(rel).name
            if prior is not None:
                backup.write_bytes(prior)
            staging = target.with_name(target.name + ".reportapp-new")
            try:
                with staging.open("xb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(staging, target)
            finally:
                staging.unlink(missing_ok=True)
            replaced.append((target, prior))
        _smoke_test(python)
    except Exception:
        for target, prior in reversed(replaced):
            rollback = target.with_name(target.name + ".reportapp-rollback")
            try:
                if prior is None:
                    target.unlink(missing_ok=True)
                else:
                    rollback.write_bytes(prior)
                    os.replace(rollback, target)
            finally:
                rollback.unlink(missing_ok=True)
        # Retain backups for diagnostics and manual inspection.
        raise
    receipt = {
        "tag": tag,
        "installed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_files": sorted(payload),
        "backup_folder": str(backups),
        "status": "DEPLOYED_TESTED",
    }
    write_json(LAST_UPDATE, receipt)
    return receipt


def report_health_issue(health, *, now=None):
    """Optional GitHub issue upload: ONLY a sanitized issue-code summary.

    Uses an explicitly authenticated GitHub CLI; never sends raw logs,
    record IDs, usernames, service URLs, credentials, or feature attributes.
    """
    if health.get("status") == "PAUSED":
        return "WATCHER_PAUSED"
    codes = sorted(set(health.get("issues") or []))
    if not codes:
        return "NO_NEW_ISSUE"
    executable = shutil.which("gh")
    if not executable:
        return "GH_CLI_NOT_INSTALLED"
    now = now or dt.datetime.now(dt.timezone.utc)
    fingerprint = hashlib.sha256("|".join(codes).encode()).hexdigest()
    path = LOCAL / "github_issue_state.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        if prev.get("fingerprint") == fingerprint:
            try:
                sent = dt.datetime.fromisoformat(prev["reported_at"])
                if now - sent < dt.timedelta(hours=12):
                    return "ALREADY_REPORTED"
            except (KeyError, ValueError, TypeError):
                pass
    body = (
        "Automated sanitized REPORTAPP health report. No REG content included.\n\n"
        "Issue codes: " + ", ".join(codes) + "\n"
        "Watcher task state: " + str(health.get("watcher_task_state")) + "\n"
        "Latest scan age (minutes): " + str(health.get("scan_age_minutes")) + "\n"
        "Delivery failures in latest scan: "
        + str(health.get("delivery_failures_last_scan")) + "\n"
        "Manual diagnosis required before any watcher or service change."
    )
    result = subprocess.run(
        [executable, "issue", "create", "--repo", REPO,
         "--title", "[REPORTAPP HEALTH] " + ", ".join(codes),
         "--body", body],
        text=True, capture_output=True, timeout=45,
    )
    if result.returncode:
        return "GH_ISSUE_REPORT_FAILED"
    write_json(path, {"fingerprint": fingerprint, "reported_at": now.isoformat()})
    return "GH_ISSUE_CREATED"


def cycle(fetch_json=_read_json, download=_download_asset):
    health = collect_health()
    write_json(REPORT, health)
    outcome = {"health": health, "deployment": "DISABLED"}
    policy = _load_policy()
    if policy.get("github_issue_reporting") is True:
        try:
            outcome["github_reporting"] = report_health_issue(health)
        except Exception as exc:
            outcome["github_reporting"] = "FAILED_" + type(exc).__name__
    if policy.get("auto_deploy") is not True:
        return outcome
    try:
        release, asset = _load_approved_release(fetch_json)
        if release is None:
            outcome["deployment"] = "NO_APPROVED_RELEASE"
            return outcome
        tag = release["tag_name"]
        if LAST_UPDATE.exists():
            previous = json.loads(LAST_UPDATE.read_text(encoding="utf-8"))
            if previous.get("tag") == tag and previous.get("status") == "DEPLOYED_TESTED":
                outcome["deployment"] = "UP_TO_DATE"
                return outcome
        # Failed releases require manual review; never retry unattended.
        if (LOCAL / "blocked_releases" / tag).exists():
            outcome["deployment"] = "BLOCKED_AFTER_FAILURE"
            return outcome
        data = download(asset)
        try:
            outcome["receipt"] = apply_update(release, data)
            outcome["deployment"] = "DEPLOYED_TESTED"
        except Exception as exc:
            (LOCAL / "blocked_releases").mkdir(parents=True, exist_ok=True)
            write_json(LOCAL / "blocked_releases" / tag,
                       {"tag": tag, "reason": type(exc).__name__})
            raise
    except Exception as exc:
        outcome["deployment"] = "FAILED_SAFE"
        outcome["deployment_error_type"] = type(exc).__name__
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle", action="store_true",
                        help="Collect local health and check approved releases")
    parser.add_argument("--status", action="store_true",
                        help="Read-only current health report")
    opts = parser.parse_args(argv)
    if opts.cycle:
        outcome = cycle()
        write_json(LOCAL / "cycle_latest.json", outcome)
        if sys.stdout is not None:
            print(json.dumps(outcome, indent=2))
    else:
        report = collect_health()
        if sys.stdout is not None:
            print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""REPORTAPP Self-Maintenance V3: isolated, immutable, explicitly approved rollout.

This module NEVER changes the developer checkout, Scheduled Tasks, ArcGIS Pro
add-ins, REG GIS data, monitor configuration, SQLite, or generated reports.
A separate explicitly approved launcher cutover is needed before active.json
is consumed by the office watcher.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import uuid
import zipfile

REPO = "iranzi17/REPORTAPP"
AGENT_VERSION = "3.0.0"
WORK_REL = "outputs/Customer_Meter_Photo_QA_Working"
TAG_PATTERN = re.compile(r"reportapp-v3-v[0-9]{8}-[0-9]{3,9}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_FILES = {
    f"{WORK_REL}/src/meter_photo_qa/__init__.py",
    f"{WORK_REL}/src/meter_photo_qa/surveyor_notifications.py",
    f"{WORK_REL}/src/meter_photo_qa/notification_inbox.py",
    f"{WORK_REL}/src/meter_photo_qa/alert_navigation.py",
    f"{WORK_REL}/tests/test_surveyor_notifications.py",
    f"{WORK_REL}/tests/test_notification_inbox.py",
    f"{WORK_REL}/tests/test_alert_navigation.py",
}
REQUIRED_TESTS = (
    "test_surveyor_notifications.py",
    "test_notification_inbox.py",
    "test_alert_navigation.py",
    "test_surveyor_activity.py",
    "test_deferred_notifications.py",
)
MAX_ARCHIVE = 15_000_000
MAX_UNPACKED = 30_000_000
MAX_ENTRY = 3_000_000


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_name(tag):
    if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
        raise ValueError("Invalid V3 release ID")
    return tag


def safe_path(name):
    """Restrict deployment to audited application source/tests and static config."""
    if not isinstance(name, str) or "\\" in name or ":" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    if str(path) != name or path.is_absolute() or ".." in path.parts or "." in path.parts:
        return False
    prefix = WORK_REL + "/"
    if not name.startswith(prefix):
        return False
    rel = name[len(prefix):]
    if rel.startswith("src/meter_photo_qa/") and rel.endswith(".py"):
        return True
    if rel.startswith("tests/test_") and rel.endswith(".py") and "/" not in rel[len("tests/"):]:
        return True
    return rel in {
        "config/lv_line_quality_rules.json",
        "config/rwanda_district_sectors.json",
    }


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_archive(data, expected_hash, tag):
    """Pin archive SHA256 out-of-band; reject traversals, links, ZIP bombs, omissions."""
    tag = safe_name(tag)
    if not isinstance(data, bytes) or len(data) > MAX_ARCHIVE:
        raise ValueError("Invalid or oversized archive")
    if not isinstance(expected_hash, str) or not SHA_PATTERN.fullmatch(expected_hash):
        raise ValueError("Expected release SHA256 is not pinned")
    if digest(data) != expected_hash:
        raise ValueError("Approved archive SHA256 does not match")
    payload = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [part.filename for part in entries]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("Missing manifest or duplicate ZIP paths")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict):
            raise ValueError("Invalid release manifest")
        if (manifest.get("format") != 3 or manifest.get("repository") != REPO
                or manifest.get("tag") != tag
                or manifest.get("min_agent_version") != AGENT_VERSION
                or manifest.get("arcgis_pro") != "3.4"
                or manifest.get("python") != "3.11"):
            raise ValueError("Release compatibility or identity mismatch")
        files = manifest.get("files")
        tests = manifest.get("required_tests")
        if (not isinstance(files, dict) or not REQUIRED_FILES.issubset(files)
                or set(names) != set(files) | {"manifest.json"}
                or tests != list(REQUIRED_TESTS)
                or not all(safe_path(name) for name in files)):
            raise ValueError("Missing mandatory code/tests or unexpected release file")
        for part in entries:
            if part.filename == "manifest.json":
                if part.file_size > 64_000:
                    raise ValueError("Manifest exceeds limit")
                continue
            mode = part.external_attr >> 16
            if part.is_dir() or (mode & 0o170000) == 0o120000:
                raise ValueError("Release must contain only regular files")
            if part.file_size > MAX_ENTRY:
                raise ValueError("Oversized release file")
            if not isinstance(files[part.filename], str) or not SHA_PATTERN.fullmatch(files[part.filename]):
                raise ValueError("Invalid manifest file digest")
            content = archive.read(part.filename)
            if digest(content) != files[part.filename]:
                raise ValueError("Release file SHA256 mismatch")
            if part.filename.endswith(".py"):
                compile(content, part.filename, "exec")
            payload[part.filename] = content
        if sum(map(len, payload.values())) > MAX_UNPACKED:
            raise ValueError("Expanded release exceeds safety limit")
    return manifest, payload


def _clean_message(error):
    """Keep safe local reason codes; never persist arbitrary HTTP responses or tokens."""
    detail = str(error).splitlines()[0][:350]
    detail = re.sub(r"https?://\S+", "<url>", detail, flags=re.I)
    detail = re.sub(r"[A-Fa-f0-9]{8}-[A-Fa-f0-9-]{20,}", "<id>", detail)
    detail = re.sub(r"[A-Za-z]:\\[^ ]+", "<local-path>", detail)
    detail = re.sub(r"(?i)(token|password|secret|authorization)\s*[:=]\s*\S+",
                    r"\1=<redacted>", detail)
    return detail


class ReleaseError(RuntimeError):
    def __init__(self, stage, code, detail=""):
        super().__init__(detail or code)
        self.stage, self.code = stage, code


class Manager:
    def __init__(self, local, python=None):
        self.local = Path(local).resolve()
        self.python = str(python or sys.executable)
        self.versions = self.local / "versions"
        self.active = self.local / "active.json"
        self.journal = self.local / "transaction.json"
        self.policy = self.local / "v3_policy.json"

    @contextmanager
    def locked(self):
        self.local.mkdir(parents=True, exist_ok=True)
        with (self.local / "v3.lock").open("a+b") as lock:
            lock.seek(0)
            lock.write(b"1")
            lock.flush()
            if os.name == "nt":
                import msvcrt
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise ReleaseError("LOCK", "BUSY", "Another V3 deployment is running") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise ReleaseError("LOCK", "BUSY", "Another V3 deployment is running") from exc
            try:
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _failure(self, tag, stage, code, detail, rollback="NOT_NEEDED"):
        report = {"tag": tag, "at_utc": utc_now(), "stage": stage,
                  "code": code, "details": _clean_message(detail),
                  "rollback": rollback}
        atomic_json(self.local / "diagnostics" / (tag + ".json"), report)
        atomic_json(self.local / "blocked_releases" / tag, report)
        return report

    def _policy_for(self, tag, archive_hash):
        p = read_json(self.policy, {})
        if (not isinstance(p, dict) or p.get("enabled") is not True
                or p.get("approved_tag") != tag
                or p.get("approved_sha256") != archive_hash
                or p.get("repository") != REPO):
            raise ReleaseError("APPROVAL", "NOT_APPROVED",
                               "Operator-approved tag and exact SHA256 are required")
        return p

    def _verify_version(self, tag):
        base = self.versions / safe_name(tag)
        manifest = read_json(base / "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("tag") != tag:
            raise ReleaseError("CHECK", "MISSING_VERSION", "Versioned snapshot missing")
        hashes = manifest.get("files", {})
        if not REQUIRED_FILES.issubset(hashes):
            raise ReleaseError("CHECK", "INCOMPLETE_VERSION")
        for rel, expected in hashes.items():
            if not safe_path(rel):
                raise ReleaseError("CHECK", "UNSAFE_FILE")
            path = base / rel
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
                raise ReleaseError("CHECK", "CORRUPT_VERSION", "Snapshot file hash mismatch")
        return base

    def _run_tests(self, candidate, tests=REQUIRED_TESTS):
        src = candidate / WORK_REL / "src"
        tests_dir = candidate / WORK_REL / "tests"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(src) + os.pathsep + str(candidate)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        results = {}
        for name in tests:
            if not (tests_dir / name).is_file():
                raise ReleaseError("STAGING_TESTS", "TEST_MISSING", name)
            try:
                result = subprocess.run(
                    [self.python, "-m", "unittest", "discover",
                     "-s", str(tests_dir), "-p", name, "-v"],
                    cwd=str(candidate), env=env, capture_output=True, text=True,
                    timeout=180,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ReleaseError("STAGING_TESTS", "TEST_RUNTIME", name) from exc
            lines = result.stderr or result.stdout
            count = re.search(r"Ran (\d+) tests?\b", lines)
            n = int(count.group(1)) if count else 0
            if result.returncode or n < 1:
                markers = ("FAIL:", "ERROR:", "ModuleNotFoundError:",
                           "ImportError:", "FileNotFoundError:",
                           "AssertionError:", "RuntimeError:")
                failures = [line.strip() for line in lines.splitlines()
                            if any(mark in line for mark in markers)]
                exceptions = [line.strip() for line in lines.splitlines()
                              if re.match(r"^(AssertionError|KeyError|FileNotFoundError|RuntimeError|ModuleNotFoundError|PermissionError|OSError|ImportError|ValueError):", line.strip())]
                detail = "; ".join(exceptions[-1:] + failures[:1])
                reason = _clean_message(detail) if detail else "No test failure detail"
                raise ReleaseError("STAGING_TESTS", "TEST_FAILED",
                                   f"{name}: {n} tests, exit {result.returncode}; {reason}")
            results[name] = n
        return results

    def stage(self, tag, archive_bytes, pinned_sha256):
        """No live code or pointer changes. Tests run against isolated candidate."""
        tag = safe_name(tag)
        with self.locked():
            self._policy_for(tag, pinned_sha256)
            if (self.local / "blocked_releases" / tag).exists():
                raise ReleaseError("APPROVAL", "RELEASE_BLOCKED", "Use a superseding approved release")
            candidate = self.versions / ("." + tag + "-" + uuid.uuid4().hex)
            self.versions.mkdir(parents=True, exist_ok=True)
            if (self.versions / tag).exists():
                raise ReleaseError("STAGING", "ALREADY_STAGED")
            stage = "ARCHIVE"
            try:
                manifest, files = validate_archive(archive_bytes, pinned_sha256, tag)
                stage = "EXTRACT"
                candidate.mkdir()
                for rel, content in files.items():
                    target = candidate / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                atomic_json(candidate / "manifest.json", manifest)
                stage = "STAGING_TESTS"
                tests = self._run_tests(candidate)
                stage = "SEAL"
                os.replace(candidate, self.versions / tag)
                receipt = {"tag": tag, "status": "STAGED_TESTED", "at_utc": utc_now(),
                           "archive_sha256": pinned_sha256, "tests": tests}
                atomic_json(self.local / "receipts" / (tag + ".json"), receipt)
                return receipt
            except Exception as exc:
                self._failure(tag, stage, getattr(exc, "code", type(exc).__name__), exc)
                raise
            finally:
                if candidate.exists():
                    shutil.rmtree(candidate)

    def _precheck(self, tag, policy):
        if policy.get("office_cutover_approved") is not True:
            raise ReleaseError("ACTIVATION", "CUTOVER_NOT_APPROVED",
                               "Pilot staging cannot activate an office watcher")
        if policy.get("bridge_version_confirmed") != "1.0.4":
            raise ReleaseError("ACTIVATION", "BRIDGE_UNVERIFIED",
                               "Verify installed ArcGIS Pro navigation bridge 1.0.4")
        if policy.get("runtime_python_confirmed") != self.python:
            raise ReleaseError("ACTIVATION", "PYTHON_UNVERIFIED",
                               "Verify this exact ArcGIS Pro Python executable")
        if sys.version_info[:2] != (3, 11):
            # Agent runs under ArcGIS Pro Python; do not compare only a manifest claim.
            raise ReleaseError("ACTIVATION", "PYTHON_VERSION", "ArcGIS Pro Python 3.11 required")
        try:
            import arcpy
            version = str(arcpy.GetInstallInfo().get("Version", ""))
            if not version.startswith("3.4"):
                raise ValueError("ArcGIS Pro is not 3.4")
        except (ImportError, ValueError, KeyError, AttributeError) as exc:
            raise ReleaseError("ACTIVATION", "ARCGIS_UNVERIFIED",
                               "ArcGIS Pro 3.4 runtime cannot be confirmed") from exc

    def _probe(self, tag):
        base = self.versions / tag
        src = base / WORK_REL / "src"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(src) + os.pathsep + str(base)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        run = subprocess.run(
            [self.python, "-c",
             "from meter_photo_qa.surveyor_notifications import event_timestamp; assert callable(event_timestamp)"],
            cwd=str(base), env=env, capture_output=True, text=True, timeout=45,
        )
        if run.returncode:
            raise ReleaseError("POSTCHECK", "IMPORT_PROBE_FAILED",
                               "Installed watcher import probe failed")

    def activate(self, tag):
        """Switch ONLY the V3 active pointer; existing scheduled watcher untouched."""
        tag = safe_name(tag)
        with self.locked():
            receipt = read_json(self.local / "receipts" / (tag + ".json"), {})
            if receipt.get("status") != "STAGED_TESTED":
                raise ReleaseError("ACTIVATION", "NOT_TESTED")
            self._verify_version(tag)
            policy = self._policy_for(tag, receipt.get("archive_sha256"))
            self._precheck(tag, policy)
            before = read_json(self.active, {})
            previous = before.get("tag")
            if previous:
                self._verify_version(previous)
            atomic_json(self.journal, {"state": "SWITCHING", "tag": tag,
                                       "previous": previous, "at_utc": utc_now()})
            switched = False
            try:
                atomic_json(self.active, {"tag": tag, "activated_utc": utc_now()})
                switched = True
                self._probe(tag)
                atomic_json(self.local / "last_deployment.json",
                            {"tag": tag, "previous": previous, "status": "ACTIVATED",
                             "at_utc": utc_now()})
                self.journal.unlink(missing_ok=True)
                return {"tag": tag, "status": "ACTIVATED", "previous": previous}
            except Exception as exc:
                rollback = "NOT_NEEDED"
                if switched:
                    try:
                        if previous:
                            atomic_json(self.active, before)
                            self._verify_version(previous)
                        else:
                            self.active.unlink(missing_ok=True)
                        rollback = "RESTORED_PREVIOUS"
                    except Exception:
                        rollback = "ROLLBACK_FAILED"
                self._failure(tag, "POSTCHECK", getattr(exc, "code", type(exc).__name__),
                              exc, rollback)
                self.journal.unlink(missing_ok=True) if rollback != "ROLLBACK_FAILED" else None
                raise

    def recover(self):
        """Crash recovery refuses to replay a half-completed activation."""
        with self.locked():
            txn = read_json(self.journal)
            if not txn:
                return {"status": "CLEAN"}
            if txn.get("state") != "SWITCHING":
                raise ReleaseError("RECOVERY", "INVALID_JOURNAL")
            tag = safe_name(txn.get("tag"))
            previous = txn.get("previous")
            if previous:
                self._verify_version(previous)
                atomic_json(self.active, {"tag": previous, "recovered_utc": utc_now()})
            else:
                self.active.unlink(missing_ok=True)
            self._failure(tag, "RECOVERY", "INTERRUPTED_ACTIVATION",
                          "Prior activation interrupted; old version restored",
                          "RESTORED_PREVIOUS")
            self.journal.unlink(missing_ok=True)
            return {"status": "RESTORED_PREVIOUS", "tag": previous}

    def rollback(self):
        with self.locked():
            if self.journal.exists():
                raise ReleaseError("ROLLBACK", "RECOVER_FIRST")
            prior = read_json(self.local / "last_deployment.json", {})
            previous = prior.get("previous")
            if not previous:
                raise ReleaseError("ROLLBACK", "NO_KNOWN_GOOD")
            self._verify_version(previous)
            active = read_json(self.active, {})
            atomic_json(self.active, {"tag": previous, "rolled_back_utc": utc_now()})
            atomic_json(self.local / "rollback_latest.json",
                        {"from": active.get("tag"), "to": previous,
                         "at_utc": utc_now(), "status": "RESTORED"})
            return {"status": "RESTORED", "tag": previous}

    def status(self):
        active = read_json(self.active, {})
        latest = read_json(self.local / "last_deployment.json", {})
        blocked = sorted(p.name for p in (self.local / "blocked_releases").glob("*")) if (
            self.local / "blocked_releases").exists() else []
        return {"agent_version": AGENT_VERSION, "active": active.get("tag"),
                "latest_deployment": latest.get("status"), "blocked": blocked,
                "incomplete_transaction": self.journal.exists(),
                "legacy_watcher_unchanged": True}

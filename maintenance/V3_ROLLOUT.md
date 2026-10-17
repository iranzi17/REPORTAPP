# REPORTAPP Self-Maintenance V3 — guarded pilot

**Status: DEVELOPMENT ONLY.** V3 does not deploy from main, update office code,
reconfigure Windows Task Scheduler, or install an ArcGIS Pro add-in.

## Findings from the V2 audit

- V2 replaces files in the tracked Git checkout before local regression tests.
- The V2 package contains only a subset of the tests run by the office agent.
- Installation failures are reduced to a class name; diagnosis is inadequate.
- The release builder and update allowlist are independent and easy to desynchronize.
- A CI-green release is not equivalent to an approved, office-compatible installation.
- Python navigation components and the compiled ArcGIS Pro bridge are independently versioned.

## V3 pilot guarantees

1. A release ZIP has a V3 manifest with exact SHA256 for every file, Python 3.11,
   ArcGIS Pro 3.4, required bridge 1.0.4, and required regression test names.
2. The archive SHA256 **must be pinned out of band** in local `v3_policy.json`.
   A GitHub Actions success or a matching release tag by itself is insufficient.
3. The builder creates a **complete controlled source/test snapshot**, including
   mandatory watcher, Inbox, URI handler, and regression tests. No user output
   folders, watched-surveyor configuration, SQLite database, add-ins, or Excel
   exports are packaged.
4. V3 installs into `%LOCALAPPDATA%\\REPORTAPP\\Maintenance\\v3\\versions\\<tag>`,
   runs required unittest suites **before activation**, rejects zero tests, and
   keeps deployed source independent of the Git working tree.
5. Activation changes only an atomic `active.json` pointer; the existing watcher
   task is NOT changed. An activation journal enables recovery of incomplete
   switches. Failed postchecks restore the previous snapshot and block only the
   failed release, never every future version.
6. Structured local diagnostics include release, failure stage, code, sanitized
   reason, and rollback result. No raw REG service responses or credentials are
   uploaded by V3.

## Explicit remaining integration gates

- Test the complete candidate under **the actual office ArcGIS Pro 3.4 Python**
  and all default configuration paths, not solely in GitHub CI.
- The pilot now includes `maintenance/v3_launcher.py`, which resolves a
  verified active pointer and passes the **original external** monitor config,
  falling back to the unchanged legacy watcher on missing/invalid snapshots.
  **Office acceptance** must still prove correct imports, configuration paths,
  one-minute scheduling and live monitoring continuity before task cutover.
- Validate one-hour continuous watcher polling, alert deduplication, deferred
  notifications, output integrity and navigation against the existing office
  environment without editing REG data.
- Confirm a real bridge 1.0.4 installation and matching Python URI handler.
- Only then, with explicit operator approval, schedule a controlled cutover of
  **REPORTAPP Surveyor Quality Alerts**. Keep the old task definition and old
  source unchanged for immediate rollback. Never change the existing task
  automatically on the basis of GitHub CI.
- Define and enforce a protected GitHub release approval mechanism before
  implementing fully unattended fetch/install of newly published packages.
- Before activating KMZ PR #12, validate Excel+KMZ results in Pro 3.4 using
  authoritative read-only REG feature service geometry.

## Acceptance evidence

Run `python -m unittest discover -s maintenance/tests -v` in CI. Additionally
simulate tampering, path traversal, missing/zero tests, postcheck exceptions,
interrupted switch and a newer approved release following a blocked old one.
Document office acceptance before any production cutover.

## Office receipt diagnosis (17 October 2026)

The latest office receipts show **HEALTHY monitoring** (Ready, task result 0,
30-second scan freshness, no delivery failures) but V2 maintenance
`BLOCKED_AFTER_FAILURE`. The only confirmed installed release remains
`reportapp-safe-v20261016-002` and its one changed component is
`notification_inbox.py`. The records do **not** show the exception of the
blocked watcher release or prove bridge 1.0.4 is installed.

`maintenance/v3_office_diagnostics.py` now reports sanitized, read-only V2
release and blocked-marker status. The dashboard can show this and save a
shareable minimized JSON (no raw paths, usernames, GIS data, tokens or log
tracebacks). The office must supply the original marker under
`%LOCALAPPDATA%\\REPORTAPP\\Maintenance\\blocked_releases` to identify its
actual reason. A generic `RuntimeError` is **not a root-cause diagnosis**.

## Office isolated compatibility diagnostic — 17 October 2026

The office diagnostic ran with Windows and Python **3.11.10**. It reports
**66 passed tests across six suites**: navigation 10, Inbox 9, surveyor
notifications 22, surveyor activity 10, deferred notifications 11, and
combined QA 4. The office watcher health snapshot was healthy. No direct
GIS edits, local Git writes, automatic retries or deployments were reported.

However, the office's `test_gap_kmz.py` is **missing**. V2 may silently
consider `unittest discover -p test_gap_kmz.py` successful when it discovers
zero tests; absence **does not prove the KMZ updater failure**.
V3 now always requires and runs combined QA tests. When a V3 package
contains the `gap_kmz.py` source module, the corresponding
`test_gap_kmz.py` must be bundled and executed; the builder rejects a
source/test mismatch. Missing or zero-test suites are fatal during staging.

The office's navigation regression suite ran **10 tests**, but GitHub
`main` contains **15 navigation test functions** as of this audit.
This is evidence of a local-versus-repository test-suite difference, not
proof that the installed ArcGIS Pro add-in has any particular version.
Do not trust a green local historical test run to validate an updated
navigation bridge until the exact source and installed add-in are verified.

All five V2 blocked release markers contain only `RuntimeError`; the exact
historical failing command cannot be recovered from those files.
The Office diagnostic uses a shadow copy of current local sources, not a
reproduction of each 2026-10-16 historical release payload. A successful
shadow run does not retroactively establish whether any historical
post-update regression passed or failed.

## Operator dashboard

`maintenance/v3_dashboard.py` is a Tkinter-only, opt-in pilot interface. It
shows current V2 watcher health and V3 state, lets the operator select a
reviewed ZIP, **type an independently approved tag and SHA256**, stage it in
isolation, inspect diagnostic failure codes, recover an interrupted pointer and
restore a previous V3 snapshot. Staging and pointer rollback never change the
Windows watcher task. Do not click through checksum approval without an
independent protected release record.

## Controlled next phase

Build an office-specific, one-click **cutover assistant** only after the new
launcher passes a noncritical office acceptance test. Save the existing
Scheduled Task definition and preserve an immediate, operator-triggered
revert. The migration must be transactional; the current implementation
**does not yet reconfigure the Scheduled Task**.

**No release is authorized by this draft.** V2 continues operating unchanged.

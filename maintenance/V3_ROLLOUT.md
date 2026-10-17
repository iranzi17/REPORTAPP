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
- Add and test a stable V3 watcher launcher that reads the active pointer while
  passing the **original external** monitor_config path. Prove all relative
  imports/config files resolve correctly from a versioned snapshot.
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

**No release is authorized by this draft.** V2 continues operating unchanged.

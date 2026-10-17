## Office isolated acceptance — PASS, 17 October 2026

The corrected Windows office V2 shadow-pilot report
`office_v3_pilot_20261017_141752_4c022ed7.json` confirms that the
**unchanged** candidate `reportapp-v3-v20261017-000032` passed **71/71
required regression tests** in six suites (22 watcher, 9 Inbox, 15
navigation, 10 activity, 11 deferred, 4 QA reports) under
**ArcGIS Pro 3.4 / Python 3.11.10**. Three-component compatibility passed.
Full candidate checksum
`1dac15a37682c79f11508aaea80c344a50dfdb08d7dfede7a19b2ed7575cd948`
and 83 manifest files were verified. The diagnostic reports **no issues**
and `PASSED_IN_ISOLATION`; no live repo, Windows Task Scheduler, REG
source or running add-in was modified. The installed ArcGIS Pro Bridge
**remains 1.0.3**.

This is NOT production cutover acceptance: scheduled task command,
registerd Windows URL protocol target, rollback backup ability, process
safety, ArcGIS map version, and live polling still require a separate
supervisor-approved acceptance stage. The read-only pre-cutover office
inventory should collect a sanitized report of the exact existing
scheduled-task action/trigger, current URI handler status and V2 health
before a task-change script is authored. Keep existing watcher active
and Map Zoom paused.

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

## ArcGIS Pro Add-In Manager verified state (17 October 2026)

The office screenshot shows **REPORTAPP Alert Zoom Bridge 1.0.3**
in **Project → Add-In Manager**, targeting ArcGIS Pro 3.4.
This is direct evidence that the running office's navigation bridge has **NOT**
yet been upgraded to 1.0.4. Source-event verification is not assured by 1.0.3.
The screenshot does not confirm the Python `alert_navigation.py` handler
revision, nor that the map uses the same REG geodatabase version as the
watcher.

The office isolated compatibility report contains SHA256 hashes for the
currently installed Python modules. Comparing those hashes with current
GitHub `main` showed **nonmatching files** for `alert_navigation.py`,
`notification_inbox.py`, and `surveyor_notifications.py`, including
checks with LF/CRLF line ending normalization. Combined with the office
10-versus-main 15 navigation-test difference, this establishes Python
component drift. The exact content differences still require a reviewed
file diff; mismatched hashes alone do not identify which code path differs.
**Do not upgrade the bridge alone** while this drift remains.


The V3 activation precheck now calls `v3_bridge_audit.scan_installed_bridge()`
and validates the exact installed Esri package path, `Config.daml`
AddInInfo ID/version, and SHA256 pinned to GitHub's published
`reportapp-bridge-v1.0.4` release
(`66e3688ba7bde34caf210108d3a73225dee7abb8cd39b4e14bd64b6892963a39`).
A policy flag claiming Bridge 1.0.4 without matching installed bytes **cannot
authorize activation**. Even matching bytes cannot prove the loaded ArcGIS
Pro process has restarted; a separate user-confirmed restart and Add-In
Manager version check remain mandatory.

Safe office order: pause map zoom in the Inbox; ensure the verified
Python navigation URI handler and Inbox code are updated as a compatible
set; save/close ArcGIS Pro; install the explicitly published 1.0.4
`.esriAddInX` using Esri's installer; reopen Pro and check the displayed
version; inspect the same trusted REG `sde.DEFAULT` map version;
test a newly verified alert in a noncritical project. Do **not** silently
replace the installed add-in through V3 or change a Windows Scheduled Task
during this manual bridge upgrade.

## Office V3 package acceptance — first run failed safely

On **17 October 2026 at 14:05 UTC**, the ArcGIS Pro 3.4 office pilot
reported `FAILED_SAFE` against the reviewed 83-file release
`reportapp-v3-v20261017-000032`. Python **3.11.10**, ArcGIS Pro
**3.4**, and candidate archive SHA256
`1dac15a37682c79f11508aaea80c344a50dfdb08d7dfede7a19b2ed7575cd948`
were confirmed. Bridge remained **1.0.3**. Five suites had import/discovery
failure (`ImportError`, `TypeError`; only one unittest loader case seen),
and Inbox had two `TypeError` failures. **Zero live installations or GIS
updates occurred.**

The V1 standalone office diagnostic modified `subprocess.Popen` **itself**
into a function in its shadow-test guard. That breaks applications and
dependencies which introspect or type-check the Python class. This is a
plausible shared cause of the office failures; the generic exception-only
report cannot prove causation for all six suites. Do not mislabel this as six
separate application regressions.

The offline V2 diagnostic preserves the `Popen` class and blocks its
`__init__` method instead, retaining Python-level network/process safety
checks. It uses the **identical byte-for-byte pinned application candidate**,
not a newer release. In a local simulation (non-ArcGIS Python 3.13),
71 regression tests and the source-event compatibility probe passed. Its
process/network guard was also checked. **Office Python 3.11 rerun remains
required**; no production promotion until the corrected office diagnostics
confirm complete test discovery and passing regressions.

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

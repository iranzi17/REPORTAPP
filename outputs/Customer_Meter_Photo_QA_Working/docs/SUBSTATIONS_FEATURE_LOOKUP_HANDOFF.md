# Working-session handoff: exact ArcGIS feature lookup
Date: 17 October 2026

## Source and scope
The useful Substations Data Assistant pattern is an exact GlobalID lookup
which rejects zero/multiple results and re-verifies the selected feature.

Source: https://github.com/iranzi17/Substations-Data-Assistant/blob/main/arcgis_client.py

Staged in REPORTAPP:
- src/meter_photo_qa/exact_feature_lookup.py
- tests/test_exact_feature_lookup.py

The exact feature lookup remains read-only. It is now connected to the
desktop **QA-gap** and **clean-surveyor-activity** toast link builders via
`source_event_navigation.py`. A click action is produced ONLY after a
second independent service query confirms GlobalID, OBJECTID, source editor,
source event timestamp and `sde.DEFAULT`; there is no latest-by-creator
fallback. Service errors preserve the QA popup **without** a clickable
zoom action. The Windows ArcGIS Pro Bridge remains authoritative at click
time and repeats source checks before selection. **These changes are in
draft PR #17 only; the installed office V3 does not yet contain them.**
KMZ processing remains separate in PR #12.

## Why not copy the whole old application?
Substations Data Assistant searches recently CREATED items sorted by
created_date and takes the first 50; it is not a safe foundation for
recently EDITED older network assets. REPORTAPP already implements source
event timestamp, creator/editor selection, GlobalID, sde.DEFAULT version
checking and the ArcGIS Pro SDK bridge. The safe part to reuse is
GlobalID-first exact re-fetch with explicit identity and event checks.

## Existing work MUST be respected
- Separate ongoing KMZ feature: REPORTAPP PR #12
  https://github.com/iranzi17/REPORTAPP/pull/12
- Production main already has Python notifications and an SDK bridge
  (alert_navigation.py, surveyor_notifications.py, BridgeModule.cs).
  Do not replace or weaken their fail-closed checks.
- The office PC local REPORTAPP tree may have unsaved ArcGIS-generated
  files and uncommitted changes. GitHub Auto Sync has been disabled
  due to collisions. No force reset, clean, or blind pull.
- Preserve the emergency Pause Map Zoom control. No automatic retry of
  old navigation requests, and no map selection change on failed checks.

## Next working session, in order
1. Inspect this PR's helper and tests and run:
   PYTHONPATH=src python -m unittest discover -s tests -p 'test_exact_feature_lookup.py'
   from outputs/Customer_Meter_Photo_QA_Working.
2. Review monitor collection-to-toast flow and SDK Bridge. Only add a
   read-only exact GlobalID lookup if it catches a real gap not already
   checked by BridgeModule.cs; duplicate checks without benefit increase
   service calls and failure paths.
3. For each notification, preserve the captured service/layer, GlobalID,
   OBJECTID, source event UTC time, correct CREATE/EDIT actor and GDB
   version; never rerun a "latest features by creator" lookup when clicked.
4. Verify office installation of Python notification code, Windows URI
   handler, and current compiled ArcGIS Pro add-in. Code on GitHub does
   NOT guarantee installed office binaries were updated.
5. Reproduce with two poles by the same surveyor, older edited pole
   and newly edited pole, delayed click and map activity. A mismatch
   must not change the selected record, layer or map extent.
6. Run existing notification, alert-navigation, delay/maintenance tests
   and Windows add-in build. Only consider a merge once tests and the
   installed-system acceptance check pass.
7. Continue KMZ PR #12 separately; avoid mixing its changes with this PR.

## Future merge criteria
- No incorrect pole may be opened, regardless of which surveyor edited it.
- Correct source time and creator/editor must be shown.
- Stale/legacy notification may display a message but may NOT zoom.
- Absence of correct sde.DEFAULT layer MUST fail closed.
- Same-creator record is never substituted for missing exact GlobalID.
- Both KMZ export and existing monitor behavior remain unaffected.

## Technical note
The staged helper uses a bounded (maximum two) read-only ArcGIS
FeatureLayer.query by validated GlobalID and verifies exact OBJECTID and
optional event time/editor. It has no portal credentials and performs no
feature editing, map selection, or zoom.


## Reviewed updated Substations v2.3 rather than old main

Reviewed these current Kotlin implementations on branch
`development/v2.3-field-assistant-mvp`:
- `FieldAssistantRecentCreationResolver.kt` refuses ambiguous recent
  creation candidates and a full 20-item cap.
- `FieldAssistantPolicy.kt` scopes explicit "just created" intent to
  a 60-second window and verifies site/equipment class.
- `FieldAssistantIdentityStore.kt` prevents same-day GlobalID identity
  repointing.

REPORTAPP **must not** copy creator-scoped 60-second discovery: it monitors
older edited network assets, not only newly created devices. The adopted
principles are exact GlobalID re-fetch, reject duplicates, match OBJECTID
and latest CREATE/EDIT actor/timestamp, then leave both map selection and
extent unchanged on mismatch.

## Source Event Time: implemented changes in PR #17

1. `surveyor_notifications.deliver`: only add a desktop click action after
   `safe_verified_source_uri` successfully refetches the exact notified
   feature on `sde.DEFAULT`. A mismatch leaves the toast readable but
   not clickable. The original event UTC milliseconds are not replaced
   by latest-by-creator or local toast arrival time.
2. `surveyor_activity.deliver_clean_activity`: clean notifications
   no longer use unverified `reportapp://zoom/<asset>/<OBJECTID>`;
   they require the same exact GlobalID / timestamp / editor / version
   as QA gaps.
3. Explicit GUI TEST notifications now use `mode=manual`; they are not
   falsely presented as validated surveyor submissions.
4. New offline regression suites cover two poles from the same surveyor,
   freshly edited older pole, delayed or stale edits, wrong GlobalID,
   different editor, wrong version, missing/ambiguous service results,
   and ArcGIS errors. GitHub Actions test on Windows and Linux.
5. The existing 1.0.4 compiled Bridge still checks map source identity at
   click time, so the re-fetch on toast does NOT authorize any automatic
   zoom. Map Zoom pause remains authoritative.

**Not verified**: actual office ArcGIS Pro click-through after these new
Python files are installed. No production merge, task change, auto-update,
portal credential change, or KMZ mixing is permitted on this PR.

**Deployment caution:** This draft PR branches from main, whereas office
V3 is already running a *separately pinned* 83-file snapshot from PR #16.
Treat these as future versioned source changes. Never overwrite the live
immutable snapshot or Git checkout with ad-hoc single-file edits.

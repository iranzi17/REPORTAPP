# Working-session handoff: exact ArcGIS feature lookup
Date: 17 October 2026

## Source and scope
The useful Substations Data Assistant pattern is an exact GlobalID lookup
which rejects zero/multiple results and re-verifies the selected feature.

Source: https://github.com/iranzi17/Substations-Data-Assistant/blob/main/arcgis_client.py

Staged in REPORTAPP:
- src/meter_photo_qa/exact_feature_lookup.py
- tests/test_exact_feature_lookup.py

These are NEW, ISOLATED, READ-ONLY files. NOT wired into live monitoring,
navigation, or KMZ processing yet. Do not treat this branch as the office fix.

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

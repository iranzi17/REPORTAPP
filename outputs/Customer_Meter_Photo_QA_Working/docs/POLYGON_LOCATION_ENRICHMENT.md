# REPORTAPP — Polygon-based Location Enrichment (pilot)

## What this fixes

Existing LV Pole and Distribution Transformer quality Excel workbooks can have
**Recorded District**, **Recorded Sector** and **Recorded Cell** blank even
though REPORTAPP already uses Rwanda's hosted administrative polygons.

This utility uses the same configured REG FeatureServer and
`Hosted/Sector_and_Cell_Boundaries/FeatureServer/1` cell polygons. It
queries *point geometry by OBJECTID*, intersects with the cell polygon, and
fills missing report values only when there is exactly **one** complete
district/sector/cell match.

**Scope:** Only copies of existing `Asset Details` workbook sheets from
asset groups 7 (LV Poles) and 12 (distribution transformers). No Electric Line
spatial assignment: a line can cross multiple cells.

## Safety

- Dry-run by default; requires explicit `--apply` to generate **a new Excel copy**.
- Never updates, deletes or adds any REG FeatureServer features.
- Never overwrites the original Excel file, nor previously created output.
- Existing nonempty location attributes are never overwritten.
- Conflicts between recorded values and the polygon are left unchanged and
  marked `LOCATION_CONFLICT_REVIEW` for supervisor review.
- Missing/unselectable features, mismatched GlobalIDs, invalid geometries
  and ambiguous/missing polygon matches remain blank with diagnostic status.
- New `Polygon Location Audit` worksheet records original values, polygon
  values, final values, OBJECTID, GlobalID and the resolution status.
- `Location Provenance` is added after the existing `Asset Details` table.
- `By Recorded Location` and other original aggregate sheets retain their
  historical as-recorded values. Use the audit sheet for enriched counts.
- No changes to the watcher, monitor config, historical alerts, scheduled tasks,
  ArcGIS add-in, GIS feature attributes or automatic updater permissions.
- The Self-Maintenance updater deliberately **does not auto-deploy** this GIS
  reporting tool. Human review and a normal `git pull --ff-only` are required.

## Windows first test

1. After the approved PR is merged and local Git is updated, open CMD:

   ```cmd
   cd /d "C:\Users\AKIOLI TECHNOLOGY\Desktop\REPORTAPP"
   set "QA=C:\Users\AKIOLI TECHNOLOGY\Desktop\REPORTAPP\outputs\Customer_Meter_Photo_QA_Working"
   set "PY=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
   cd /d "%QA%\src"
   ```

2. Find the **exact original** LV pole quality workbook's path, not an enriched
   copy. Dry-run, no Excel write:

   ```cmd
   "%PY%" -m meter_photo_qa.polygon_location_enrichment --report "C:\path\to\pole_quality.xlsx"
   ```

3. Inspect dry-run counts, especially `records_filled`,
   `LOCATION_CONFLICT_REVIEW` and `AMBIGUOUS_POLYGON_MATCH`.
   If reasonable, generate a **new** report copy:

   ```cmd
   "%PY%" -m meter_photo_qa.polygon_location_enrichment --report "C:\path\to\pole_quality.xlsx" --apply
   ```

4. Open the new `*_polygon_enriched_YYYYMMDD_...xlsx`. Check both the
   corrected blank District/Sector/Cell columns and `Polygon Location Audit`.
   If discrepancies appear, retain the original and report the OBJECTIDs
   and status—not screenshots containing personal credentials.

## Notes

- The `--version` option defaults to `sde.DEFAULT` and can be explicitly
  set if the original report came from a different authorized REG GDB version.
  A mismatch may produce `FEATURE_NOT_FOUND` or
  `SOURCE_GLOBALID_MISMATCH` rather than a false location.
- A cell polygon spatial match is a derived **report location**, not a
  surveyor-recorded field. Enrichment provenance is explicit.
- Python unit tests simulate ArcGIS service geometries. A real portal
  access test is required on the office machine before calling this pilot
  production-validated.

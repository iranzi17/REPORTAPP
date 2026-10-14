# REPORTAPP data-quality v2

## Production functionality

The **Working** ArcGIS Pro toolbox includes a read-only LV watcher with:
- existing 60% overall completeness score and editable review queue;
- phase/type conflict detection using phase counts decoded from live
  subtype domains, only where the asset-type label is unambiguous;
- **Outstanding Gap Summary** and **Outstanding LV Gaps** worksheets,
  grouped by creator and listing each affected feature's GlobalID.

### Priority LV correction categories

The focused outstanding correction register counts **only**:

1. Missing/invalid phases
2. Missing/placeholder Transformer Name
3. Unselected/invalid voltage
4. Unknown/missing conductor material
5. Missing/invalid conductor insulation
6. Phase/type conflicts

The issue-category names match the existing field review tables; exact
validation details remain on each row. One line with multiple issues counts
once under *With Outstanding Gaps* and multiple times under *Total Issues*.

**Do not confuse the two statuses.** A line that meets the 60% threshold
can still appear in Outstanding LV Gaps. General checks such as construction
year, commissioning year, supplying lines, conductor size and rated current
remain in Line Details; they are not included in the focused correction totals.

The watcher only reports features matching its selected dates (created or
edited), geography and users. A two-day run is not a full historical backlog.
Use the full intended period to assess the remaining outstanding work.

## Pole manufacturer exception (future pole module)

If the pole's Manufacturer is blank, the surveyor must write in **Notes**
that the pole has **no nameplate** (for example: "No name plate").
A blank Manufacturer without that explanation is a gap. This is an
*explicitly documented field observation*, not a manufacturer value inferred
by the app.

**This requirement is recorded here but is not yet active.** The current
watcher assesses LV lines, not pole manufacturer data. Before activating it,
confirm the field names, pole asset groups and the valid Notes conventions
against the live Utility Network schema.

## Distribution transformer policy (next integration)

When adding the transformer checker:
- assess **distribution transformers only**, not generic Electric Device
  records (e.g. CTs, VTs, breakers and switches);
- exclude Ntaruka power-plant equipment using verified asset types and
  plant boundaries or other authoritative classification;
- **Branch is excluded** from required fields as it is auto-generated;
- identify features by GlobalID, and distinguish corrected, outstanding,
  new and unverified records; do not count absent records as corrected.

## Testing in ArcGIS Pro

Use the toolbox under
`outputs/Customer_Meter_Photo_QA_Working/CustomerMeterPhotoQA.pyt`.
Reopen ArcGIS Pro after a synchronized source update if cached helpers
are still loaded.

Code tests are in
`outputs/Customer_Meter_Photo_QA_Working/tests`.
Run focused unit and workflow tests in the ArcGIS Python environment
before relying on new reports for surveyor performance decisions.


## Distribution Transformer and LV Pole Watchers (added Oct 13, 2026)

The Working ArcGIS Pro toolbox now exposes two read-only tools alongside
`Watch LV Line Data Quality`:
- `Watch Distribution Transformer Data Quality` on Electric Device layer 7,
  **Asset Group 12 only** (distribution-transformer types 1 through 6).
- `Watch LV Pole Data Quality` on Structure Junction layer 12,
  **Asset Group 7** (Wooden 1, Concrete 2, Steel 3).

Both tools accept the same multiple-district selection, optional sectors/cells,
custom boundary, dates, surveyors and Utility Network version. Attribute
queries use the ObjectID-first batched loader (150 at a time by default)
and deduplicate shared administrative boundary intersections.

### Original transformer correction register

Recovered historical correction register
`Transformers_Distribution_Only_Exclude_Ntaruka.xlsx` had 160 actual
distribution transformers; 59 contained at least one remaining gap.
Only these **seven** categories are scored for comparison with that audit:

- Owner Name unknown/missing
- Type of Installation missing
- Phase Normal missing
- Transformer Protection Switch unknown/missing
- Transformer mounting support unknown/missing
- Transfomer Name missing
- Number of Low Voltage feeders missing

**Branch is excluded**. Manufacturer, Serial No and Rated kVA may be
displayed if live fields are available, but are NOT included in these
historical correction totals. The 30 Ntaruka plant devices previously
excluded were circuit breakers, CTs, VTs and other non-distribution
equipment. The tool enforces the distribution-transformer asset group
rather than excluding arbitrary assets near Ntaruka.

Live fields can have different internal names from field aliases. An exact
candidate or unique matching alias is used only when unambiguous. If a
field cannot be resolved, a `NOT_VERIFIED` state and Schema Verification
worksheet prevent a misleading clean result. Compare historical and new
records by GlobalID across equivalent scopes; `59` is a historical
baseline, not a guaranteed live outstanding count.

### LV pole manufacturer/nameplate observation

If Manufacturer is not recorded, a surveyor must write in Notes that
there is **no name plate** (e.g. "No name plate"). The quality tool
records `DOCUMENTED_NO_NAMEPLATE` for this explicit explanation
and does NOT fabricate a manufacturer. Missing Manufacturer with no
adequate note is a GAP, for all three LV pole asset types.
Missing live Manufacturer or Notes fields trigger a schema-verification
warning rather than an unsupported "clean" result.

### Limitations and validation

The new tools are GitHub CI tested using synthetic feature-service
responses. Live schema aliases must be confirmed from the first ArcGIS Pro
reports. There are no service edits, and incomplete service responses
abort without producing partial success reports. The tool does not
automatically compare against the historical baseline workbook yet;
a subsequent user-provided live QA workbook can be compared on GlobalID.


## Confirming suspected duplicate Electric Line records

For investigating repeated GlobalIDs in the same Electric Line table, the
Working toolbox includes **Inspect Electric Line Duplicate GlobalID**.
Paste one GlobalID and select the same Utility Network version as the map.

The diagnostic independently queries the Electric Line FeatureServer
(layer 10) by `GLOBALID`, returns each distinct `OBJECTID`, and writes
the source attributes, geometry assessment and both OBJECTIDs to Excel.
Geometry is called *exactly identical* only when all 2D vertex sequences
match, allowing reversed direction/path order. Same `SHAPE_Length` alone
is **not** enough to prove geometry duplication. Different vertex
sequences may still overlap: verify in ArcGIS Pro and review all Utility
Network associations and attachments.

A repeated GlobalID on different source OBJECTIDs is a data-integrity
issue requiring authorized investigation; two table rows can otherwise
arise from joined displays or different versions, which is why the
independent FeatureServer query matters. No automatic deletion, edits or
topology validation occur. Fix source issues under approved workflows,
validate the appropriate version's affected topology, and then re-run
network-connected transformer name QA.

Example under investigation:
`{9FD1C5F4-AF23-43A3-90E3-CB1E7D8CA08C}`, observed in
the Electric Line attribute table on OBJECTIDs 122510 and 122944,
and independently reported as a dirty-area blocker by Utility Network
connected trace. The duplicate may contribute to network issues, but
the trace error alone does not establish causation.


## Nationwide duplicate Electric Line register (October 2026)

A second Working ArcGIS Pro tool, **Scan All Electric Line Duplicate
GlobalIDs**, searches **all source Electric Line features** by default;
optionally restrict to LV overhead/underground asset groups 9 and 10.
It is independent from the single-GlobalID **Inspect Electric Line
Duplicate GlobalID** tool.

It scans the requested Utility Network version using bounded,
ascending OBJECTID pagination without date or surveyor filters, counts
duplicate groups by normalized GlobalID, then fetches attributes and
geometry **only for duplicate records**. The hosted national cell
boundaries are spatially intersected with each distinct duplicate
polyline, with intersections reused for exactly identical geometry.

Excel output:
- **Summary:** full scan size, duplicate GlobalID group count,
  affected record count, extra copies, invalid/missing GlobalIDs,
  source and version.
- **Duplicate GlobalIDs:** one row per repeated GlobalID with all
  OBJECTIDs and aggregated district/sector/cell names.
- **All Duplicate Records:** one row per source OBJECTID, its GlobalID,
  district, sector, cell, other duplicate OBJECTIDs, asset group/type,
  shape length, editor tracking and transformer name.
- **By District Sector Cell:** unique repeated GlobalIDs and source
  feature counts for each intersecting cell.
- **Method and Warnings:** review precautions and measurement limits.

Some lines cross more than one cell; the report lists all intersections,
not a guessed single administrative location. Missing geometry/CRS or
missing cell matches are labelled **unverified**, not fabricated.
The tool aborts rather than writing a partial successful report if the
source record count changes during a scan, a page fails, or a required
duplicate geometry fetch fails. In-place modifications during the scan
with the same total count are not fully detectable; perform final checks
when editing is paused for the most stable inventory.

**Scope limitation:** this identifies multiple source OBJECTIDs with
the **same GlobalID**. It does not yet scan distinct GlobalIDs that may
share identical or overlapping geometries. It makes no source edits,
deletions or Utility Network topology changes. Duplicate GlobalID
findings must be reviewed with network associations/attachments and
approved by authorized GIS/Utility Network editors before remediation.


## Recorded geographic columns in asset QA (Oct 13, 2026)

First successful transformer quality workbook on Burera, Gakenke and
Rulindo (Aug 29–Oct 13) contained 131 records, 40 affected features,
122 individual issues, and no repeated transformer GlobalIDs. All
seven historical correction fields resolved to live attributes.
However, its Asset Details sheet did not contain geography despite the
live layer exposing `District`, `Sector` and `Cell` fields.

The Working transformer and LV pole quality watchers now include these
three **recorded** location columns in Asset Details, and a
**By Recorded Location** worksheet with feature and gap counts.
These are source attributes for planning corrections, not verified
spatial intersections. Unknown/unrecorded locations are labeled
`(not recorded)`; geography is informational and does not inflate
the original correction priorities. Branch remains excluded.

The initial transformer QA showed 39 missing LV-feeder counts,
20 missing installation types, 17 missing mounting supports, 16
missing protection-switch attributes, 15 missing owners, and 15
missing phase attributes. Transformer Name was complete within
that date/geography/surveyor scope; connectivity-based name consistency
is a separate check requiring validated Utility Network topology.

The uploaded duplicate report had 154 repeated GlobalID groups
(309 records, one group with three records), of which 17 groups did
not have wholly identical vertex sequences. It contained asset
groups 9 (overhead LV) and 10 (underground LV) only, so do not call
it a full LV/MV/HV inventory absent an overall scan summary.


## Repeated distribution-transformer GlobalIDs in a quality run (Oct 13, 2026)

The transformer watcher can encounter repeated GlobalIDs on distinct
source Electric Device OBJECTIDs. A live three-district test found
GlobalID `8013868c-1ed5-46a9-8f97-2c3a8bd86a01` on source
OBJECTIDs **605878** and **606278**. The first version failed after
retrieving 150 of 786 unique ObjectIDs; these are source-feature counts,
not confirmed physically distinct transformers.

**Change:** both the transformer and LV pole quality watchers opt in to
the `query_attributes_in_batches(..., duplicate_globalid_policy="report")`
mode. The reusable batch loader defaults to `"error"` for stricter
other callers. Asset QA now continues through every requested batch,
retains each distinct OBJECTID, flags each repeated GlobalID as a separate
identifier/data-integrity gap, and produces:

- **Duplicate GlobalIDs** — one row per repeated identifier with all
  OBJECTIDs, surveyors, transformer names and recorded admin attributes.
- **Duplicate Asset Records** — one row per affected OBJECTID with all
  peer OBJECTIDs, original attribute issues, recorded district/sector/cell
  and identity-review information.

The Summary shows **both** original field-correction counts (the seven
previously agreed transformer attributes, excluding Branch) and all
data-integrity findings. Do not count each duplicate record as a unique
physical transformer until field/network review. Reports remain read-only.

**Important scope limitation:** a duplicate is found only when at least
two source OBJECTIDs are included by the **selected date range, surveyors
and administrative boundaries** in the *same run*. This workbook is NOT a
full nationwide transformer duplicate inventory. A full unrestricted
distribution-transformer inventory is a separate task. Recorded
District/Sector/Cell fields may be blank; empty cells do not prove
the asset has no geographic location. No geometry, attachments, or
Utility Network associations are compared in this watcher.

Source query failure or missing requested OBJECTIDs still cancels the
run—do not produce misleading partial reports.


## First live LV pole audit — corrected live manufacturer field (October 14, 2026)

Uploaded `pole_quality_20261013_172719_20261013_172807.xlsx`
covers Burera, Gakenke and Rulindo, 29 Aug–13 Oct 2026 with 64
surveyor accounts selected (42 returned). It contains 66,915
Structure Junction LV Pole records: 63,664 wooden, 2,534 steel,
702 concrete, and 15 with an unrecognized asset type.

The **original** manufacturer QA result is INVALID as a completeness
claim: the tool was matching singular `Manufacturer`, but the actual
Structure Junction layer has `Manufacturers` (plural, string) and
`Notes`. Thus 66,443 records were classified NOT_VERIFIED, while
472 were GAP principally because the report also found 229 duplicate
GlobalID groups / 458 distinct records. There were 15 original
attribute-type issues, but the manufacturer completeness rule was not
run on any source record. Do not interpret 0 NO_GAPS_FOUND as evidence
that all poles are incomplete.

Corrected the pole field lookup to resolve **`Manufacturers`**, without
confusing it with `CountryOfManufacturer`. The Notes exception
recognizes explicit English and Kinyarwanda absence statements (e.g.,
`No name plate`, `Nta name plate iriho`). Notes such as
`Name plate not clear` remain REVIEW/GAP when manufacturer is blank:
they do not confirm a missing nameplate.

Approximately 5,343 Notes entries explicitly describe no nameplate
(English or Kinyarwanda), while about 479 report an unclear plate.
These counts are based on Notes only; the first workbook **did not
retrieve Manufacturers**, so neither the actual manufacturer-gap total
nor the intersection of missing manufacturer values and qualifying
Notes can yet be reported. Re-run with the corrected toolbox.

The Structure Junction layer's live schema in this workbook has
**no District, Sector or Cell attributes**. Every recorded-location
field was therefore blank; assigning administrative locations to poles
requires authoritative point-in-polygon spatial attribution from
feature geometry against the hosted administrative boundaries.
No district or cell was inferred from surveyor name or selection
without spatial evidence.

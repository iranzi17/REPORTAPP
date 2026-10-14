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


## Senior Supervisor Pamela — Gicumbi team profile (Oct 14, 2026)

The Working ArcGIS Pro toolbox now contains
**Review Gicumbi - Pamela Team (LV Lines, Transformers, Poles)**.

The source is `Detailed plan for Gicumbi district revised 1(1).xlsx`,
filtered strictly to work-plan entries whose **Senior Supervisor Name**
is Pamela (field Supervisor Derrick). The plan's schedule is 14–16
September 2026; QA date range is configurable.

**Six sectors:** Muko, Mutete, Nyamiyaga, Nyankenke, Rukomo and Rushaki.
The 32 enumerated plan cells, 95 planned transformers, and approximately
196.85 km of planned LV lines are planning reference totals, **not actual
live REGUN completions**. Assignment is *by sector*; the work plan does
not attribute specific cells or individual line segments to a particular
person within a multi-person team.

**12 planned surveyors; all 12 have confirmed current portal accounts**
in `config/report_user_names.json`. A work-plan spelling variation for
Bimenyimana Emmauel corresponds to configured Bimenyimana Emmanuel.
**Updated Gicumbi account roster, 14 October 2026 (user screenshot):**

| Current portal username | Current surveyor name | Previous REPORTAPP account label |
|---|---|---|
| `ninamenye9683` | Kwizerwa Edison | Nshimiyimana Jean Baptiste |
| `maniraguhatheogene01` | Ringuyeneza Frederic | Kwizerwa Edison (and earlier Manzi Intime) |
| `janviersafari515` | Usabyeyezu Jean Dieu (screenshot spelling: Usabyezu) | Nkubana Guillaume |

The 12-person Pamela field roster now uses these three updated usernames.
Personnel change **Kwizerwa Edison replacing Manzi Intime** remains
recorded, but the latest screenshot supersedes the former
`maniraguhatheogene01` **current** assignment. Exact portal-account
handover dates were not provided; previous holder labels are retained
as a **historical attribution caution**, not asserted historical
session ownership. Existing legacy usernames `etienne2020` and
`jeandedieujadomax123` are no longer the active Pamela assignments
for Ringuyeneza and Usabyeyezu, respectively; they are retained in
the broad user-name map pending a historical data review. For records
created across account changes, prefer a dated handover register or
independent survey attribution over current account labels.

The profile configuration is
`outputs/Customer_Meter_Photo_QA_Working/config/gicumbi_pamela_team.json`.
This file stores actual work-plan names, cells, sectors, and mapped
portal account usernames. Source mapping changes fail verification
before querying REG.

### Modes

- **Mapped Pamela team accounts only** (default): includes all **12**
  confirmed current account logins; the former Intime login is now
  assigned to Edison for current QA routing. Records predating the
  staff handover require separate attribution review.
- **All accounts in the six sectors:** useful for identifying unmapped
  users and records made by accounts not in the plan. Such accounts
  must **not** be claimed as Pamela's team members without review.

Asset selection can run all three modules or one selected module.
Each run creates a uniquely timestamped output subfolder with existing
read-only QA workbooks:
- `Pamela_Pole_*.xlsx`
- `Pamela_Transformer_*.xlsx`
- `Pamela_LV_Lines_*.xlsx`

It also writes `Pamela_Team_Roster.csv` and
`Pamela_Review_Manifest.json`. The manifest records exact sector,
surveyors, date range, profile scope, QA metrics and status. If one
module fails (e.g. FeatureServer 503), the manifest is marked
**INCOMPLETE** and any earlier successful asset reports remain
available; the tool never falsely reports full completion.

### Review caveats

- A field `created_user` is surveyor attribution for these reports.
  The person who last edited a feature may be different.
- LV line priority gaps and General Completeness are distinct.
- Distribution-transformer original seven missing-attribute checks
  are distinct from repeated GlobalID source integrity issues.
- LV pole manufacturer field is actually `Manufacturers` (plural);
  a missing manufacturer requires a genuine `Notes` statement that
  the nameplate is absent.
- Planned assignments do not prove the individual field collector
  worked in every cell of their sector; do not blame surveyors for
  edited/legacy records without further evidence.
- Geographical filtering uses chosen administrative polygons; source
  District/Sector/Cell attributes on poles may be absent. No editing
  or Utility Network topology validation is performed.


## Ask REPORTAPP: plain-language query and filter (Oct 14, 2026)

**New tool:** `Ask REPORTAPP - Query and Filter Attributes` in
`outputs/Customer_Meter_Photo_QA_Working/CustomerMeterPhotoQA.pyt`.

This is the first **controlled natural-language interpreter**, not an
unrestricted LLM or conversational agent. It converts only recognized
instructions to a whitelisted attribute SQL expression and (when
provided) a spatial selection against official district/sector/cell
boundaries. It **does not** execute SQL supplied by the user and will
fail if any substantive part of the request cannot be interpreted.

**Examples to paste:**

- `Show LV poles in Gicumbi with missing manufacturer`
- `Find distribution transformers in Burera with protection switch is unknown`
- `Count LV lines in Gicumbi sector Muko with missing transformer name`
- `Filter LV lines in Gasabo with voltage = 400`
- `Show LV poles in Pamela team with missing notes`
- `Show LV poles in Gicumbi by Kwizerwa Edison with missing manufacturer`
- `Count LV lines in Gicumbi by Ringuyeneza Frederic`
- `Find distribution transformers in Gicumbi by Usabyezu Jean Dieu`
- `Show LV poles in Gicumbi by maniraguhatheogene01`
- `Find LV poles in Gicumbi sector Muko cell Mwendo`

The first release supports exactly one asset category per request
(LV poles, distribution transformers, LV lines), one administrative
district with optional **explicit** sector/cell, a username
(`by <portal_account>`) or one full surveyor name resolved against
the current user mapping (e.g. `by Kwizerwa Edison`), or the special
12-account Pamela team,
and simple verified-field missing/equals comparisons. A request
mentioning Pamela resolves to Gicumbi and the six planned sectors;
data captured under the three reassigned usernames may predate
their most recent holder changes. Full-name lookup in Gicumbi
prioritizes the active Pamela profile, including the screenshot
spelling variant `Usabyezu Jean Dieu`, and rejects ambiguous
names rather than guessing.

Attribute names are resolved **against the live FeatureServer fields**.
Pole manufacturer resolves to `Manufacturers` (plural).
Transformer original correction fields use exact/unique known aliases,
and LV line fields use the existing REG layer spellings (such as
`CondustorSize` and `Voltage_Level_kV`). The interpreter refuses
unrecognized fields, operators, places and any write/delete requests.

**Two modes:**

1. **Preview query and count only (default).** Displays parsed query,
   generated SQL, spatial boundary criteria and matching feature count.
   Saves a JSON interpretation/audit log.
2. **Create local filtered layer and add to map.** Selects matching
   features from the configured services, copies them **only to the
   ArcGIS scratch geodatabase**, confirms copied count, and adds that
   local feature class to the current map. Refuses copies above 25,000
   features until the query is narrowed. Network source features,
   fields, associations and topology remain unchanged.

**Important limitations:**
- Live ArcGIS Pro test of REST-service layer and selection functionality
  is still required; unit tests use simulated ArcPy.
- The ArcPy FeatureServer layer connection is not an explicit
  `gdb_version` override; compare the map's connected service version.
  For branch-version-aware filtering, build a separate authenticated
  feature layer workflow in a future release.
- This tool filters **records based on attributes**. It does not yet
  hide/show individual attribute columns or provide a persistent
  multi-turn chat. Natural language involving tracing, feeder voltage
  drop, between-pole connectivity, fuzzy names or complex formulas
  should fail closed, then be implemented as separate verified actions.
- `missing manufacturer` queries find blank manufacturer fields;
  they include poles documented as having **no nameplate**. For the
  true manufacturer *QA gap* excluding verified no-nameplate exceptions,
  use `Watch LV Pole Data Quality`, which checks `Notes`.
- Administrative boundaries are spatially intersected, so border
  features may be present in multiple areas; exact district labels are
  never guessed from surveyor names.
- FeatureServer query access depends on ArcGIS Pro being signed into
  an account with permission for the REG Utility Network service.

**Next iteration:** add history-based dialogue, safe column projection,
filter conjunctions and a schema-aware local LLM (optional). Require
explicit confirmation for anything changing live GIS; future
conversational interpretation does not bypass technical validation.

## Ask REPORTAPP — prepare LV feeder report by surveyor and source district (Oct 2026)

New supported commands in the existing **Ask REPORTAPP - Query and Filter Attributes** tool:

- `Prepare LV Lines Report for Kwizerwa Edison in Gicumbi`
- `Prepare LV Lines Report for ninamenye9683 in Gicumbi`
- `Prepare LV Lines Report for Ringuyeneza Frederic in Gicumbi`
- `Prepare LV Lines Report in Burera` (all surveyors)

Choose the separate **Destination folder for requested LV Lines Report**
control in ArcGIS Pro. The output is a timestamped Excel workbook in that
folder (Summary, Connected LV Lines, Engineering Review, Starting Transformers,
Method and Caveats). The command does not interpret arbitrary embedded
filesystem paths: the ArcGIS folder picker determines the output location.

### Feeder origin and border rule — essential

**A district is a transformer-source selection boundary, NOT a line clipping
boundary.** Find distribution-transformer points located in the specified
district, then perform **Utility Network connected traces from each
secondary terminal**. Retrieve all LV line ObjectIDs returned by each trace
independently of their administrative location, surveyor, creation date or
last-edit date. Do not stop at a sector, district, or provincial border.
Apply any requested `created_user` filter only to the *reported line rows*
**after** obtaining complete connected-component membership. The Summary
provides separate totals before/after the surveyor filter.

This is a **connected-network report**, not a verified **energized-direction
feeder** determination. Where a trace includes multiple distribution
transformers or topology warnings, classify supply as engineering review;
never invent a unique source or automatically rename lines. `validateConsistency`
is kept enabled; dirty-area and trace failures block the report rather than
produce incomplete or unreliable source attribution.

The report includes line GlobalIDs, OBJECTIDs, creator, recorded transformer
name, unique connected-source name when supported, name disagreement, asset
group/type and selected conductor/voltage/phase attributes. A known limitation
is that the default output does not independently calculate the exact district,
sector or cell of every segment; **do not infer that downstream segments remain
in the source district**. To assign each segment's administrative location,
add a separate geometry-to-boundaries intersection step, and distinguish
cross-boundary membership from electrical topology.

Read-only implementation is in
`src/meter_photo_qa/lv_feeder_report.py`; prompt parser is
`src/meter_photo_qa/smart_query.py::parse_lv_report_request`. A live REG
Utility Network run is necessary before using outputs operationally.


## Dirty-topology-tolerant LV feeder report — geometry continuity mode (Oct 2026)

The user requested LV Lines Reports to remain usable even when
Electric Utility Network dirty areas cannot all be validated.

**New default in Ask REPORTAPP -> Prepare LV Lines Report:** 
`Geometry continuity - no Utility Network trace required`.
The earlier strict `Validated Utility Network connectivity trace (strict)`
remains available by choice. The provisional geometry mode **never**
invokes the Utility Network trace or validates dirty areas.

- District selects **starting distribution-transformer points only**,
  by authoritative spatial boundary. Neither LV candidate query nor
  graph traversal is clipped at district/sector borders.
- With a surveyor name or login, retrieve **all LV lines in Rwanda**
  created under that login, without date filters. The caller's
  `created_user` is used to group candidate line continuity; a
  transformer account does *not* have to equal the line creator.
- Request all users without specifying a surveyor only when source
  candidate count is below the safe **25,000-feature limit**, otherwise
  narrow by surveyor. The tool fails rather than silently report a
  truncated dataset.
- Project fetched point/polyline geometry to EPSG:3857; reject missing
  or mismatched spatial reference rather than apply metres to degrees.
- Build a geometry graph from endpoint pairs within **1.5 m**
  (configurable 0.05–5 m). Continue only along the **same created_user**.
  Transformer point proximity within **7 m** identifies a *possible*
  source connection, not an electrically verified source.
- Near-endpoint pairs outside the primary tolerance but within 3 m
  are exported to **Suggested Endpoint Gaps**, *not automatically joined*.
  Crossings midspan, T-junctions without split points and different
  surveyor accounts are *not* traversed; real feeder branches can be
  undercounted. This is a deliberate fail-conservative rule, not proof
  of absence of connectivity.
- Where multiple starting transformers could match a component,
  do not choose one arbitrarily. Flag
  `MULTIPLE_TRANSFORMERS_NEAR_COMPONENT`.
  Transformer-name disagreement is labelled
  `NAME_DIFFERENCE_PROVISIONAL` rather than verified error.
- Review workbook includes **Summary**, **Provisional Connected Lines**,
  **Unassociated Candidate Lines**, **Starting Transformers**,
  **Suggested Endpoint Gaps**, **Repeated Source GlobalIDs** and
  **Method and Limitations**. Duplicate source identifiers remain in
  counts as distinct ObjectIDs, with explicit duplicate warnings.
- The same destination-folder control in ArcGIS Pro saves the Excel.
  The tool reads only the FeatureServer; it does not alter utility
  network topology, line attributes or device associations.

**Engineering interpretation:** a geometric chain, matching collector
login and nearby transformer are evidence for prioritizing inspection,
not energized feeder connectivity, electrical source direction,
switching state, phase continuity or current load. For engineering
signoff, obtain validated trace, as-built/circuit verification or a
field-confirmed path. `Rated_Current` remains **conductor ampacity**.

The geometry algorithm has unit and mock ArcGIS FeatureServer tests;
it still requires its first live REG query. Large national requests
may be slower and need a targeted surveyor. The tool does not yet do
authoritative spatial attribution of every downstream segment to its
district/sector/cell, nor estimate conductor loading or voltage drop.


## Consolidated "Prepare Report" replaces geometry-only output (Oct 14, 2026)

**User correction:** the earlier
`Prepare LV Lines Report for ninamenye9683 in Gicumbi` command
created only `LV_Geometry_Continuity_Gicumbi_....xlsx` with 1,755
nationwide same-creator LV line candidates, 123 provisionally
associated LV line segments, and 1,632 unassociated candidates.
That file is a topology-independent *continuity aid*, **not** the
full asset QA report the user had been receiving.

**Changed behavior:** the existing **Ask REPORTAPP** command now runs
**all three original QA audit engines** using the same district,
surveyor account(s) and user-selectable created/edited period:

1. `run_quality_watcher` — LV lines including outstanding priority
   gap categories, completion score, surveyor summary and review queue.
2. `run_asset_quality(asset="transformer")` — distribution
   transformers, seven historical attribute correction categories and
   duplicate GlobalID register.
3. `run_asset_quality(asset="pole")` — LV Pole checks, including
   the live `Manufacturers` (plural) field, missing-nameplate
   documented `Notes` exception and duplicate GlobalID register.

Output is **one consolidated Excel workbook** with
`Combined Summary`, `Surveyor Comparison`, `Reporting Rules`,
`Sheet Index`, and renamed prefixed copies of all component
worksheets (e.g. `LV Line Details`, `LV Outstanding LV Gaps`,
`LV Review Queue`, `DT Asset Details`, `Pole Asset Details`,
and duplicate/source metadata worksheets). An accompanying
`Components` folder contains the **unchanged original workbooks**
for users requiring native formatting, data-validation controls,
existing review workbooks or other source-specific functionality.
All original audit tests/rules remain active.

The report has visible QA From/To date controls, defaulting to
1 January 2026 and today's date (inclusive). Users can change them.
The chosen destination folder receives a single timestamped
`REG_Combined_LV_Quality_<district>_<timestamp>.xlsx` inside an
organizing subfolder. Source GIS data are never edited.

**Cross-district feeders are an optional, separately labeled
geometry-continuity appendix**, not a replacement for QA. Main
attribute QA is scoped spatially to the requested district;
the appendix searches the chosen collector's LV lines nationally
from starting distribution transformers in the district without
clipping at district boundaries. Inaccurate or dirty topology is
not required. Predictions remain provisional: same creator and
endpoint continuity do not verify source, energized paths or phases.
When the optional appendix fails or cannot run (e.g. national data
limit), the mandatory three original QA audits can still finish.
`Combined Summary` explicitly labels the appendix unavailable,
preventing the absence of geometry evidence from appearing clean.

**Failure protection:** if *any* of the three mandatory original QA
audits fails, the consolidated report is not reported as complete.
Earlier successful original component workbooks are preserved with
an `INCOMPLETE` manifest. The backend never fabricates missing
surveyors, transformer origins or gap counts.


## LV Pole mandatory field: Append Cable (October 14, 2026)

The live Structure Junction LV Pole QA (asset group 7, types 1–3) now
requires **Append Cable** in addition to the existing **Manufacturers**
and **Notes**/no-nameplate rule. Candidate live field names are
`Append_Cable`, `AppendCable`, `Append Cable`,
`Append_Cables`, and `AppendCables`, resolved against actual live
field names or unique exact aliases. The current runtime schema still
needs confirmation of the exact source field name.

- Each eligible pole requires a **known response**. Explicit
  `Yes` and `No` are both valid; blank, NULL, `Unknown`, `N/A`
  and similar unselected values are gaps.
- Numeric coded values such as `0` are valid when the **actual
  ArcGIS coded domain** resolves to a known choice such as `No`.
  A string `"0"` without verified domain mapping is not
  silently assumed to be a `No`.
- Unlike manufacturer, this field has **no nameplate Notes exception**.
  A pole with no manufacturer nameplate still needs Append Cable
  recorded.
- If the source layer does not provide a unique matching field,
  QA displays **NOT_VERIFIED** and shows the unmapped field under
  **Schema Verification**. It must not call poles complete.
- Standalone `Watch LV Pole Data Quality` reports add `Append Cable`
  and `Append Cable QA` columns, a dedicated summary issue count,
  and a Rule-sheet description. The combined
  `Prepare Combined QA Report` inherits these checks and shows
  the updated pole results in its prefixed sheets.
- `Ask REPORTAPP` now supports explicit missing/equal filtering, e.g.
  `Show LV poles in Gicumbi with missing append cable`.
- Transformer historical seven mandatory correction categories and LV
  line rules are unaffected. All reads remain source read-only.

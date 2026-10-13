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

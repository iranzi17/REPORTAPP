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

# LV feeder engineering consistency — implementation specification

**Stage 1 (implemented):** the pure read-only engine in
`outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/feeder_engineering.py`
is committed to `main` with synthetic regression tests.
**Stage 2 (not yet implemented):** integration with the ArcGIS Pro interface,
a trustworthy source-rooted directional topology export, and per-feeder
engineering review workbook/KMZ. The current LV watcher is unchanged by Stage 1.

## Electrical interpretation

A 230/400 V three-phase four-wire system offers approximately 230 V
phase-to-neutral (LN) and 400 V phase-to-phase (LL). This is NOT a sequential
voltage transformation. A 230 V LN single-phase branch can leave a 400 V LL
three-phase trunk, while the three-phase trunk continues elsewhere at 400 V.

The specific 400 LL -> 230 LN -> 400 LL sequence is suspicious **only
when it is proven to be a single directed path**, a one-phase segment has
no alternate source and no verified conversion. Parallel branches never
establish an upstream/downstream path by themselves.

### Current: verified meaning and required evidence

**Confirmed by the REG project user:** `Rated_Current` represents the LV
**conductor's current-carrying capacity in amperes (ampacity)**. It is not
measured current, load flow, or a fuse/breaker setting.

- `rated_current_a`: mapped conductor `Rated_Current`, the recorded capacity (A).
- `design_current_a` (`Ib`): expected load current; not derived from the capacity.
- `adjusted_ampacity_a` (`Iz`): verified permissible capacity **after
  installation and environmental corrections**.
- `protective_setting_a` (`In`): rated/setting current of the relevant
  protective device, not the conductor rating.
- Actual measured current is time-varying, can differ on each phase,
  and decreases/changes through branches; it is NOT available from
  `Rated_Current`.

**Critical unresolved source definition:** Does the REG recorded
`Rated_Current` already include installation derating, or is it a
reference/catalogue ampacity? We do **not** equate it to `Iz` until verified.

The Stage 1 engine:
- marks differing consecutive `Rated_Current` values as **INFO**, not errors;
- flags nonpositive recorded ampacity as a data-quality REVIEW;
- flags `Ib > Iz` as a potential thermal overload **only if Iz is provided**;
- flags `Ib > Rated_Current` for REVIEW when Iz is missing, explicitly
  requiring reference-condition confirmation;
- checks `Ib <= In <= Iz` where the individual inputs are available,
  with protective-coordination caveats.

Do not infer overloaded cable or current-conservation failures from
`Rated_Current` alone. A complete assessment includes overload protection,
installation conditions, voltage drop, phase load sharing, available fault
level, and short-circuit withstand. Actual per-phase flow conservation needs
synchronized measurements or a calibrated load-flow model.

### Cable sections

Conductor sizes can change at branch points or even along a feeder for
load, voltage drop, thermal limits, fault withstand, neutral requirements,
and protection reasons. Changed sizes are **INFO**, not defects. Valid
ampacity assessment additionally needs material, insulation, installed
configuration, installation method, ambient, grouping and correction
factors, available fault levels and protective-device details.

### Critical field semantics

The live field `Voltage_Level_kV` currently has domain labels such as
`400`, `230`, and `242`. Verify whether these are **volts**; do NOT
convert 400 to 400 kV or assume 242 is wrong without the schema owner
confirming the convention. A future schema change should distinguish
`Nominal Voltage (V)` and `Voltage Reference` (`LL`, `LN`), and carry
phase identity (R/Y/B or A/B/C) where available.

## Safety/verification gates

1. Identify supplying distribution transformer by unique GlobalID,
   not `Transformer_Name`; exclude non-distribution plant equipment.
2. Verify Utility Network trace consistency, check associations and
   terminal connectivity; connected trace gives **membership**, not
   feeder direction/order or energized state.
3. Obtain authoritative directed connections with branch and alternate
   supply evidence before performing inter-segment engineering checks.
   Coincident coordinates or visual crossings alone are insufficient.
4. Skip missing links, unverified directions, loops and multiply-supplied
   nodes rather than issue false violation reports.
5. Separate review findings from informational changes, and retain
   GlobalIDs and evidence. Never automatically change network data.
6. Integrate with existing LV outstanding gap categories only after
   testing on real sample feeders.

## Existing Stage 1 API

```python
from meter_photo_qa.feeder_engineering import audit_lv_feeder

segments = [
    {"globalid":"T", "phase_count":3, "nominal_voltage_v":400, "voltage_basis":"LL"},
    {"globalid":"B", "phase_count":1, "nominal_voltage_v":230, "voltage_basis":"LN"},
    {"globalid":"C", "phase_count":3, "nominal_voltage_v":400, "voltage_basis":"LL"},
]
links = [
    {"upstream_globalid":"T", "downstream_globalid":"B", "topology_verified":True},
    {"upstream_globalid":"T", "downstream_globalid":"C", "topology_verified":True},
]
assessment = audit_lv_feeder(segments, links)
assert assessment["review_findings"] == 0
```

**These links are an example only.** Do not label connections as verified
merely because they are close together on a map.

## References

- IEC 60038 standardized 230/400 V: https://cdn.standards.iteh.ai/samples/14766/0ef9a2c3878e40cca23313e947f90bb6/IEC-60038-2009.pdf
- Schneider Electric conductor design: https://www.electrical-installation.org/enwiki/Conductor_sizing:_methodology_and_definition
- Schneider Electric sizing/protection overview: https://www.electrical-installation.org/enwiki/Sizing_and_protection_of_conductors


## Transformer-name trace QA (October 2026)

The Working ArcGIS Pro toolbox has a separate read-only tool:
**Check LV Line Transformer Names**.

**Field rule:** the line's `Transformer_Name` must match the
supplying distribution transformer's `Transfomer_name_`. The comparison
is case-/whitespace-insensitive, but uses no fuzzy name matching.

The tool:
- Selects transformer **Electric Device layer 7 / ASSETGROUP 12 /
  ASSETTYPE 1-6**, excluding CTs, VTs, breakers and unrelated equipment.
- Starts a `connected` Utility Network trace from each selected transformer's
  **secondary terminal**, with `validateConsistency=True`.
- **By default, checks every connected LV line**, including lines outside the
  district boundary or created before the selected dates. Districts/sector/cell
  selection determines transformer start points, not a clipping mask.
  Optional 'Only lines surveyed/edited in selected date range' mode
  preserves date and geographic filters. Explicit surveyor selection
  filters the lines in either mode.
- Queries traced LV line OBJECTIDs in bounded batches; never infers a source
  using nearest geometry or a shared transformer-name string.
- Exports `Summary`, `Name Mismatch Review`, `All Checked LV Lines`,
  `Surveyor Summary` and `Rule and Limitations` worksheets.
  Every line and transformer receives its GlobalID for traceable corrections.
- Treats a missing line name with one uniquely connected named transformer
  as a correction gap.
- Flags a different line name only as `NAME_MISMATCH_REVIEW` pending
  verification of **energized supply and switching state**. Connected topology
  alone does not prove electrical direction.
- Separately identifies cases with multiple transformer points in the
  connected component, trace warnings, unnamed transformer points or no
  verified local transformer. None is automatically assigned a source name.
- Fails closed if a transformer trace fails or a line returned by topology
  cannot be retrieved; no partial report is produced.

Before using the result as proof of surveyor error, a network engineer
should confirm the actual feeder source in the relevant operating
configuration. Mismatches must **not** be automatically renamed in the
Utility Network.

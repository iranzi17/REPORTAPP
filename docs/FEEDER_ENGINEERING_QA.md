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

### Current: three different meanings

- `Rated_Current` may represent a conductor/device thermal rating (A).
- `design_current_a` is a load-design value, not necessarily surveyed.
- Measured feeder current is time varying and, with load branches, is
  NOT expected to remain constant along the feeder.

Do not infer an overloaded cable or a current-conservation failure from
`Rated_Current` alone. For a basic protective design review, the checker
can compare design load `Ib`, protective setting `In`, and **adjusted**
ampacity `Iz` where reliable evidence for all three is supplied. This is
a REVIEW and requires checking applicable protection design exceptions.
Actual per-phase flow conservation requires synchronized per-phase load
measurements or a calibrated load-flow model, including the neutral.

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

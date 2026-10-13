# Mburamazi transformer check — Gicumbi / Rukomo

Checked against the signed-in REG feature service on 15 September 2026. These are live read-only observations; the service may change.

| Check | Finding |
|---|---:|
| Transformer label in the service | `Mburamazi trf` |
| Distribution-transformer points with that label nationally | 1 |
| Those points inside Gicumbi / Rukomo | 1 |
| LV line features carrying that exact label | 29 |
| Named lines within the Rukomo boundary | 29 |
| Named lines crossing or outside Rukomo | 0 |
| Named lines in a continuous drawn geometry chain from the transformer point | 29 |
| Recorded Sector and LV Feeder Name on those lines | Blank on all 29 |

The transformer point is system OBJECTID **227017**. The 29 line features were created on **14 September 2026**, from **05:29 to 15:29 UTC**. One line endpoint coincides with the transformer point. The other named lines connect to this drawn chain when branch endpoints that touch the middle of another line are counted. An endpoints-only check found 11 of 29; accounting for these branch taps found 29 of 29.

## User trace evidence

The [ArcGIS Pro trace screenshot](Mburamazi_Connected_Trace.png) shows a **Connected** trace from the Mburamazi starting point that **succeeded in about four seconds** on 15 September 2026. **Validate Consistency** is checked, and the cyan map selection follows a branched network from that point. The user confirms that the trace ran all lines from the transformer. The long label repeated along the selected lines matches the `created_user` value on all 29 name-matched LV features; it does not indicate a second transformer name.

**Assessment:** The trace gives stronger evidence of *utility-network connectivity* than the name and geometry checks. However, the screenshot does not show returned feature IDs or a count, so its exact overlap with the 29 name-matched LV features has not been independently reconciled. Esri states that a **Connected** trace follows connectivity and **ignores traversability**; this result alone does not establish which lines are energized through switch and barrier conditions. [Connected trace guidance](https://doc.esri.com/en/arcgis-pro/latest/help/data/utility-network/find-connected-features.html) recommends additional barriers or conditions to confine a trace to the intended network area. A numeric accuracy percentage cannot be established from this single case.

The working survey report now accepts a name assignment only when one distribution-transformer point nationally has that name. It labels the result **connection unverified**. Names shared by separate transformer points are excluded from survey totals and placed in an **Unassigned LV Candidates** review section, including candidates outside the selected boundary.

The blank Sector and LV Feeder Name values on all 29 name-matched lines are the next data-cleaning priority for this case. To reconcile the trace with the report numerically, compare its returned line IDs with these 29 features and note any additional lines. Esri's [Trace documentation](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/utility-networks/trace.html) explains that Validate Consistency returns an error if dirty areas are encountered in traversed features; the screenshot shows a successful run with this setting checked.

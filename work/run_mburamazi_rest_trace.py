"""Read-only connected trace for the project's saved Mburamazi starting point."""

import json
import sys
from collections import Counter
from pathlib import Path

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

ROOT = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2"
GLOBAL_ID = "{042316F3-4A09-47DC-B91B-7D4CA7AB5635}"
terminal_id = int(sys.argv[1]) if len(sys.argv) > 1 else 4
gis = GIS("pro")
transformer = FeatureLayer(ROOT + "/FeatureServer/7", gis).query(
    where="OBJECTID=227017", out_fields="OBJECTID,GLOBALID,Transfomer_name_",
    return_geometry=False,
).features[0].attributes
print("Saved start belongs to Mburamazi:",
      str(transformer.get("GLOBALID", "")).casefold() == GLOBAL_ID.casefold())
params = {
    "f": "json",
    "gdbVersion": "sde.DEFAULT",
    "traceType": "connected",
    "traceLocations": json.dumps([{
        "traceLocationType": "startingPoint",
        "globalId": GLOBAL_ID,
        "terminalId": terminal_id,
    }]),
    "traceConfiguration": json.dumps({
        "validateConsistency": True,
        "includeContainers": False,
        "includeContent": False,
        "includeStructures": False,
    }),
    "resultTypes": json.dumps([{"type": "elements", "includeGeometry": False}]),
}
result = gis._con.post(ROOT + "/UtilityNetworkServer/trace", params=params)
if not isinstance(result, dict):
    raise RuntimeError(f"Unexpected trace response type: {type(result).__name__}")
print("Trace response keys:", sorted(result.keys()))
print("Trace error:", result.get("error"))
trace = result.get("traceResults", {})
elements = trace.get("elements", [])
print("Trace element count:", len(elements))
print("Element network source counts:", Counter(e.get("networkSourceId") for e in elements))
print("Element asset group counts:", Counter((e.get("networkSourceId"), e.get("assetGroupCode")) for e in elements))
print("Trace warnings:", trace.get("warnings"))
destination = Path(__file__).with_name(f"mburamazi_rest_trace_terminal{terminal_id}.json")
destination.write_text(json.dumps(result), encoding="utf-8")
print("Trace data saved in work")

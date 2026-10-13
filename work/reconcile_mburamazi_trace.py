"""Reconcile live connected trace IDs with LV feature labels and survey scope."""

import json
from collections import Counter
from pathlib import Path

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

ROOT = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2"
trace = json.loads(Path(__file__).with_name("mburamazi_rest_trace.json").read_text(encoding="utf-8"))
elements = trace["traceResults"]["elements"]
line_elements = [e for e in elements if e.get("networkSourceId") == 17 and e.get("assetGroupCode") in (9, 10)]
ids = {int(e["objectId"]) for e in line_elements}
print("Line elements:", len(line_elements), "distinct LV feature OBJECTIDs:", len(ids))
print("Point elements:", [(e.get("objectId"), e.get("assetGroupCode")) for e in elements if e.get("networkSourceId") == 16])
gis = GIS("pro")
line_layer = FeatureLayer(ROOT + "/FeatureServer/10", gis)
features = line_layer.query(object_ids=",".join(map(str, sorted(ids))),
                            out_fields="OBJECTID,ASSETGROUP,Transformer_Name,created_user,created_date,Shape__Length,Sector,LV_Feeder_Name",
                            return_geometry=False, return_all_records=True, gdb_version="sde.DEFAULT")
rows = [f.attributes for f in features.features]
print("Queried connected line features:", len(rows))
print("Connected assetgroups:", Counter(r.get("ASSETGROUP") for r in rows))
print("Connected transformer name counts:", Counter(str(r.get("Transformer_Name") or "[Blank]") for r in rows))
print("Connected creator counts:", Counter(str(r.get("created_user") or "[Blank]") for r in rows))
mburamazi = [r for r in rows if " ".join(str(r.get("Transformer_Name") or "").split()).casefold() == "mburamazi trf"]
print("Connected lines named Mburamazi trf:", len(mburamazi))
print("Other connected line OBJECTIDs:", sorted(int(r["OBJECTID"]) for r in rows if r not in mburamazi))
Path(__file__).with_name("mburamazi_trace_reconciliation.json").write_text(json.dumps({
    "distinct_lv_objectids": sorted(ids),
    "queried_count": len(rows),
    "name_counts": dict(Counter(str(r.get("Transformer_Name") or "[Blank]") for r in rows)),
    "mburamazi_named_count": len(mburamazi),
}, indent=2), encoding="utf-8")

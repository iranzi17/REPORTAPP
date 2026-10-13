"""Verify the new connected trace helper for the known Mburamazi point."""

import sys
from pathlib import Path

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

root = Path(__file__).resolve().parents[1] / "outputs" / "Customer_Meter_Photo_QA_Working" / "src"
sys.path.insert(0, str(root))
from meter_photo_qa.connectivity_trace import trace_connected_lv_lines

service = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"
gis = GIS("pro")
point = FeatureLayer(service + "/7", gis).query(
    where="OBJECTID=227017", out_fields="OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,Transfomer_name_",
    return_geometry=False,
).features[0].attributes
result = trace_connected_lv_lines(gis, service, [point], "sde.DEFAULT")[227017]
print("Terminal ID:", result["terminal_id"])
print("Distinct LV line features:", len(result["line_objectids"]))
print("Distinct connected transformer points:", len(result["connected_transformer_objectids"]))
print("Network elements:", result["network_element_count"])

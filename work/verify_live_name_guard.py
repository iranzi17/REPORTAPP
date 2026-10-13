"""Check the new national-name guard against the signed-in service."""

import sys
from pathlib import Path

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

working = Path(__file__).resolve().parents[1] / "outputs" / "Customer_Meter_Photo_QA_Working" / "src"
sys.path.insert(0, str(working))
from meter_photo_qa.progress_report import _query_national_transformer_name_counts

gis = GIS("pro")
layer = FeatureLayer("https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer/7", gis)
counts = _query_national_transformer_name_counts(layer, "sde.DEFAULT")
print("National distribution-transformer names counted:", len(counts))
print("Mburamazi trf point count:", counts.get("mburamazi trf"))
print("Murama point count (duplicate control):", counts.get("murama"))

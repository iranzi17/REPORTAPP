"""Run a one-transformer connected-survey workbook against live REG data."""

import json
import sys
import datetime as dt
from pathlib import Path

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

workspace = Path(__file__).resolve().parents[1]
working = workspace / "outputs" / "Customer_Meter_Photo_QA_Working"
sys.path.insert(0, str(working / "src"))
from meter_photo_qa.progress_report import generate_progress_report

service = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"
gis = GIS("pro")
point_set = FeatureLayer(service + "/7", gis).query(
    where="OBJECTID=227017", out_fields="OBJECTID", return_geometry=True,
)
point = point_set.features[0].geometry
x, y = point["x"], point["y"]
radius = 5
boundary = {
    "rings": [[[x-radius,y-radius],[x+radius,y-radius],[x+radius,y+radius],[x-radius,y+radius],[x-radius,y-radius]]],
    "spatialReference": point_set.spatial_reference,
}
output = working / "outputs" / f"mburamazi_connected_survey_pilot_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx"
summary = generate_progress_report(
    output_xlsx=output,
    start_date="2026-09-14", end_date="2026-09-14",
    usernames=["maniraguhatheogene01"],
    custom_boundary_geometry=boundary,
    gis=gis,
)
print(json.dumps({key: summary[key] for key in (
    "output_xlsx", "matched_line_records", "localized_transformers", "connected_lv_feature_ids",
    "trace_network_elements", "name_mismatch_records", "total_km", "localization_warnings",
)}, indent=2))

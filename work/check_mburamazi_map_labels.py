"""Read-only check whether map labels correspond to named LV line creator usernames."""

from collections import Counter

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

gis = GIS("pro")
layer = FeatureLayer("https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer/10", gis)
result = layer.query(
    where="ASSETGROUP IN (9,10) AND UPPER(Transformer_Name)='MBURAMAZI TRF'",
    out_fields="OBJECTID,Transformer_Name,created_user,LV_Feeder_Name,FeederName",
    return_geometry=False, return_all_records=True,
)
users = Counter(str(f.attributes.get("created_user") or "") for f in result.features)
print("Name-matched line count:", len(result.features))
print("Map label 'maniraguhathoegene01' is a creator on named lines:",
      any("maniraguhathoegene01" in name.casefold() for name in users))
print("Named-line creator counts:", users)

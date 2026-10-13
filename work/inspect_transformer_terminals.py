"""Read-only look at distribution-transformer terminal metadata."""

from collections import Counter

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

ROOT = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2"
gis = GIS("pro")
layer = FeatureLayer(ROOT + "/FeatureServer/7", gis)
fields = [f["name"] for f in layer.properties.fields]
print("Potential terminal fields:", [f for f in fields if any(s in f.casefold() for s in ("terminal", "asset", "global"))])
results = layer.query(where="ASSETGROUP=12", out_fields="OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,TERMINALCONFIGURATION",
                      return_geometry=False, return_all_records=True)
print("Distribution transformer asset types:", Counter(f.attributes.get("ASSETTYPE") for f in results.features))
print("Distribution transformer asset type/config pairs:", Counter((f.attributes.get("ASSETTYPE"), f.attributes.get("TERMINALCONFIGURATION")) for f in results.features))
print("Mburamazi asset type:", next(f.attributes.get("ASSETTYPE") for f in results.features if f.attributes.get("OBJECTID")==227017))

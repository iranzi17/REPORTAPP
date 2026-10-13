"""Read-only lookup for Rukomo transformer labels and Mburamazi variants."""

from collections import Counter

from arcgis.features import FeatureLayer
from arcgis.gis import GIS
from arcgis.geometry.filters import intersects


BASE = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"
BOUNDARY = "https://gisweb.reg.rw/server/rest/services/Hosted/Sector_and_Cell_Boundaries/FeatureServer/0"


def main():
    gis = GIS("pro")
    sector = FeatureLayer(BOUNDARY, gis)
    transformers = FeatureLayer(BASE + "/7", gis)
    lines = FeatureLayer(BASE + "/10", gis)
    area = sector.query(
        where="UPPER(district)='GICUMBI' AND UPPER(sector)='RUKOMO'",
        out_fields="objectid", return_geometry=True,
    )
    geometry = {
        "rings": [ring for item in area.features for ring in item.geometry.get("rings", [])],
        "spatialReference": area.spatial_reference,
    }
    filt = intersects(geometry, sr=area.spatial_reference)
    print("Transformer point layer count:", transformers.query(where="1=1", return_count_only=True))
    print("Transformer assetgroup 12 count:", transformers.query(where="ASSETGROUP=12", return_count_only=True))
    print("Rukomo transformer points all groups:", transformers.query(where="1=1", geometry_filter=filt, return_count_only=True))
    local = transformers.query(where="ASSETGROUP=12", geometry_filter=filt,
                               out_fields="OBJECTID,ASSETGROUP,Transfomer_name_", return_geometry=False,
                               return_all_records=True)
    print("Rukomo distribution transformer labels:", [
        (f.attributes.get("OBJECTID"), f.attributes.get("Transfomer_name_"))
        for f in local.features
    ])
    for fragment in ("MBUR", "BURAM", "MURAM", "RUKOMO"):
        where_t = f"UPPER(Transfomer_name_) LIKE '%{fragment}%'"
        where_l = f"UPPER(Transformer_Name) LIKE '%{fragment}%'"
        found_t = transformers.query(where=where_t, out_fields="OBJECTID,ASSETGROUP,Transfomer_name_",
                                     return_geometry=False, return_all_records=True)
        found_l = lines.query(where=where_l, out_fields="OBJECTID,ASSETGROUP,Transformer_Name,Sector",
                              return_geometry=False, return_all_records=True)
        print("Fragment", fragment, "transformers:", [(f.attributes.get("OBJECTID"), f.attributes.get("ASSETGROUP"), f.attributes.get("Transfomer_name_")) for f in found_t.features])
        print("Fragment", fragment, "line labels:", Counter((f.attributes.get("ASSETGROUP"), f.attributes.get("Transformer_Name")) for f in found_l.features))


if __name__ == "__main__":
    main()

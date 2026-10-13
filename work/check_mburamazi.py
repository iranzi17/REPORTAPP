"""Read-only Mburamazi pilot check using the local ArcGIS Pro sign-in."""

import json
from pathlib import Path

from arcgis.features import FeatureLayer
from arcgis.gis import GIS
from arcgis.geometry.filters import contains, intersects


BASE = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"
BOUNDARY = "https://gisweb.reg.rw/server/rest/services/Hosted/Sector_and_Cell_Boundaries/FeatureServer"


def safe_query(layer, **kwargs):
    result = layer.query(**kwargs)
    return result


def main():
    gis = GIS("pro")
    sector_layer = FeatureLayer(BOUNDARY + "/0", gis)
    transformer_layer = FeatureLayer(BASE + "/7", gis)
    line_layer = FeatureLayer(BASE + "/10", gis)
    area = safe_query(
        sector_layer,
        where="UPPER(district) = 'GICUMBI' AND UPPER(sector) = 'RUKOMO'",
        out_fields="objectid,district,sector",
        return_geometry=True,
        return_all_records=True,
    )
    print("Rukomo boundary features:", len(area.features))
    if not area.features:
        raise RuntimeError("No live Rukomo boundary found")
    rings = [ring for feature in area.features for ring in feature.geometry.get("rings", [])]
    geometry = {"rings": rings, "spatialReference": area.spatial_reference}
    spatial_filter = intersects(geometry, sr=area.spatial_reference)
    transformer_where = "ASSETGROUP = 12 AND UPPER(Transfomer_name_) = 'MBURAMAZI'"
    all_transformers = safe_query(
        transformer_layer,
        where=transformer_where,
        out_fields="OBJECTID,GLOBALID,Transfomer_name_,ASSETGROUP,ASSETTYPE",
        return_geometry=True,
        gdb_version="sde.DEFAULT",
        return_all_records=True,
    )
    local_transformers = safe_query(
        transformer_layer,
        where=transformer_where,
        out_fields="OBJECTID,GLOBALID,Transfomer_name_,ASSETGROUP,ASSETTYPE",
        return_geometry=True,
        geometry_filter=spatial_filter,
        gdb_version="sde.DEFAULT",
        return_all_records=True,
    )
    print("Mburamazi transformer points nationally:", len(all_transformers.features))
    print("Mburamazi transformer points in Gicumbi/Rukomo:", len(local_transformers.features))
    print("Transformer OBJECTIDs in Rukomo:", [f.attributes.get("OBJECTID") or f.attributes.get("objectid") for f in local_transformers.features])
    line_fields = [str(field.get("name", "")) for field in line_layer.properties.get("fields", [])]
    candidate_fields = [field for field in line_fields if any(term in field.casefold() for term in ("transform", "feeder", "parent", "subnetwork", "from", "to"))]
    print("Line relationship field candidates:", candidate_fields)
    line_where = "ASSETGROUP IN (9,10) AND UPPER(Transformer_Name) = 'MBURAMAZI'"
    total_lines = safe_query(line_layer, where=line_where, return_count_only=True, gdb_version="sde.DEFAULT")
    crossing_lines = safe_query(line_layer, where=line_where, geometry_filter=spatial_filter, return_count_only=True, gdb_version="sde.DEFAULT")
    within_lines = safe_query(line_layer, where=line_where, geometry_filter=contains(geometry, sr=area.spatial_reference), return_count_only=True, gdb_version="sde.DEFAULT")
    print("LV lines named Mburamazi nationally:", total_lines)
    print("LV lines named Mburamazi intersecting Rukomo:", crossing_lines)
    print("LV lines named Mburamazi within Rukomo:", within_lines)
    result = {
        "area": "Gicumbi / Rukomo",
        "sector_boundary_objectids": [f.attributes.get("objectid") for f in area.features],
        "transformers_national": [
            {
                "objectid": f.attributes.get("OBJECTID"),
                "globalid": f.attributes.get("GLOBALID"),
                "name": f.attributes.get("Transfomer_name_"),
                "geometry": f.geometry,
            }
            for f in all_transformers.features
        ],
        "transformers_local_objectids": [f.attributes.get("OBJECTID") for f in local_transformers.features],
        "line_relationship_field_candidates": candidate_fields,
        "lv_lines_name_total": total_lines,
        "lv_lines_name_intersects_sector": crossing_lines,
        "lv_lines_name_within_sector": within_lines,
    }
    destination = Path(__file__).resolve().parent / "mburamazi_case.json"
    destination.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("Case data saved to work")


if __name__ == "__main__":
    main()

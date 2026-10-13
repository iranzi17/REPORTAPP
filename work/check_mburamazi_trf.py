"""Read-only case facts for the live Mburamazi trf label."""

import json
from collections import Counter
import datetime as dt
from pathlib import Path

from arcgis.features import FeatureLayer
from arcgis.gis import GIS
from arcgis.geometry.filters import contains, intersects

BASE = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"
BOUNDARY = "https://gisweb.reg.rw/server/rest/services/Hosted/Sector_and_Cell_Boundaries/FeatureServer/0"
LABEL = "Mburamazi trf"


def main():
    gis = GIS("pro")
    sector = FeatureLayer(BOUNDARY, gis)
    transformers = FeatureLayer(BASE + "/7", gis)
    lines = FeatureLayer(BASE + "/10", gis)
    area = sector.query(where="UPPER(district)='GICUMBI' AND UPPER(sector)='RUKOMO'",
                        out_fields="objectid", return_geometry=True)
    geometry = {"rings": [r for item in area.features for r in item.geometry.get("rings", [])],
                "spatialReference": area.spatial_reference}
    cross_filter = intersects(geometry, sr=area.spatial_reference)
    inside_filter = contains(geometry, sr=area.spatial_reference)
    transformer_where = "ASSETGROUP=12 AND UPPER(Transfomer_name_)='MBURAMAZI TRF'"
    transformer_set = transformers.query(where=transformer_where,
                                         out_fields="OBJECTID,GLOBALID,Transfomer_name_,ASSETGROUP,ASSETTYPE",
                                         return_geometry=True, return_all_records=True)
    local_set = transformers.query(where=transformer_where, geometry_filter=cross_filter,
                                   out_fields="OBJECTID,GLOBALID,Transfomer_name_",
                                   return_geometry=False, return_all_records=True)
    line_where = "ASSETGROUP IN (9,10) AND UPPER(Transformer_Name)='MBURAMAZI TRF'"
    fields = [f.get("name") for f in lines.properties.fields]
    selected = [f for f in fields if f.casefold() in {
        "objectid", "globalid", "assetgroup", "transformer_name", "sector", "created_date",
        "shape__length", "lv_feeder_name", "feedername", "mvfeederid", "subnetworkname",
    }]
    line_set = lines.query(where=line_where, out_fields=",".join(selected),
                           return_geometry=False, return_all_records=True)
    cross_set = lines.query(where=line_where, geometry_filter=cross_filter,
                            out_fields="OBJECTID", return_geometry=False, return_all_records=True)
    inside_set = lines.query(where=line_where, geometry_filter=inside_filter,
                             out_fields="OBJECTID", return_geometry=False, return_all_records=True)
    cross_ids = {f.attributes["OBJECTID"] for f in cross_set.features}
    inside_ids = {f.attributes["OBJECTID"] for f in inside_set.features}
    rows = [f.attributes for f in line_set.features]
    ids = {row["OBJECTID"] for row in rows}
    dates = [row.get("created_date") for row in rows if isinstance(row.get("created_date"), (int,float))]
    facts = {
        "transformer_name": LABEL,
        "boundary": "Gicumbi / Rukomo",
        "national_transformer_count": len(transformer_set.features),
        "local_transformer_count": len(local_set.features),
        "transformer_objectids": [f.attributes["OBJECTID"] for f in transformer_set.features],
        "national_lv_line_count": len(rows),
        "intersecting_line_count": len(cross_ids),
        "inside_line_count": len(inside_ids),
        "outside_line_count": len(ids - cross_ids),
        "crossing_line_count": len(cross_ids - inside_ids),
        "recorded_sector_counts": dict(Counter(str(row.get("Sector") or "[Blank]") for row in rows)),
        "feeder_counts": dict(Counter(str(row.get("LV_Feeder_Name") or "[Blank]") for row in rows)),
        "earliest_created_utc": dt.datetime.fromtimestamp(min(dates)/1000, tz=dt.timezone.utc).isoformat() if dates else None,
        "latest_created_utc": dt.datetime.fromtimestamp(max(dates)/1000, tz=dt.timezone.utc).isoformat() if dates else None,
        "line_field_candidates": [f for f in fields if any(t in f.casefold() for t in ("transform", "global", "feeder", "terminal", "subnetwork"))],
    }
    Path(__file__).with_name("mburamazi_trf_facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    print(json.dumps(facts, indent=2))


if __name__ == "__main__":
    main()

"""ArcGIS Pro read-only natural-language query preview and filtered local map copy."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .asset_quality import ASSETS, domain_map
from .progress_report import (
    DEFAULT_BOUNDARY_SERVICE_URL, DEFAULT_LINE_SERVICE_URL,
    CELL_LAYER_ID, SECTOR_LAYER_ID, _get_gis, _layer_url,
)
from .smart_query import (
    ASSET_GROUPS, ASSET_LAYERS, EXAMPLES, boundary_where,
    compile_attribute_where, parse_request,
)

ACTIONS = ("preview", "local_copy")
MAX_COPY = 25000


def run_smart_query(
    request: str,
    mode: str = "preview",
    output_json: str | Path | None = None,
    service_url: str | None = None,
    boundary_service_url: str | None = None,
    version: str = "sde.DEFAULT",
    arcpy_module: Any = None,
    gis: Any = None,
) -> dict:
    """Interpret, validate live schema, preview and optionally copy selected data.

    No ExecuteSQL, raw user SQL, EditFeatures, DeleteFeatures, ApplyEdits or
    network topology operations. The only new features are a local scratch
    file-geodatabase copy, explicitly requested by the user.
    """
    if mode not in ACTIONS:
        raise ValueError("Mode must be 'preview' or 'local_copy'.")
    plan = parse_request(request)
    if arcpy_module is None:
        import arcpy as arcpy_module
    arcpy = arcpy_module
    from arcgis.features import FeatureLayer
    active_gis = _get_gis(gis)
    base = str(service_url or DEFAULT_LINE_SERVICE_URL).rstrip("/")
    boundary = str(boundary_service_url or DEFAULT_BOUNDARY_SERVICE_URL).rstrip("/")
    layer_url = _layer_url(base, ASSET_LAYERS[plan.asset])
    layer = FeatureLayer(layer_url, active_gis)
    live_fields = [dict(field) for field in layer.properties.fields]
    sub_domains = domain_map(layer.properties, ASSET_GROUPS[plan.asset][0])
    sql = compile_attribute_where(plan, live_fields, sub_domains)
    admin_sql = boundary_where(plan)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # GP layers are not published/edited. Names are unique within the session.
    layer_name = f"REPORTAPP_{plan.asset}_{stamp}"
    selected = None
    admin_lyr = None
    try:
        try:
            selected = arcpy.management.MakeFeatureLayer(
                layer_url, layer_name, sql
            ).getOutput(0)
        except Exception as exc:
            raise RuntimeError(
                "Unable to create a temporary FeatureServer query layer. "
                "Confirm ArcGIS Pro is signed into the REG portal, the "
                f"asset layer is accessible ({layer_url}), and the "
                f"verified query is supported: {sql}. Details: {exc}"
            ) from exc
        if admin_sql:
            boundary_layer_id = CELL_LAYER_ID if plan.cell else SECTOR_LAYER_ID
            boundary_url = _layer_url(boundary, boundary_layer_id)
            try:
                admin_lyr = arcpy.management.MakeFeatureLayer(
                    boundary_url, f"REPORTAPP_area_{stamp}", admin_sql
                ).getOutput(0)
                boundary_count = int(arcpy.management.GetCount(admin_lyr).getOutput(0))
                if boundary_count < 1:
                    raise ValueError(
                        "The selected district/sector/cell has no verified administrative boundary."
                    )
                arcpy.management.SelectLayerByLocation(
                    selected, "INTERSECT", admin_lyr, selection_type="NEW_SELECTION"
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Could not apply spatial filtering with official boundaries "
                    f"(source: {boundary_url}; query: {admin_sql}). "
                    f"No unfiltered results will be shown. Details: {exc}"
                ) from exc

        count = int(arcpy.management.GetCount(selected).getOutput(0))
        result = {
            "read_only_feature_service": True,
            "input_request": request,
            "interpreted": plan.serialize(),
            "feature_service": layer_url,
            "network_version_requested": version,
            "attribute_sql": sql,
            "spatial_boundary_sql": admin_sql,
            "boundary_service": boundary if admin_sql else None,
            "matched_features": count,
            "mode": mode,
            "local_feature_class": None,
            "added_to_map": False,
            "cautions": [
                "The REG Utility Network FeatureServer is never modified.",
                "Current VERSION must be checked against the ArcGIS map/service: "
                "this ArcPy map-filter workflow uses the connected feature "
                "layer's configured version, not a REST gdb_version override.",
                "Selected geographic polygons use spatial intersections; border features may belong to multiple administrative areas.",
                "Manufacturer missing means the attribute is blank: a documented no-nameplate exception is evaluated by Watch LV Pole Data Quality.",
            ],
        }
        if plan.pamela_team:
            result["cautions"].append(
                "Kwizerwa Edison now uses maniraguhatheogene01; earlier activity "
                "may belong to the prior account holder Manzi Intime."
            )
        if mode == "local_copy":
            if count > MAX_COPY:
                raise ValueError(
                    f"{count:,} features match, exceeding the {MAX_COPY:,} "
                    "local-copy safety limit. Narrow the query by district, sector, "
                    "surveyor or attribute and try again. No records were modified."
                )
            # Local output is intentionally separate from network source data.
            gdb = getattr(arcpy.env, "scratchGDB", None)
            if not gdb:
                raise RuntimeError("ArcGIS scratchGDB is not available for local filtered copies.")
            output_fc = str(arcpy.CreateUniqueName(f"REPORTAPP_{plan.asset}_query", gdb))
            arcpy.management.CopyFeatures(selected, output_fc)
            actual = int(arcpy.management.GetCount(output_fc).getOutput(0))
            if actual != count:
                try:
                    arcpy.management.Delete(output_fc)
                except Exception:
                    pass
                raise RuntimeError(
                    f"Filtered copy changed in transit: expected {count}, "
                    f"copied {actual}; local incomplete output removed."
                )
            result["local_feature_class"] = output_fc
            try:
                current = arcpy.mp.ArcGISProject("CURRENT")
                active_map = current.activeMap
                if active_map is not None:
                    active_map.addDataFromPath(output_fc)
                    result["added_to_map"] = True
            except Exception as exc:
                result["cautions"].append(
                    "Local data were created but not added automatically "
                    f"to the map: {exc}. Add this feature class manually."
                )
        if output_json:
            out = Path(output_json).expanduser().resolve()
            if out.suffix.casefold() != ".json":
                raise ValueError("Audit log path must have .json extension.")
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists():
                raise FileExistsError(f"Audit log already exists: {out}")
            out.write_text(
                json.dumps(result, ensure_ascii=False, indent=2)+"\n",
                encoding="utf-8",
            )
            result["audit_log"] = str(out)
        return result
    finally:
        # Clean only temporary layers we own, never user map layers or
        # source data. Local scratch copy is retained for display.
        for obj in (admin_lyr, selected):
            if obj is not None:
                try:
                    arcpy.management.Delete(obj)
                except Exception:
                    pass

"""Rule-aware substation containment preview and controlled application.

The workflow mirrors the proven Kibuye hierarchy:

* a transmission-substation Structure Boundary contains Electric Bay boundaries;
* each Electric Bay contains only Electric Device asset types permitted by the
  live utility-network containment rules;
* spatial overlap alone never creates an association.

Preview is the normal mode. Applying associations is a separate explicit mode
and writes through FeatureServer/applyEdits rather than editing the
associations table directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .progress_report import (
    CELL_LAYER_ID,
    DEFAULT_BOUNDARY_SERVICE_URL,
    SECTOR_LAYER_ID,
    _combined_boundary_geometry,
    _get_gis,
    _get_sector_features,
    _layer_url,
    _query_with_retry,
    load_province_index,
)


DEFAULT_SUBSTATION_SERVICE_URL = (
    "https://gisweb.reg.rw/server/rest/services/"
    "REG_UN_Service__/FeatureServer"
)

KIGALI_MODE = "Kigali City (Gasabo, Kicukiro and Nyarugenge)"
PROVINCE_MODE = "Selected province"
ADMIN_MODE = "Selected district / sector / cell"
CUSTOM_MODE = "Custom drawn boundary"
AREA_MODES = [KIGALI_MODE, PROVINCE_MODE, ADMIN_MODE, CUSTOM_MODE]

PREVIEW_MODE = "Preview only"
APPLY_MODE = "Apply approved proposals"
OPERATION_MODES = [PREVIEW_MODE, APPLY_MODE]

STRUCTURE_BOUNDARY_LAYER_ID = 13
ELECTRIC_DEVICE_LAYER_ID = 5
UTILITY_NETWORK_LAYER_ID = 14
ASSOCIATIONS_TABLE_ID = 500001
RULES_TABLE_ID = 500003

# Network source IDs are utility-network schema identifiers, not layer IDs.
STRUCTURE_BOUNDARY_SOURCE_ID = 6
ELECTRIC_DEVICE_SOURCE_ID = 16

MAIN_SUBSTATION_ASSET_GROUP = 2
ELECTRIC_BAY_ASSET_GROUP = 4
CONTAINMENT_RULE_TYPE = 2
CONTAINMENT_ASSOCIATION_TYPE = 2

PLACEHOLDER_SUBSTATION_IDS = {
    "",
    "UNKNOWN",
    "UNKNOWN_SS",
    "OTHER",
    "OTHERS",
    "OTHERS_SS",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_BUILDER = PROJECT_ROOT / "spreadsheet_runtime" / "containment_report.mjs"
DEFAULT_REPORT_NODE = (
    Path.home()
    / ".cache"
    / "codex-runtimes"
    / "codex-primary-runtime"
    / "dependencies"
    / "node"
    / "bin"
    / "node.exe"
)


def normalize_guid(value: Any) -> str:
    """Return a stable uppercase GUID representation for comparisons."""
    return str(value or "").strip().upper()


def _normal_text(value: Any) -> str:
    return str(value or "").strip()


def _normal_substation_id(value: Any) -> str:
    return _normal_text(value).upper()


def _bay_label(attributes: dict[str, Any]) -> str:
    """Return the best human-readable bay label available in the live schema."""
    for id_field, name_field in (
        ("Line_Bay_ID", "Line_Bay_Name"),
        ("Trx_Bay_ID", "Trx_Bay_Name"),
    ):
        bay_id = _normal_text(attributes.get(id_field))
        bay_name = _normal_text(attributes.get(name_field))
        if bay_id and bay_name:
            return f"{bay_id} - {bay_name}"
        if bay_name:
            return bay_name
        if bay_id:
            return bay_id
    for field in ("Name", "Bay_ID", "assetid"):
        value = _normal_text(attributes.get(field))
        if value:
            return value
    return f"Bay record {attributes.get('OBJECTID', '')}".strip()


def _substation_label(attributes: dict[str, Any]) -> str:
    value = _normal_substation_id(attributes.get("Substation_ID"))
    if value:
        return value
    return f"Substation record {attributes.get('OBJECTID', '')}".strip()


def _report_substation(value: Any) -> str:
    normalized = _normal_substation_id(value)
    if normalized in PLACEHOLDER_SUBSTATION_IDS:
        return "UNIDENTIFIED SUBSTATION"
    return normalized


def _sql_text(value: Any) -> str:
    return str(value).replace("'", "''")


def _chunks(values: Sequence[str], size: int = 100) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _subtype_maps(layer: Any) -> tuple[dict[int, str], dict[tuple[int, int], str]]:
    group_names: dict[int, str] = {}
    type_names: dict[tuple[int, int], str] = {}
    for group in layer.properties.get("types", []):
        group_code = int(group.get("id"))
        group_names[group_code] = str(group.get("name") or group_code)
        coded_values = (
            group.get("domains", {})
            .get("ASSETTYPE", {})
            .get("codedValues", [])
        )
        for item in coded_values:
            type_names[(group_code, int(item["code"]))] = str(item["name"])
    return group_names, type_names


def _feature_attributes(feature: Any) -> dict[str, Any]:
    attributes = getattr(feature, "attributes", None)
    if attributes is not None:
        return dict(attributes)
    return dict(feature.get("attributes", {}))


def _feature_geometry(feature: Any) -> dict[str, Any] | None:
    geometry = getattr(feature, "geometry", None)
    if geometry is not None:
        return dict(geometry)
    value = feature.get("geometry")
    return dict(value) if value else None


def classify_association(
    container_guid: str,
    legal_rule: bool,
    existing_containers: Sequence[str] | None = None,
    ambiguity_reason: str | None = None,
) -> tuple[str, str]:
    """Classify one candidate without performing any network edit."""
    if ambiguity_reason:
        return "REVIEW", ambiguity_reason
    if not legal_rule:
        return "REVIEW", "No legal containment rule for this asset-type pair"

    wanted = normalize_guid(container_guid)
    existing = {normalize_guid(item) for item in existing_containers or [] if item}
    if wanted in existing and len(existing) == 1:
        return "EXISTING", "Association already exists"
    if wanted in existing and len(existing) > 1:
        return "CONFLICT", "Content is associated with multiple containers"
    if existing:
        return "CONFLICT", "Content already belongs to a different container"
    return "PROPOSE", "Legal, spatially unambiguous, and not already contained"


def build_apply_edits(
    rows: Sequence[dict[str, Any]],
    associations_table_id: int = ASSOCIATIONS_TABLE_ID,
) -> list[dict[str, Any]]:
    """Build the service-level applyEdits payload for proposed rows only."""
    adds = []
    for row in rows:
        if row.get("status") != "PROPOSE":
            continue
        adds.append(
            {
                "attributes": {
                    "fromNetworkSourceId": int(row["_from_source_id"]),
                    "fromGlobalId": row["container_globalid"],
                    "fromTerminalId": -1,
                    "toNetworkSourceId": int(row["_to_source_id"]),
                    "toGlobalId": row["content_globalid"],
                    "toTerminalId": -1,
                    # This Enterprise 11.4 associations table exposes the
                    # Association Type field as a coded integer.  Sending the
                    # descriptive string is rejected with error 400.
                    "associationType": CONTAINMENT_ASSOCIATION_TYPE,
                    "isContentVisible": 1,
                }
            }
        )
    return [{"id": int(associations_table_id), "adds": adds}] if adds else []


def _area_geometry(
    gis: Any,
    area_mode: str,
    province: str | None,
    district: str | None,
    sectors: Sequence[str] | None,
    cells: Sequence[str] | None,
    custom_boundary_geometry: dict[str, Any] | None,
    boundary_service_url: str,
) -> tuple[dict[str, Any], str]:
    from arcgis.features import FeatureLayer

    if custom_boundary_geometry is not None:
        return custom_boundary_geometry, "Custom drawn boundary"
    if area_mode == CUSTOM_MODE:
        raise ValueError("Draw at least one polygon for Custom drawn boundary mode.")

    sector_layer = FeatureLayer(
        _layer_url(boundary_service_url, SECTOR_LAYER_ID), gis
    )
    cell_layer = FeatureLayer(
        _layer_url(boundary_service_url, CELL_LAYER_ID), gis
    )

    if area_mode == PROVINCE_MODE:
        clean_province = _normal_text(province)
        if not clean_province:
            raise ValueError("Choose a province.")
        province_index = load_province_index()
        matched_province = next(
            (
                name
                for name in province_index
                if name.casefold() == clean_province.casefold()
            ),
            None,
        )
        if matched_province is None:
            raise ValueError(f"Province not found in the Rwanda index: {clean_province}")
        districts = province_index[matched_province]
        district_sql = ",".join(f"'{_sql_text(item.upper())}'" for item in districts)
        feature_set = _query_with_retry(
            sector_layer,
            where=f"UPPER(district) IN ({district_sql})",
            out_fields="objectid,district,sector",
            return_geometry=True,
        )
        if not feature_set.features:
            raise ValueError(
                f"No administrative boundaries were found for {matched_province}."
            )
        return _combined_boundary_geometry(feature_set), matched_province

    if area_mode == KIGALI_MODE:
        feature_set = _query_with_retry(
            sector_layer,
            where="UPPER(district) IN ('GASABO','KICUKIRO','NYARUGENGE')",
            out_fields="objectid,district,sector",
            return_geometry=True,
        )
        if not feature_set.features:
            raise ValueError("The Kigali City administrative boundaries were not found.")
        geometry = _combined_boundary_geometry(feature_set)
        return geometry, KIGALI_MODE

    clean_district = _normal_text(district)
    if not clean_district:
        raise ValueError("Choose a district or draw a custom boundary.")
    feature_set = _get_sector_features(
        sector_layer,
        clean_district,
        sectors or [],
        cell_layer,
        cells or [],
    )
    geometry = _combined_boundary_geometry(feature_set)
    clean_sectors = [_normal_text(item) for item in sectors or [] if _normal_text(item)]
    clean_cells = [_normal_text(item) for item in cells or [] if _normal_text(item)]
    if clean_cells:
        label = f"{clean_district} / {', '.join(clean_sectors)} / {', '.join(clean_cells)}"
    elif clean_sectors:
        label = f"{clean_district} / {', '.join(clean_sectors)}"
    else:
        label = f"{clean_district} / all sectors"
    return geometry, label


def _query_existing_containers(
    association_layer: Any,
    content_guids: Sequence[str],
    version: str,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    unique = sorted({normalize_guid(item) for item in content_guids if item})
    for chunk in _chunks(unique):
        quoted = ",".join(f"'{_sql_text(item)}'" for item in chunk)
        feature_set = _query_with_retry(
            association_layer,
            where=(
                f"ASSOCIATIONTYPE = {CONTAINMENT_ASSOCIATION_TYPE} "
                f"AND TOGLOBALID IN ({quoted})"
            ),
            out_fields="FROMGLOBALID,TOGLOBALID,ERRORCODE,STATUS",
            return_geometry=False,
            gdb_version=version,
        )
        for feature in feature_set.features:
            attributes = _feature_attributes(feature)
            # A newly added valid association has STATUS 56 until network
            # topology is validated. Bits 0-2 indicate that the association,
            # From feature, or To feature has been deleted; bits 3-5 only mark
            # the live association and participants as dirty.
            status = int(attributes.get("STATUS") or 0)
            error_code = int(attributes.get("ERRORCODE") or 0)
            if status & 7 or error_code:
                continue
            content = normalize_guid(attributes.get("TOGLOBALID"))
            container = normalize_guid(attributes.get("FROMGLOBALID"))
            if content and container:
                result[content].append(container)
    return result


def _legal_rules(rule_layer: Any, version: str) -> set[tuple[int, int, int, int, int, int]]:
    feature_set = _query_with_retry(
        rule_layer,
        where=(
            f"RULETYPE = {CONTAINMENT_RULE_TYPE} "
            f"AND FROMNETWORKSOURCEID = {STRUCTURE_BOUNDARY_SOURCE_ID} "
            f"AND TONETWORKSOURCEID IN "
            f"({STRUCTURE_BOUNDARY_SOURCE_ID},{ELECTRIC_DEVICE_SOURCE_ID})"
        ),
        out_fields=(
            "FROMNETWORKSOURCEID,FROMASSETGROUP,FROMASSETTYPE,"
            "TONETWORKSOURCEID,TOASSETGROUP,TOASSETTYPE"
        ),
        return_geometry=False,
        gdb_version=version,
    )
    return {
        (
            int(attrs["FROMNETWORKSOURCEID"]),
            int(attrs["FROMASSETGROUP"]),
            int(attrs["FROMASSETTYPE"]),
            int(attrs["TONETWORKSOURCEID"]),
            int(attrs["TOASSETGROUP"]),
            int(attrs["TOASSETTYPE"]),
        )
        for attrs in (_feature_attributes(feature) for feature in feature_set.features)
    }


def _as_shape(geometry: dict[str, Any]) -> Any:
    import arcpy

    return arcpy.AsShape(geometry, True)


def _point_inside(polygon_shape: Any, point_geometry: dict[str, Any]) -> bool:
    point = _as_shape(point_geometry)
    return bool(polygon_shape.contains(point) or polygon_shape.touches(point))


def _polygon_centroid_inside(container_shape: Any, content_shape: Any) -> bool:
    centroid = content_shape.centroid
    return bool(container_shape.contains(centroid) or container_shape.touches(centroid))


def _asset_names(
    attributes: dict[str, Any],
    group_names: dict[int, str],
    type_names: dict[tuple[int, int], str],
) -> tuple[int, str, int, str]:
    group = int(attributes.get("ASSETGROUP") or 0)
    asset_type = int(attributes.get("ASSETTYPE") or 0)
    return (
        group,
        group_names.get(group, str(group)),
        asset_type,
        type_names.get((group, asset_type), str(asset_type)),
    )


def _row(
    *,
    area_label: str,
    substation_id: str,
    level: str,
    container_layer: str,
    container: Any,
    container_names: tuple[int, str, int, str],
    container_label: str,
    content_layer: str,
    content: Any,
    content_names: tuple[int, str, int, str],
    content_label: str,
    content_asset_id: str,
    spatial_container_count: int,
    legal_rule: bool,
    existing_containers: Sequence[str],
    ambiguity_reason: str | None,
    from_source_id: int,
    to_source_id: int,
) -> dict[str, Any]:
    container_attrs = _feature_attributes(container)
    content_attrs = _feature_attributes(content)
    container_guid = normalize_guid(container_attrs.get("GLOBALID"))
    status, reason = classify_association(
        container_guid,
        legal_rule,
        existing_containers,
        ambiguity_reason,
    )
    return {
        "proposal_id": "",
        "status": status,
        "reason": reason,
        "area": area_label,
        "substation_id": substation_id,
        "level": level,
        "container_layer": container_layer,
        "container_objectid": container_attrs.get("OBJECTID"),
        "container_globalid": container_guid,
        "container_asset_group": container_names[0],
        "container_asset_group_name": container_names[1],
        "container_asset_type": container_names[2],
        "container_asset_type_name": container_names[3],
        "_container_label": container_label,
        "content_layer": content_layer,
        "content_objectid": content_attrs.get("OBJECTID"),
        "content_globalid": normalize_guid(content_attrs.get("GLOBALID")),
        "content_asset_id": content_asset_id,
        "content_asset_group": content_names[0],
        "content_asset_group_name": content_names[1],
        "content_asset_type": content_names[2],
        "content_asset_type_name": content_names[3],
        "_content_label": content_label,
        "spatial_container_count": spatial_container_count,
        "current_container_globalids": "; ".join(existing_containers),
        "rule_matched": "YES" if legal_rule else "NO",
        "_from_source_id": from_source_id,
        "_to_source_id": to_source_id,
    }


def _report_containment_rows(
    rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    report_rows = []
    for number, row in enumerate(rows, start=1):
        substation_to_bay = row["level"] == "Substation > Bay"
        report_rows.append(
            {
                "No.": number,
                "Substation": _report_substation(row["substation_id"]),
                "Association Level": row["level"],
                "Bay": (
                    row["_content_label"]
                    if substation_to_bay
                    else row["_container_label"]
                ),
                "Record ID": row["content_objectid"],
                "Asset ID": row["content_asset_id"],
                "Asset Group": row["content_asset_group_name"],
                "Asset Type": row["content_asset_type_name"],
                "Status": row["status"],
                "Assessment": row["reason"],
            }
        )
    return report_rows


def _report_missing_rule_rows(
    rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "No.": number,
            "Substation": _report_substation(row["substation_id"]),
            "Bay": row["bay_label"],
            "Bay Type": row["bay_asset_type_name"],
            "Equipment Record ID": row["device_objectid"],
            "Asset ID": row["device_asset_id"],
            "Equipment Group": row["device_asset_group_name"],
            "Equipment Type": row["device_asset_type_name"],
            "Spatial Bay Count": row["spatial_bay_count"],
            "Required Rule": row["required_rule"],
        }
        for number, row in enumerate(rows, start=1)
    ]


def _write_excel_report(
    path: str | Path,
    *,
    area: str,
    operation: str,
    version: str,
    substations: Sequence[str],
    rows: Sequence[dict[str, Any]],
    missing_rule_rows: Sequence[dict[str, Any]],
) -> str:
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    target.parent.mkdir(parents=True, exist_ok=True)

    node_path = Path(
        os.environ.get("CUSTOMER_METER_PHOTO_QA_NODE", str(DEFAULT_REPORT_NODE))
    )
    if not node_path.is_file():
        raise RuntimeError(
            "The bundled spreadsheet runtime is unavailable. Expected Node.js at "
            f"{node_path}"
        )
    if not REPORT_BUILDER.is_file():
        raise RuntimeError(f"Containment report builder not found: {REPORT_BUILDER}")

    payload = {
        "area": area,
        "operation": operation,
        "version": version,
        "generatedAt": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "substations": list(substations),
        "containmentRows": _report_containment_rows(rows),
        "missingRuleRows": _report_missing_rule_rows(missing_rule_rows),
    }
    with tempfile.TemporaryDirectory(prefix="substation_containment_report_") as temp:
        payload_path = Path(temp) / "report.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                str(node_path),
                str(REPORT_BUILDER),
                str(payload_path),
                str(target),
            ],
            cwd=str(REPORT_BUILDER.parent),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    if completed.returncode:
        details = (completed.stderr or completed.stdout or "Unknown error").strip()
        raise RuntimeError(f"Excel containment report could not be created: {details}")
    if not target.is_file():
        raise RuntimeError(f"Excel containment report was not created: {target}")
    return str(target)


def _apply_associations(
    gis: Any,
    service_url: str,
    version: str,
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    edits = build_apply_edits(rows)
    if not edits:
        return {"requested": 0, "succeeded": 0, "failed": 0, "response": []}

    response = gis._con.post(
        f"{service_url.rstrip('/')}/applyEdits",
        {
            "f": "json",
            "edits": json.dumps(edits),
            "gdbVersion": version,
            "useGlobalIds": "true",
            "rollbackOnFailure": "true",
            "returnEditMoment": "true",
        },
    )
    if isinstance(response, dict) and response.get("error"):
        raise RuntimeError(f"Association applyEdits failed: {response['error']}")
    response_items = response if isinstance(response, list) else [response]
    add_results = []
    for item in response_items:
        if isinstance(item, dict):
            add_results.extend(item.get("addResults") or [])

    proposed_rows = [row for row in rows if row.get("status") == "PROPOSE"]
    for index, row in enumerate(proposed_rows):
        result = add_results[index] if index < len(add_results) else {}
        if result.get("success") is True:
            row["status"] = "APPLIED"
            row["reason"] = "Association created successfully"
        else:
            row["status"] = "FAILED"
            error = result.get("error") or "No add result returned"
            row["reason"] = f"Association was not created: {error}"

    succeeded = sum(item.get("success") is True for item in add_results)
    return {
        "requested": len(proposed_rows),
        "succeeded": succeeded,
        "failed": len(proposed_rows) - succeeded,
        "response": response,
    }


def run_substation_containment(
    output_xlsx: str | Path,
    area_mode: str = KIGALI_MODE,
    province: str | None = None,
    district: str | None = None,
    sectors: Sequence[str] | None = None,
    cells: Sequence[str] | None = None,
    custom_boundary_geometry: dict[str, Any] | None = None,
    operation: str = PREVIEW_MODE,
    apply_confirmation: str | None = None,
    service_url: str | None = None,
    boundary_service_url: str | None = None,
    version: str = "sde.DEFAULT",
    gis: Any | None = None,
) -> dict[str, Any]:
    """Preview or apply rule-valid containment associations in a selected area."""
    from arcgis.features import FeatureLayer
    from arcgis.geometry.filters import contains

    if area_mode not in AREA_MODES:
        raise ValueError(f"Unsupported area mode: {area_mode}")
    if operation not in OPERATION_MODES:
        raise ValueError(f"Unsupported operation: {operation}")
    # ``apply_confirmation`` is retained only for backward compatibility with
    # older callers. Choosing Apply approved proposals is the explicit action.

    active_gis = _get_gis(gis)
    active_service = service_url or os.environ.get(
        "UN_SUBSTATION_SERVICE_URL", DEFAULT_SUBSTATION_SERVICE_URL
    )
    active_boundaries = boundary_service_url or os.environ.get(
        "UN_SECTOR_BOUNDARY_URL", DEFAULT_BOUNDARY_SERVICE_URL
    )
    area_geometry, area_label = _area_geometry(
        active_gis,
        area_mode,
        province,
        district,
        sectors,
        cells,
        custom_boundary_geometry,
        active_boundaries,
    )

    structure_layer = FeatureLayer(
        _layer_url(active_service, STRUCTURE_BOUNDARY_LAYER_ID), active_gis
    )
    device_layer = FeatureLayer(
        _layer_url(active_service, ELECTRIC_DEVICE_LAYER_ID), active_gis
    )
    association_layer = FeatureLayer(
        _layer_url(active_service, ASSOCIATIONS_TABLE_ID), active_gis
    )
    rule_layer = FeatureLayer(_layer_url(active_service, RULES_TABLE_ID), active_gis)

    geometry_filter = contains(
        area_geometry, sr=area_geometry.get("spatialReference", {})
    )
    structure_set = _query_with_retry(
        structure_layer,
        where=(
            f"ASSETGROUP IN ({MAIN_SUBSTATION_ASSET_GROUP},"
            f"{ELECTRIC_BAY_ASSET_GROUP})"
        ),
        out_fields=(
            "OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,ASSOCIATIONSTATUS,"
            "Substation_ID,Substation_Name,Name,Line_Bay_ID,Line_Bay_Name,"
            "Trx_Bay_ID,Trx_Bay_Name,Bay_ID,assetid"
        ),
        return_geometry=True,
        geometry_filter=geometry_filter,
        gdb_version=version,
    )
    device_set = _query_with_retry(
        device_layer,
        where="ASSETGROUP IS NOT NULL AND ASSETTYPE IS NOT NULL",
        out_fields=(
            "OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,ASSOCIATIONSTATUS,"
            "Substation_ID,AssetIDs"
        ),
        return_geometry=True,
        geometry_filter=geometry_filter,
        gdb_version=version,
    )

    structures = list(structure_set.features)
    devices = list(device_set.features)
    mains = [
        feature
        for feature in structures
        if int(_feature_attributes(feature).get("ASSETGROUP") or 0)
        == MAIN_SUBSTATION_ASSET_GROUP
    ]
    bays = [
        feature
        for feature in structures
        if int(_feature_attributes(feature).get("ASSETGROUP") or 0)
        == ELECTRIC_BAY_ASSET_GROUP
    ]

    structure_group_names, structure_type_names = _subtype_maps(structure_layer)
    device_group_names, device_type_names = _subtype_maps(device_layer)
    legal_rules = _legal_rules(rule_layer, version)
    if not legal_rules:
        raise RuntimeError("No live containment rules were returned; preview stopped safely.")

    main_shapes = {
        normalize_guid(_feature_attributes(feature).get("GLOBALID")): _as_shape(
            _feature_geometry(feature)
        )
        for feature in mains
    }
    bay_shapes = {
        normalize_guid(_feature_attributes(feature).get("GLOBALID")): _as_shape(
            _feature_geometry(feature)
        )
        for feature in bays
    }

    bay_contexts: dict[str, dict[str, Any]] = {}
    for bay in bays:
        bay_attrs = _feature_attributes(bay)
        bay_guid = normalize_guid(bay_attrs.get("GLOBALID"))
        bay_shape = bay_shapes[bay_guid]
        bay_substation = _normal_substation_id(bay_attrs.get("Substation_ID"))
        spatial_mains = []
        exact_mains = []
        for main in mains:
            main_attrs = _feature_attributes(main)
            main_guid = normalize_guid(main_attrs.get("GLOBALID"))
            if not _polygon_centroid_inside(main_shapes[main_guid], bay_shape):
                continue
            spatial_mains.append(main)
            if _normal_substation_id(main_attrs.get("Substation_ID")) == bay_substation:
                exact_mains.append(main)

        ambiguity_reason = None
        chosen_main = exact_mains[0] if len(exact_mains) == 1 else None
        if bay_substation in PLACEHOLDER_SUBSTATION_IDS:
            ambiguity_reason = "Bay has a blank or placeholder Substation_ID"
        elif len(exact_mains) == 0:
            if spatial_mains:
                ambiguity_reason = "Bay is spatially inside a main boundary but Substation_ID does not match"
            else:
                ambiguity_reason = "No containing main substation boundary was found"
        elif len(exact_mains) > 1:
            ambiguity_reason = "Bay matches more than one main substation boundary"

        bay_contexts[bay_guid] = {
            "bay": bay,
            "substation_id": bay_substation,
            "chosen_main": chosen_main,
            "spatial_mains": spatial_mains,
            "ambiguity_reason": ambiguity_reason,
        }

    device_memberships: dict[str, list[Any]] = defaultdict(list)
    for device in devices:
        geometry = _feature_geometry(device)
        if not geometry:
            continue
        for bay in bays:
            bay_guid = normalize_guid(_feature_attributes(bay).get("GLOBALID"))
            if _point_inside(bay_shapes[bay_guid], geometry):
                device_memberships[
                    normalize_guid(_feature_attributes(device).get("GLOBALID"))
                ].append(bay)

    content_guids = [
        normalize_guid(_feature_attributes(feature).get("GLOBALID")) for feature in bays
    ] + list(device_memberships)
    existing_by_content = _query_existing_containers(
        association_layer, content_guids, version
    )

    rows: list[dict[str, Any]] = []
    missing_rule_rows: list[dict[str, Any]] = []
    for bay_guid, context in bay_contexts.items():
        bay = context["bay"]
        main = context["chosen_main"]
        if main is None:
            # A review row still needs a stable container. Use the sole spatial
            # main if available; otherwise use the bay itself as a visible
            # placeholder and make the reason explicit.
            main = context["spatial_mains"][0] if context["spatial_mains"] else bay
        main_attrs = _feature_attributes(main)
        bay_attrs = _feature_attributes(bay)
        main_names = _asset_names(
            main_attrs, structure_group_names, structure_type_names
        )
        bay_names = _asset_names(
            bay_attrs, structure_group_names, structure_type_names
        )
        legal = (
            STRUCTURE_BOUNDARY_SOURCE_ID,
            main_names[0],
            main_names[2],
            STRUCTURE_BOUNDARY_SOURCE_ID,
            bay_names[0],
            bay_names[2],
        ) in legal_rules
        row = _row(
            area_label=area_label,
            substation_id=context["substation_id"],
            level="Substation > Bay",
            container_layer="Structure Boundary",
            container=main,
            container_names=main_names,
            container_label=_substation_label(main_attrs),
            content_layer="Structure Boundary",
            content=bay,
            content_names=bay_names,
            content_label=_bay_label(bay_attrs),
            content_asset_id=_normal_text(bay_attrs.get("assetid")),
            spatial_container_count=len(context["spatial_mains"]),
            legal_rule=legal,
            existing_containers=existing_by_content.get(bay_guid, []),
            ambiguity_reason=context["ambiguity_reason"],
            from_source_id=STRUCTURE_BOUNDARY_SOURCE_ID,
            to_source_id=STRUCTURE_BOUNDARY_SOURCE_ID,
        )
        rows.append(row)

    device_by_guid = {
        normalize_guid(_feature_attributes(feature).get("GLOBALID")): feature
        for feature in devices
    }
    for device_guid, memberships in device_memberships.items():
        device = device_by_guid[device_guid]
        device_attrs = _feature_attributes(device)
        membership_guids = [
            normalize_guid(_feature_attributes(item).get("GLOBALID"))
            for item in memberships
        ]
        ambiguity_reason = None
        chosen_bay = memberships[0]
        if len(memberships) > 1:
            ambiguity_reason = "Device falls inside more than one bay boundary"

        bay_attrs = _feature_attributes(chosen_bay)
        bay_guid = membership_guids[0]
        bay_names = _asset_names(
            bay_attrs, structure_group_names, structure_type_names
        )
        device_names = _asset_names(
            device_attrs, device_group_names, device_type_names
        )
        legal = (
            STRUCTURE_BOUNDARY_SOURCE_ID,
            bay_names[0],
            bay_names[2],
            ELECTRIC_DEVICE_SOURCE_ID,
            device_names[0],
            device_names[2],
        ) in legal_rules
        context = bay_contexts[bay_guid]
        if not legal:
            missing_rule_rows.append(
                {
                    "area": area_label,
                    "substation_id": context["substation_id"],
                    "bay_objectid": bay_attrs.get("OBJECTID"),
                    "bay_label": _bay_label(bay_attrs),
                    "bay_asset_type": bay_names[2],
                    "bay_asset_type_name": bay_names[3],
                    "device_objectid": device_attrs.get("OBJECTID"),
                    "device_asset_id": _normal_text(device_attrs.get("AssetIDs")),
                    "device_asset_group": device_names[0],
                    "device_asset_group_name": device_names[1],
                    "device_asset_type": device_names[2],
                    "device_asset_type_name": device_names[3],
                    "spatial_bay_count": len(memberships),
                    "candidate_bays": "; ".join(
                        _bay_label(_feature_attributes(item)) for item in memberships
                    ),
                    "required_rule": (
                        f"Structure Boundary source {STRUCTURE_BOUNDARY_SOURCE_ID}, "
                        f"Electric Bay AG {bay_names[0]} AT {bay_names[2]} -> "
                        f"Electric Device source {ELECTRIC_DEVICE_SOURCE_ID}, "
                        f"AG {device_names[0]} AT {device_names[2]}"
                    ),
                }
            )
            continue
        rows.append(
            _row(
                area_label=area_label,
                substation_id=context["substation_id"],
                level="Bay > Device",
                container_layer="Structure Boundary",
                container=chosen_bay,
                container_names=bay_names,
                container_label=_bay_label(bay_attrs),
                content_layer="Electric Device",
                content=device,
                content_names=device_names,
                content_label=(
                    _normal_text(device_attrs.get("AssetIDs"))
                    or f"Equipment record {device_attrs.get('OBJECTID', '')}".strip()
                ),
                content_asset_id=_normal_text(device_attrs.get("AssetIDs")),
                spatial_container_count=len(memberships),
                legal_rule=legal,
                existing_containers=existing_by_content.get(device_guid, []),
                ambiguity_reason=ambiguity_reason,
                from_source_id=STRUCTURE_BOUNDARY_SOURCE_ID,
                to_source_id=ELECTRIC_DEVICE_SOURCE_ID,
            )
        )

    rows.sort(
        key=lambda item: (
            item["substation_id"],
            item["level"],
            int(item["container_objectid"] or 0),
            item["content_layer"],
            int(item["content_objectid"] or 0),
        )
    )
    proposal_number = 0
    for row in rows:
        if row["status"] == "PROPOSE":
            proposal_number += 1
            row["proposal_id"] = f"P{proposal_number:05d}"

    apply_result = {"requested": 0, "succeeded": 0, "failed": 0}
    if operation == APPLY_MODE:
        apply_result = _apply_associations(
            active_gis, active_service, version, rows
        )

    status_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        status_counts[row["status"]] += 1
    substation_ids = sorted(
        {
            _report_substation(item["substation_id"])
            for item in [*rows, *missing_rule_rows]
        }
        | {
            _report_substation(_feature_attributes(main).get("Substation_ID"))
            for main in mains
        }
    )
    output_path = _write_excel_report(
        output_xlsx,
        area=area_label,
        operation=operation,
        version=version,
        substations=substation_ids,
        rows=rows,
        missing_rule_rows=missing_rule_rows,
    )
    return {
        "output_xlsx": output_path,
        "missing_rules_sheet": "Missing Rules",
        "operation": operation,
        "area": area_label,
        "version": version,
        "service_url": active_service,
        "main_substation_boundaries": len(mains),
        "bay_boundaries": len(bays),
        "electric_devices_in_area": len(devices),
        "devices_inside_bays": len(device_memberships),
        "substations": substation_ids,
        "legal_containment_rules": len(legal_rules),
        "candidate_rows": len(rows),
        "missing_rule_equipment": len(missing_rule_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "apply_result": {
            key: value for key, value in apply_result.items() if key != "response"
        },
    }

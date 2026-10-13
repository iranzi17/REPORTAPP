"""Rule-aware Electric Relay connectivity preview and controlled application.

Relays are Electric Junction Objects. Their Bay_ID localizes a line or
transformer bay, while Digital Fault Recorders operate across a substation.
Only Electric Devices physically in scope and permitted by a live connectivity
rule are associated. Transformer differential relays use every configured
winding terminal allowed by the live rule.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .progress_report import (
    DEFAULT_BOUNDARY_SERVICE_URL,
    _get_gis,
    _layer_url,
    _query_with_retry,
)
from .substation_containment import (
    APPLY_MODE,
    AREA_MODES,
    ASSOCIATIONS_TABLE_ID,
    CUSTOM_MODE,
    DEFAULT_REPORT_NODE,
    DEFAULT_SUBSTATION_SERVICE_URL,
    ELECTRIC_DEVICE_LAYER_ID,
    KIGALI_MODE,
    OPERATION_MODES,
    PREVIEW_MODE,
    PROVINCE_MODE,
    RULES_TABLE_ID,
    STRUCTURE_BOUNDARY_LAYER_ID,
    _area_geometry,
    _as_shape,
    _bay_label,
    _chunks,
    _feature_attributes,
    _feature_geometry,
    _normal_text,
    _point_inside,
    _report_substation,
    _sql_text,
    _subtype_maps,
    normalize_guid,
)


ELECTRIC_DEVICE_SOURCE_ID = 16
ELECTRIC_JUNCTION_OBJECT_LAYER_ID = 22
ELECTRIC_JUNCTION_OBJECT_SOURCE_ID = 21
UTILITY_NETWORK_LAYER_ID = 14
ELECTRIC_BAY_ASSET_GROUP = 4
ELECTRIC_RELAY_ASSET_GROUP = 4
CONNECTION_RULE_TYPE = 1
CONNECTION_ASSOCIATION_TYPE = 1

DISTANCE_RELAY = 1
TRANSFORMER_DIFFERENTIAL_RELAY = 2
DIGITAL_FAULT_RECORDER = 3
LINE_OVERCURRENT_RELAY = 6
SUPPORTED_RELAY_TYPES = {
    DISTANCE_RELAY,
    TRANSFORMER_DIFFERENTIAL_RELAY,
    DIGITAL_FAULT_RECORDER,
    LINE_OVERCURRENT_RELAY,
}
TRANSFORMER_DEVICE_GROUPS = {11, 29}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_BUILDER = PROJECT_ROOT / "spreadsheet_runtime" / "relay_association_report.mjs"


def _name_key(value: Any) -> str:
    key = "".join(character for character in _normal_text(value).upper() if character.isalnum())
    return key[:-2] if key.endswith("SS") else key


def _asset_prefix(attributes: dict[str, Any]) -> str:
    value = _normal_text(attributes.get("assetid") or attributes.get("AssetID"))
    return value.upper().split("-EBAY", 1)[0]


def _relay_scope_fields(relay_type: int) -> tuple[str, ...]:
    if relay_type == TRANSFORMER_DIFFERENTIAL_RELAY:
        return ("Trx_Bay_ID", "Bay_ID")
    return ("Line_Bay_ID", "Bay_ID")


def resolve_relay_bay(
    relay_attributes: dict[str, Any],
    bay_features: Sequence[Any],
) -> tuple[list[Any], str | None, str]:
    """Resolve one relay to its operational bay using relay type precedence."""
    bay_id = _normal_text(relay_attributes.get("Bay_ID")).upper()
    if not bay_id:
        return [], None, "Relay has no Bay_ID"
    relay_type = int(relay_attributes.get("ASSETTYPE") or 0)
    substation_key = _name_key(relay_attributes.get("NameofSubstation"))
    if not substation_key:
        return [], None, "Relay has no substation name"

    exact = [
        feature
        for feature in bay_features
        if _name_key(_feature_attributes(feature).get("Substation_ID"))
        == substation_key
    ]
    fallback = [
        feature
        for feature in bay_features
        if _name_key(_asset_prefix(_feature_attributes(feature))) == substation_key
    ]
    substation_bays = exact if exact else fallback
    if not substation_bays:
        return [], None, "No bay boundary was found for the relay substation"

    for field in _relay_scope_fields(relay_type):
        matches = [
            feature
            for feature in substation_bays
            if _normal_text(_feature_attributes(feature).get(field)).upper() == bay_id
        ]
        if matches:
            if len(matches) == 1:
                return matches, field, f"Matched relay Bay_ID through {field}"
            return matches, field, f"More than one bay has {field} = {bay_id}"
    expected = " or ".join(_relay_scope_fields(relay_type))
    return [], None, f"No boundary has {expected} = {bay_id}"


def _connection_rules(rule_layer: Any, version: str) -> list[dict[str, Any]]:
    result = _query_with_retry(
        rule_layer,
        where=(
            f"RULETYPE = {CONNECTION_RULE_TYPE} AND "
            "((FROMNETWORKSOURCEID = 16 AND TONETWORKSOURCEID = 21 "
            "AND TOASSETGROUP = 4) OR "
            "(FROMNETWORKSOURCEID = 21 AND FROMASSETGROUP = 4 "
            "AND TONETWORKSOURCEID = 16))"
        ),
        out_fields=(
            "OBJECTID,RULETYPE,FROMNETWORKSOURCEID,FROMASSETGROUP,FROMASSETTYPE,"
            "FROMTERMINALID,TONETWORKSOURCEID,TOASSETGROUP,TOASSETTYPE,TOTERMINALID"
        ),
        return_geometry=False,
        gdb_version=version,
    )
    rules = []
    for feature in result.features:
        raw = _feature_attributes(feature)
        if int(raw.get("FROMNETWORKSOURCEID") or 0) == ELECTRIC_DEVICE_SOURCE_ID:
            device_group = int(raw.get("FROMASSETGROUP") or 0)
            device_type = int(raw.get("FROMASSETTYPE") or 0)
            device_terminal = int(raw.get("FROMTERMINALID") or 0)
            relay_type = int(raw.get("TOASSETTYPE") or 0)
            relay_terminal = int(raw.get("TOTERMINALID") or 0)
            direction = "device_to_relay"
        else:
            device_group = int(raw.get("TOASSETGROUP") or 0)
            device_type = int(raw.get("TOASSETTYPE") or 0)
            device_terminal = int(raw.get("TOTERMINALID") or 0)
            relay_type = int(raw.get("FROMASSETTYPE") or 0)
            relay_terminal = int(raw.get("FROMTERMINALID") or 0)
            direction = "relay_to_device"
        rules.append(
            {
                "rule_objectid": raw.get("OBJECTID"),
                "device_group": device_group,
                "device_type": device_type,
                "device_terminal": device_terminal,
                "relay_type": relay_type,
                "relay_terminal": relay_terminal,
                "direction": direction,
            }
        )
    return rules


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    return value if isinstance(value, list) else [value]


def _terminal_schema(gis: Any, service_url: str) -> dict[str, Any]:
    response = gis._con.get(
        f"{service_url.rstrip('/')}/queryDataElements",
        {"f": "json", "layers": f"[{UTILITY_NETWORK_LAYER_ID}]"},
    )
    if response.get("error"):
        raise RuntimeError(f"Utility Network terminal metadata failed: {response['error']}")
    elements = response.get("layerDataElements") or []
    if not elements:
        raise RuntimeError("Utility Network terminal metadata was not returned.")
    data_element = elements[0].get("dataElement") or {}

    terminal_names: dict[int, str] = {}
    configuration_terminals: dict[int, set[int]] = {}
    for configuration in data_element.get("terminalConfigurations") or []:
        config_id = int(configuration.get("terminalConfigurationId") or 0)
        ids = set()
        for terminal in _as_list(configuration.get("terminals")):
            terminal_id = int(terminal.get("terminalId") or 0)
            if terminal_id:
                ids.add(terminal_id)
                terminal_names[terminal_id] = str(
                    terminal.get("terminalName") or terminal_id
                )
        configuration_terminals[config_id] = ids

    asset_configuration: dict[tuple[int, int], int] = {}
    for domain in data_element.get("domainNetworks") or []:
        for source in [
            *_as_list(domain.get("junctionSources")),
            *_as_list(domain.get("edgeSources")),
        ]:
            if int(source.get("sourceId") or 0) != ELECTRIC_DEVICE_SOURCE_ID:
                continue
            for group in source.get("assetGroups") or []:
                group_code = int(group.get("assetGroupCode") or 0)
                for asset_type in group.get("assetTypes") or []:
                    asset_configuration[
                        (group_code, int(asset_type.get("assetTypeCode") or 0))
                    ] = int(asset_type.get("terminalConfigurationId") or 0)
    if not terminal_names or not asset_configuration:
        raise RuntimeError("Utility Network terminal assignments are incomplete.")
    return {
        "terminal_names": terminal_names,
        "configuration_terminals": configuration_terminals,
        "asset_configuration": asset_configuration,
    }


def _allowed_rules_for_pair(
    rules_by_pair: dict[tuple[int, int, int], list[dict[str, Any]]],
    relay_type: int,
    device_attributes: dict[str, Any],
    terminal_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    group = int(device_attributes.get("ASSETGROUP") or 0)
    asset_type = int(device_attributes.get("ASSETTYPE") or 0)
    rules = list(rules_by_pair.get((relay_type, group, asset_type), []))
    if not rules:
        return []
    configuration_id = terminal_schema["asset_configuration"].get((group, asset_type))
    configured_terminals = terminal_schema["configuration_terminals"].get(
        configuration_id, set()
    )
    return [
        rule
        for rule in rules
        if rule["device_terminal"] in configured_terminals
        or (configuration_id == 0 and rule["device_terminal"] == 1)
    ]


def _query_existing_connections(
    association_layer: Any,
    relay_guids: Sequence[str],
    version: str,
) -> set[tuple[str, int, str, int]]:
    relay_set = {normalize_guid(item) for item in relay_guids if item}
    result: set[tuple[str, int, str, int]] = set()
    for guid_chunk in _chunks(sorted(relay_set), 40):
        quoted = ",".join(f"'{_sql_text(item)}'" for item in guid_chunk)
        feature_set = _query_with_retry(
            association_layer,
            where=(
                f"ASSOCIATIONTYPE = {CONNECTION_ASSOCIATION_TYPE} AND "
                f"(FROMGLOBALID IN ({quoted}) OR TOGLOBALID IN ({quoted}))"
            ),
            out_fields=(
                "FROMGLOBALID,FROMTERMINALID,TOGLOBALID,TOTERMINALID,"
                "ASSOCIATIONTYPE,STATUS,ERRORCODE"
            ),
            return_geometry=False,
            gdb_version=version,
        )
        for feature in feature_set.features:
            attrs = _feature_attributes(feature)
            if int(attrs.get("STATUS") or 0) & 7 or int(attrs.get("ERRORCODE") or 0):
                continue
            from_guid = normalize_guid(attrs.get("FROMGLOBALID"))
            to_guid = normalize_guid(attrs.get("TOGLOBALID"))
            if from_guid in relay_set:
                key = (
                    from_guid,
                    int(attrs.get("FROMTERMINALID") or 0),
                    to_guid,
                    int(attrs.get("TOTERMINALID") or 0),
                )
            elif to_guid in relay_set:
                key = (
                    to_guid,
                    int(attrs.get("TOTERMINALID") or 0),
                    from_guid,
                    int(attrs.get("FROMTERMINALID") or 0),
                )
            else:
                continue
            result.add(key)
    return result


def _device_asset_id(attributes: dict[str, Any]) -> str:
    for field in (
        "AssetID",
        "AssetIDs",
        "CircuitBreakerID",
        "CurrentTransfomer_ID",
        "VoltageTransfomer_ID",
        "transfomerID",
    ):
        value = _normal_text(attributes.get(field))
        if value:
            return value
    return ""


def _report_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for number, row in enumerate(rows, start=1):
        result.append(
            {
                "No.": number,
                "Substation": row["substation"],
                "Relay Record ID": row["relay_objectid"],
                "Relay Type": row["relay_type_name"],
                "Relay Description": row["relay_description"],
                "Relay Bay ID": row["relay_bay_id"],
                "Matched Scope": row["matched_scope"],
                "Bay": row["bay_label"],
                "Equipment Record ID": row["device_objectid"],
                "Equipment Asset ID": row["device_asset_id"],
                "Equipment Group": row["device_group_name"],
                "Equipment Type": row["device_type_name"],
                "Equipment Terminal": row["device_terminal_label"],
                "Relay Terminal": row["relay_terminal_label"],
                "Status": row["status"],
                "Assessment": row["reason"],
            }
        )
    return result


def _report_exceptions(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "No.": number,
            "Substation": row.get("substation", ""),
            "Relay Record ID": row.get("relay_objectid", ""),
            "Relay Type": row.get("relay_type_name", ""),
            "Relay Bay ID": row.get("relay_bay_id", ""),
            "Status": row.get("status", "REVIEW"),
            "Assessment": row.get("reason", ""),
        }
        for number, row in enumerate(rows, start=1)
    ]


def _write_excel_report(
    output_xlsx: str | Path,
    *,
    area: str,
    operation: str,
    version: str,
    substations: Sequence[str],
    rows: Sequence[dict[str, Any]],
    exceptions: Sequence[dict[str, Any]],
) -> str:
    target = Path(output_xlsx).expanduser().resolve()
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    target.parent.mkdir(parents=True, exist_ok=True)
    node_path = Path(
        os.environ.get("CUSTOMER_METER_PHOTO_QA_NODE", str(DEFAULT_REPORT_NODE))
    )
    if not node_path.is_file():
        raise RuntimeError(f"The bundled spreadsheet runtime is unavailable: {node_path}")
    if not REPORT_BUILDER.is_file():
        raise RuntimeError(f"Relay report builder not found: {REPORT_BUILDER}")
    payload = {
        "area": area,
        "operation": operation,
        "version": version,
        "generatedAt": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "substations": list(substations),
        "relayRows": _report_rows(rows),
        "exceptionRows": _report_exceptions(exceptions),
    }
    with tempfile.TemporaryDirectory(prefix="relay_association_report_") as temp:
        payload_path = Path(temp) / "report.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
        )
        completed = subprocess.run(
            [str(node_path), str(REPORT_BUILDER), str(payload_path), str(target)],
            cwd=str(REPORT_BUILDER.parent),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    if completed.returncode:
        details = (completed.stderr or completed.stdout or "Unknown error").strip()
        raise RuntimeError(f"Excel relay report could not be created: {details}")
    if not target.is_file():
        raise RuntimeError(f"Excel relay report was not created: {target}")
    return str(target)


def build_relay_apply_edits(
    rows: Sequence[dict[str, Any]],
    associations_table_id: int = ASSOCIATIONS_TABLE_ID,
) -> list[dict[str, Any]]:
    adds = []
    for row in rows:
        if row.get("status") != "PROPOSE":
            continue
        adds.append(
            {
                "attributes": {
                    "fromNetworkSourceId": int(row["_from_source_id"]),
                    "fromGlobalId": row["_from_globalid"],
                    "fromTerminalId": int(row["_from_terminal_id"]),
                    "toNetworkSourceId": int(row["_to_source_id"]),
                    "toGlobalId": row["_to_globalid"],
                    "toTerminalId": int(row["_to_terminal_id"]),
                    "associationType": CONNECTION_ASSOCIATION_TYPE,
                    "isContentVisible": 0,
                }
            }
        )
    return [{"id": int(associations_table_id), "adds": adds}] if adds else []


def _apply_associations(
    gis: Any,
    service_url: str,
    version: str,
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    edits = build_relay_apply_edits(rows)
    if not edits:
        return {"requested": 0, "succeeded": 0, "failed": 0}
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
        raise RuntimeError(f"Relay association applyEdits failed: {response['error']}")
    response_items = response if isinstance(response, list) else [response]
    add_results = []
    for item in response_items:
        if isinstance(item, dict):
            add_results.extend(item.get("addResults") or [])
    proposed = [row for row in rows if row.get("status") == "PROPOSE"]
    for index, row in enumerate(proposed):
        result = add_results[index] if index < len(add_results) else {}
        if result.get("success") is True:
            row["status"] = "APPLIED"
            row["reason"] = "Connectivity association created successfully"
        else:
            row["status"] = "FAILED"
            row["reason"] = f"Association was not created: {result.get('error') or 'No add result returned'}"
    succeeded = sum(item.get("success") is True for item in add_results)
    return {
        "requested": len(proposed),
        "succeeded": succeeded,
        "failed": len(proposed) - succeeded,
    }


def _relay_row(
    *,
    relay: Any,
    device: Any,
    rule: dict[str, Any],
    matched_scope: str,
    bay_label: str,
    relay_type_names: dict[tuple[int, int], str],
    device_group_names: dict[int, str],
    device_type_names: dict[tuple[int, int], str],
    terminal_names: dict[int, str],
    existing: set[tuple[str, int, str, int]],
) -> dict[str, Any]:
    relay_attrs = _feature_attributes(relay)
    device_attrs = _feature_attributes(device)
    relay_guid = normalize_guid(relay_attrs.get("GLOBALID"))
    device_guid = normalize_guid(device_attrs.get("GLOBALID"))
    relay_terminal = int(rule["relay_terminal"])
    device_terminal = int(rule["device_terminal"])
    key = (relay_guid, relay_terminal, device_guid, device_terminal)
    status = "EXISTING" if key in existing else "PROPOSE"
    reason = (
        "Connectivity association already exists"
        if status == "EXISTING"
        else "Correct spatial scope, terminal configuration, and live rule"
    )
    if rule["direction"] == "device_to_relay":
        from_source, from_guid, from_terminal = (
            ELECTRIC_DEVICE_SOURCE_ID,
            device_guid,
            device_terminal,
        )
        to_source, to_guid, to_terminal = (
            ELECTRIC_JUNCTION_OBJECT_SOURCE_ID,
            relay_guid,
            relay_terminal,
        )
    else:
        from_source, from_guid, from_terminal = (
            ELECTRIC_JUNCTION_OBJECT_SOURCE_ID,
            relay_guid,
            relay_terminal,
        )
        to_source, to_guid, to_terminal = (
            ELECTRIC_DEVICE_SOURCE_ID,
            device_guid,
            device_terminal,
        )
    relay_type = int(relay_attrs.get("ASSETTYPE") or 0)
    device_group = int(device_attrs.get("ASSETGROUP") or 0)
    device_type = int(device_attrs.get("ASSETTYPE") or 0)
    return {
        "proposal_id": "",
        "status": status,
        "reason": reason,
        "substation": _normal_text(relay_attrs.get("NameofSubstation"))
        or _report_substation(relay_attrs.get("Substation_ID")),
        "substation_id": _normal_text(relay_attrs.get("Substation_ID")),
        "relay_objectid": relay_attrs.get("OBJECTID"),
        "relay_type": relay_type,
        "relay_type_name": relay_type_names.get(
            (ELECTRIC_RELAY_ASSET_GROUP, relay_type), str(relay_type)
        ),
        "relay_description": _normal_text(relay_attrs.get("RelayType")),
        "relay_bay_id": _normal_text(relay_attrs.get("Bay_ID")),
        "matched_scope": matched_scope,
        "bay_label": bay_label,
        "device_objectid": device_attrs.get("OBJECTID"),
        "device_asset_id": _device_asset_id(device_attrs),
        "device_group_name": device_group_names.get(device_group, str(device_group)),
        "device_type_name": device_type_names.get(
            (device_group, device_type), str(device_type)
        ),
        "device_terminal_id": device_terminal,
        "device_terminal_label": f"{device_terminal} - {terminal_names.get(device_terminal, str(device_terminal))}",
        "relay_terminal_id": relay_terminal,
        "relay_terminal_label": f"{relay_terminal} - {terminal_names.get(relay_terminal, str(relay_terminal))}",
        "_from_source_id": from_source,
        "_from_globalid": from_guid,
        "_from_terminal_id": from_terminal,
        "_to_source_id": to_source,
        "_to_globalid": to_guid,
        "_to_terminal_id": to_terminal,
    }


def run_relay_associations(
    output_xlsx: str | Path,
    area_mode: str = KIGALI_MODE,
    province: str | None = None,
    district: str | None = None,
    sectors: Sequence[str] | None = None,
    cells: Sequence[str] | None = None,
    custom_boundary_geometry: dict[str, Any] | None = None,
    operation: str = PREVIEW_MODE,
    service_url: str | None = None,
    boundary_service_url: str | None = None,
    version: str = "sde.DEFAULT",
    gis: Any | None = None,
) -> dict[str, Any]:
    """Preview or apply rule-valid Electric Relay connectivity associations."""
    from arcgis.features import FeatureLayer
    from arcgis.geometry.filters import contains

    if area_mode not in AREA_MODES:
        raise ValueError(f"Unsupported area mode: {area_mode}")
    if operation not in OPERATION_MODES:
        raise ValueError(f"Unsupported operation: {operation}")

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

    bay_layer = FeatureLayer(_layer_url(active_service, STRUCTURE_BOUNDARY_LAYER_ID), active_gis)
    device_layer = FeatureLayer(_layer_url(active_service, ELECTRIC_DEVICE_LAYER_ID), active_gis)
    relay_layer = FeatureLayer(_layer_url(active_service, ELECTRIC_JUNCTION_OBJECT_LAYER_ID), active_gis)
    association_layer = FeatureLayer(_layer_url(active_service, ASSOCIATIONS_TABLE_ID), active_gis)
    rule_layer = FeatureLayer(_layer_url(active_service, RULES_TABLE_ID), active_gis)

    geometry_filter = contains(area_geometry, sr=area_geometry.get("spatialReference", {}))
    bay_set = _query_with_retry(
        bay_layer,
        where=f"ASSETGROUP = {ELECTRIC_BAY_ASSET_GROUP}",
        out_fields=(
            "OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,Substation_ID,Substation_Name,"
            "Name,Line_Bay_ID,Line_Bay_Name,Trx_Bay_ID,Trx_Bay_Name,Bay_ID,assetid"
        ),
        return_geometry=True,
        geometry_filter=geometry_filter,
        gdb_version=version,
    )
    area_device_set = _query_with_retry(
        device_layer,
        where="ASSETGROUP IS NOT NULL AND ASSETTYPE IS NOT NULL",
        out_fields=(
            "OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,Substation_ID,AssetID,AssetIDs,"
            "CircuitBreakerID,CurrentTransfomer_ID,VoltageTransfomer_ID,transfomerID"
        ),
        return_geometry=True,
        geometry_filter=geometry_filter,
        gdb_version=version,
    )
    relay_set = _query_with_retry(
        relay_layer,
        where=(
            f"ASSETGROUP = {ELECTRIC_RELAY_ASSET_GROUP} AND "
            f"ASSETTYPE IN ({','.join(str(item) for item in sorted(SUPPORTED_RELAY_TYPES))})"
        ),
        out_fields=(
            "OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,ASSOCIATIONSTATUS,RelayType,"
            "NameofSubstation,Bay_ID,Substation_ID"
        ),
        return_geometry=False,
        gdb_version=version,
    )

    bays = list(bay_set.features)
    area_devices = list(area_device_set.features)
    all_relays = list(relay_set.features)
    relay_group_names, relay_type_names = _subtype_maps(relay_layer)
    bay_shapes = {
        normalize_guid(_feature_attributes(feature).get("GLOBALID")): _as_shape(
            _feature_geometry(feature)
        )
        for feature in bays
    }
    devices_by_bay: dict[str, list[Any]] = defaultdict(list)
    for device in area_devices:
        geometry = _feature_geometry(device)
        if not geometry:
            continue
        for bay in bays:
            bay_guid = normalize_guid(_feature_attributes(bay).get("GLOBALID"))
            if _point_inside(bay_shapes[bay_guid], geometry):
                devices_by_bay[bay_guid].append(device)

    selected_substation_keys = {
        _name_key(_feature_attributes(bay).get("Substation_ID")) for bay in bays
    } | {_name_key(_asset_prefix(_feature_attributes(bay))) for bay in bays}
    area_device_substation_ids = {
        _normal_text(_feature_attributes(device).get("Substation_ID")).upper()
        for device in area_devices
        if _normal_text(_feature_attributes(device).get("Substation_ID"))
    }

    selected_relays = []
    relay_context: dict[str, dict[str, Any]] = {}
    exceptions: list[dict[str, Any]] = []
    for relay in all_relays:
        attrs = _feature_attributes(relay)
        relay_guid = normalize_guid(attrs.get("GLOBALID"))
        relay_type = int(attrs.get("ASSETTYPE") or 0)
        if relay_type == DIGITAL_FAULT_RECORDER:
            substation_id = _normal_text(attrs.get("Substation_ID")).upper()
            substation_key = _name_key(attrs.get("NameofSubstation"))
            if substation_id not in area_device_substation_ids and substation_key not in selected_substation_keys:
                continue
            selected_relays.append(relay)
            relay_context[relay_guid] = {
                "scope": "Whole substation",
                "bay_label": "All substation equipment",
                "bay": None,
            }
            continue

        substation_key = _name_key(attrs.get("NameofSubstation"))
        if substation_key not in selected_substation_keys:
            continue
        matches, matched_field, reason = resolve_relay_bay(attrs, bays)
        selected_relays.append(relay)
        if len(matches) != 1:
            exceptions.append(
                {
                    "substation": _normal_text(attrs.get("NameofSubstation")),
                    "relay_objectid": attrs.get("OBJECTID"),
                    "relay_type_name": relay_type_names.get(
                        (ELECTRIC_RELAY_ASSET_GROUP, relay_type), str(relay_type)
                    ),
                    "relay_bay_id": _normal_text(attrs.get("Bay_ID")),
                    "status": "REVIEW",
                    "reason": reason,
                }
            )
            relay_context[relay_guid] = {"skip": True}
            continue
        bay = matches[0]
        relay_context[relay_guid] = {
            "scope": matched_field or "Bay_ID",
            "bay_label": _bay_label(_feature_attributes(bay)),
            "bay": bay,
        }

    dfr_substation_ids = sorted(
        {
            _normal_text(_feature_attributes(relay).get("Substation_ID"))
            for relay in selected_relays
            if int(_feature_attributes(relay).get("ASSETTYPE") or 0)
            == DIGITAL_FAULT_RECORDER
            and _normal_text(_feature_attributes(relay).get("Substation_ID"))
        }
    )
    dfr_devices_by_substation: dict[str, list[Any]] = defaultdict(list)
    for substation_chunk in _chunks(dfr_substation_ids, 50):
        quoted = ",".join(f"'{_sql_text(item)}'" for item in substation_chunk)
        result = _query_with_retry(
            device_layer,
            where=f"Substation_ID IN ({quoted})",
            out_fields=(
                "OBJECTID,GLOBALID,ASSETGROUP,ASSETTYPE,Substation_ID,AssetID,AssetIDs,"
                "CircuitBreakerID,CurrentTransfomer_ID,VoltageTransfomer_ID,transfomerID"
            ),
            return_geometry=False,
            gdb_version=version,
        )
        for device in result.features:
            dfr_devices_by_substation[
                _normal_text(_feature_attributes(device).get("Substation_ID")).upper()
            ].append(device)

    rules = _connection_rules(rule_layer, version)
    rules_by_pair: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for rule in rules:
        rules_by_pair[
            (rule["relay_type"], rule["device_group"], rule["device_type"])
        ].append(rule)
    terminal_schema = _terminal_schema(active_gis, active_service)
    device_group_names, device_type_names = _subtype_maps(device_layer)
    relay_guids = [
        normalize_guid(_feature_attributes(relay).get("GLOBALID"))
        for relay in selected_relays
    ]
    existing = _query_existing_connections(association_layer, relay_guids, version)

    rows: list[dict[str, Any]] = []
    for relay in selected_relays:
        relay_attrs = _feature_attributes(relay)
        relay_guid = normalize_guid(relay_attrs.get("GLOBALID"))
        context = relay_context.get(relay_guid, {})
        if context.get("skip"):
            continue
        relay_type = int(relay_attrs.get("ASSETTYPE") or 0)
        if relay_type == DIGITAL_FAULT_RECORDER:
            devices = dfr_devices_by_substation.get(
                _normal_text(relay_attrs.get("Substation_ID")).upper(), []
            )
        else:
            bay = context.get("bay")
            bay_guid = normalize_guid(_feature_attributes(bay).get("GLOBALID"))
            devices = devices_by_bay.get(bay_guid, [])

        relay_rows_before = len(rows)
        for device in devices:
            device_attrs = _feature_attributes(device)
            pair_rules = _allowed_rules_for_pair(
                rules_by_pair, relay_type, device_attrs, terminal_schema
            )
            for rule in pair_rules:
                rows.append(
                    _relay_row(
                        relay=relay,
                        device=device,
                        rule=rule,
                        matched_scope=context["scope"],
                        bay_label=context["bay_label"],
                        relay_type_names=relay_type_names,
                        device_group_names=device_group_names,
                        device_type_names=device_type_names,
                        terminal_names=terminal_schema["terminal_names"],
                        existing=existing,
                    )
                )
        if len(rows) == relay_rows_before:
            exceptions.append(
                {
                    "substation": _normal_text(relay_attrs.get("NameofSubstation")),
                    "relay_objectid": relay_attrs.get("OBJECTID"),
                    "relay_type_name": relay_type_names.get(
                        (ELECTRIC_RELAY_ASSET_GROUP, relay_type), str(relay_type)
                    ),
                    "relay_bay_id": _normal_text(relay_attrs.get("Bay_ID")),
                    "status": "REVIEW",
                    "reason": "No rule-compatible equipment was found in the resolved scope",
                }
            )

    rows.sort(
        key=lambda row: (
            row["substation"],
            int(row["relay_objectid"] or 0),
            int(row["device_objectid"] or 0),
            int(row["device_terminal_id"] or 0),
        )
    )
    proposal_number = 0
    for row in rows:
        if row["status"] == "PROPOSE":
            proposal_number += 1
            row["proposal_id"] = f"R{proposal_number:05d}"

    apply_result = {"requested": 0, "succeeded": 0, "failed": 0}
    if operation == APPLY_MODE:
        apply_result = _apply_associations(active_gis, active_service, version, rows)

    status_counts = Counter(row["status"] for row in rows)
    substations = sorted(
        {
            row["substation"]
            for row in rows
            if row.get("substation")
        }
        | {
            row.get("substation", "")
            for row in exceptions
            if row.get("substation")
        },
        key=str.casefold,
    )
    output_path = _write_excel_report(
        output_xlsx,
        area=area_label,
        operation=operation,
        version=version,
        substations=substations,
        rows=rows,
        exceptions=exceptions,
    )
    transformer_rows = [
        row
        for row in rows
        if row["relay_type"] == TRANSFORMER_DIFFERENTIAL_RELAY
        and row["device_group_name"] in {
            device_group_names.get(group, str(group)) for group in TRANSFORMER_DEVICE_GROUPS
        }
    ]
    return {
        "output_xlsx": output_path,
        "operation": operation,
        "area": area_label,
        "version": version,
        "service_url": active_service,
        "selected_relays": len(selected_relays),
        "candidate_rows": len(rows),
        "transformer_terminal_rows": len(transformer_rows),
        "legal_connection_rules": len(rules),
        "status_counts": dict(sorted(status_counts.items())),
        "exception_rows": len(exceptions),
        "substations": substations,
        "apply_result": apply_result,
    }

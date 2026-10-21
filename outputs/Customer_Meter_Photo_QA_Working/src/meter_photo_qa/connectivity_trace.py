"""Read-only connected utility-network trace membership for LV survey reports."""

from __future__ import annotations

import json
import re
from typing import Any, Sequence


_GUID_PATTERN = re.compile(
    r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}"
)
_DIRTY_LINE_GROUP_PATTERN = re.compile(
    r"ElectricLine\s*:\s*((?:"
    r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}\s*,?\s*)+)",
    re.IGNORECASE,
)


class TopologyDirtyAreaError(RuntimeError):
    """Trace blocked by unvalidated topology; never a data-name mismatch."""

    def __init__(self, *, transformer_objectid, transformer_globalid,
                 dirty_line_globalids, version, trace_position, trace_total, original_error):
        self.transformer_objectid = int(transformer_objectid)
        self.transformer_globalid = str(transformer_globalid)
        self.dirty_line_globalids = tuple(dirty_line_globalids)
        self.version = str(version)
        self.trace_position = int(trace_position)
        self.trace_total = int(trace_total)
        self.original_error = str(original_error)
        dirty_list = ", ".join(self.dirty_line_globalids) or "not returned by server"
        super().__init__(
            f"Utility Network topology requires validation: trace "
            f"{self.trace_position}/{self.trace_total} was blocked at distribution "
            f"transformer OBJECTID {self.transformer_objectid} "
            f"(GlobalID {self.transformer_globalid}), version {self.version}. "
            f"Dirty ElectricLine GlobalID(s): {dirty_list}. "
            "This is NOT a transformer-name mismatch. No name-consistency "
            "report can be trusted for the selected area until affected dirty "
            "areas are reviewed and network topology is validated by an "
            "authorized Utility Network editor. In ArcGIS Pro, locate the "
            "Electric Line by GlobalID and inspect Dirty Areas; coordinate "
            "Utility Network > Validate > Current Extent. "
            "Do not disable trace consistency validation. "
            f"Service response: {self.original_error}"
        )


def _trace_dirty_error(error, point, version, position, total):
    """Return a typed blocker when ArcGIS signals one or more dirty areas."""
    message = str(error)
    if not ("dirty area" in message.casefold() or
            "dirty areas" in message.casefold()):
        return None
    globals_found = []
    for group in _DIRTY_LINE_GROUP_PATTERN.findall(message):
        globals_found.extend(
            guid.upper() for guid in _GUID_PATTERN.findall(group)
        )
    return TopologyDirtyAreaError(
        transformer_objectid=point["OBJECTID"],
        transformer_globalid=point.get("GLOBALID") or "",
        dirty_line_globalids=list(dict.fromkeys(globals_found)),
        version=version,
        trace_position=position,
        trace_total=total,
        original_error=message,
    )


def _network_schema(gis: Any, service_url: str) -> dict[str, Any]:
    root = service_url.rstrip("/")
    response = gis._con.get(
        root + "/queryDataElements", params={"f": "json", "layers": "[0]"}
    )
    if not isinstance(response, dict) or response.get("error"):
        raise RuntimeError(f"Utility-network schema could not be read: {response.get('error') if isinstance(response, dict) else response}")
    elements = response.get("layerDataElements") or []
    if not elements or not isinstance(elements[0].get("dataElement"), dict):
        raise RuntimeError("The feature service did not return its utility-network data element.")
    return elements[0]["dataElement"]


def _source(schema: dict[str, Any], layer_id: int) -> dict[str, Any]:
    for domain in schema.get("domainNetworks", []):
        for kind in ("junctionSources", "edgeSources"):
            for source in domain.get(kind, []):
                if int(source.get("layerId", -1)) == layer_id:
                    return source
    raise RuntimeError(f"Utility-network source for feature layer {layer_id} was not found.")


def _terminal_id(schema: dict[str, Any], device_source: dict[str, Any], point: dict[str, Any]) -> int:
    asset_group = int(point["ASSETGROUP"])
    asset_type = int(point["ASSETTYPE"])
    for group in device_source.get("assetGroups", []):
        if int(group.get("assetGroupCode", -1)) != asset_group:
            continue
        for asset in group.get("assetTypes", []):
            if int(asset.get("assetTypeCode", -1)) != asset_type:
                continue
            config_id = int(asset.get("terminalConfigurationId", -1))
            for config in schema.get("terminalConfigurations", []):
                if int(config.get("terminalConfigurationId", -2)) != config_id:
                    continue
                terminals = config.get("terminals") or []
                secondary = next((t for t in terminals if str(t.get("terminalName", "")).casefold() == "secondary"), None)
                selected = secondary or (terminals[0] if len(terminals) == 1 else None)
                if selected is None:
                    raise RuntimeError(
                        f"Transformer {point['OBJECTID']} has multiple terminals but no Secondary terminal."
                    )
                return int(selected["terminalId"])
    raise RuntimeError(
        f"Transformer {point['OBJECTID']} asset group/type lacks terminal configuration metadata."
    )


def _parse_trace(
    response: dict[str, Any], line_source_id: int, device_source_id: int,
) -> dict[str, Any]:
    if response.get("error") or response.get("success") is not True:
        raise RuntimeError(f"Connected trace failed: {response.get('error') or response}")
    result = response.get("traceResults")
    if not isinstance(result, dict):
        raise RuntimeError("Connected trace returned no traceResults object.")
    if result.get("startingPointsIgnored"):
        raise RuntimeError("The connected trace ignored its transformer starting point.")
    elements = result.get("elements")
    if not isinstance(elements, list):
        raise RuntimeError("Connected trace returned no network elements array.")
    line_ids = {
        int(element["objectId"])
        for element in elements
        if int(element.get("networkSourceId", -1)) == line_source_id
        and int(element.get("assetGroupCode", -1)) in (9, 10)
    }
    transformer_ids = {
        int(element["objectId"])
        for element in elements
        if int(element.get("networkSourceId", -1)) == device_source_id
        and int(element.get("assetGroupCode", -1)) == 12
    }
    return {
        "line_objectids": line_ids,
        "connected_transformer_objectids": transformer_ids,
        "network_element_count": len(elements),
        "warnings": list(result.get("warnings") or []),
    }


def trace_connected_lv_lines(
    gis: Any,
    service_url: str,
    transformer_points: Sequence[dict[str, Any]],
    version: str,
    line_layer_id: int = 10,
    transformer_layer_id: int = 7,
    progress: Any | None = None,
) -> dict[int, dict[str, Any]]:
    """Return distinct connected LV feature IDs for each localized point asset.

    The trace runs against the utility-network topology, with consistency checked.
    An error fails the report; it never silently substitutes a name match.
    """
    if not transformer_points:
        return {}
    schema = _network_schema(gis, service_url)
    line_source = _source(schema, line_layer_id)
    device_source = _source(schema, transformer_layer_id)
    trace_url = service_url.rstrip("/").removesuffix("/FeatureServer") + "/UtilityNetworkServer/trace"
    results: dict[int, dict[str, Any]] = {}
    for index, point in enumerate(transformer_points, 1):
        object_id = int(point["OBJECTID"])
        global_id = str(point.get("GLOBALID") or "").strip()
        if not global_id:
            raise RuntimeError(f"Transformer {object_id} has no GLOBALID for a connected trace.")
        terminal_id = _terminal_id(schema, device_source, point)
        params = {
            "f": "json",
            "gdbVersion": version,
            "traceType": "connected",
            "traceLocations": json.dumps([{
                "traceLocationType": "startingPoint",
                "globalId": global_id,
                "terminalId": terminal_id,
            }]),
            "traceConfiguration": json.dumps({
                "validateConsistency": True,
                "includeContainers": False,
                "includeContent": False,
                "includeStructures": False,
            }),
            "resultTypes": json.dumps([{"type": "elements", "includeGeometry": False}]),
        }
        try:
            response = gis._con.post(trace_url, params=params)
            if not isinstance(response, dict):
                raise RuntimeError("Connected trace returned an invalid response.")
            result = _parse_trace(
                response, int(line_source["sourceId"]),
                int(device_source["sourceId"]),
            )
        except Exception as exc:
            dirty = _trace_dirty_error(
                exc, point, version, index, len(transformer_points)
            )
            if dirty is not None:
                raise dirty from exc
            raise RuntimeError(
                f"Connected trace failed at transformer {index}/{len(transformer_points)} "
                f"(OBJECTID {object_id}, GlobalID {global_id}) in {version}: {exc}. "
                "No partial transformer-name QA report was generated."
            ) from exc
        if object_id not in result["connected_transformer_objectids"]:
            raise RuntimeError(f"Transformer {object_id} was not present in its own trace result.")
        result["terminal_id"] = terminal_id
        results[object_id] = result
        if progress and (index == 1 or index % 10 == 0 or index == len(transformer_points)):
            progress(
                f"Transformer connectivity trace {index}/{len(transformer_points)} "
                f"(ObjectID {object_id}); {len(result['line_objectids'])} LV line IDs in this component."
            )
    return results

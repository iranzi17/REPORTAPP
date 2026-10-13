"""Read-only source-level diagnostic for a suspected duplicate Electric Line GlobalID.

This tool checks the FeatureServer independently of ArcGIS Pro's attribute-table
selection, showing distinct OBJECTIDs and comparing exact polyline coordinates.
Do NOT infer that same length implies identical geometry, and never delete or
alter Utility Network records here.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .progress_report import DEFAULT_LINE_SERVICE_URL, LINE_LAYER_ID, _get_gis, _layer_url, _query_with_retry

_GUID_PATTERN = re.compile(
    r"^\{?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}?$"
)


def canonical_globalid(raw: str) -> str:
    value = str(raw or "").strip()
    match = _GUID_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("Enter one complete GlobalID in GUID format, with or without braces.")
    return "{" + match.group(1).upper() + "}"


def _canonical_paths(geometry: Any) -> tuple | None:
    """Exact XY vertex comparison, insensitive only to path direction/order.

    Does not prove spatial equality for differently segmented/offset paths.
    """
    if not geometry or not geometry.get("paths"):
        return None
    canonical = []
    for path in geometry["paths"]:
        vertices = []
        for vertex in path:
            if len(vertex) < 2:
                return None
            vertices.append((float(vertex[0]), float(vertex[1])))
        t = tuple(vertices)
        canonical.append(min(t, tuple(reversed(t))))
    return tuple(sorted(canonical))


def _readable_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return "" if value is None else value


def inspect_duplicate_line_globalid(
    globalid: str,
    output_xlsx: str | Path,
    service_url: str | None = None,
    version: str = "sde.DEFAULT",
    gis: Any | None = None,
) -> dict:
    """Fetch all source features using one GlobalID; inspect, never modify."""
    from arcgis.features import FeatureLayer
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    gid = canonical_globalid(globalid)
    service = str(service_url or DEFAULT_LINE_SERVICE_URL).rstrip("/")
    layer = FeatureLayer(_layer_url(service, LINE_LAYER_ID), _get_gis(gis))
    features = _query_with_retry(
        layer,
        where=f"GLOBALID = '{gid}'",
        out_fields="*",
        return_geometry=True,
        return_all_records=True,
        gdb_version=version,
    )
    if not hasattr(features, "features") or getattr(features, "exceeded_transfer_limit", False):
        raise RuntimeError("The source feature query did not return a complete feature set.")
    records = []
    geometry_signatures = []
    seen_objectids = set()
    for feature in features.features:
        attrs = dict(feature.attributes)
        objectid = attrs.get("OBJECTID")
        if objectid is None:
            raise RuntimeError("Electric Line record was returned without OBJECTID.")
        objectid = int(objectid)
        if objectid in seen_objectids:
            raise RuntimeError("FeatureServer repeated the same OBJECTID in one result.")
        seen_objectids.add(objectid)
        actual_gid = canonical_globalid(attrs.get("GLOBALID"))
        if actual_gid != gid:
            raise RuntimeError("FeatureServer returned a record with a different GlobalID.")
        geom = dict(feature.geometry or {})
        geometry_signatures.append(_canonical_paths(geom))
        records.append({
            "OBJECTID": objectid,
            "GLOBALID": actual_gid,
            "SHAPE_Length": attrs.get("SHAPE_Length", attrs.get("SHAPE__Length", "")),
            "ASSETGROUP": attrs.get("ASSETGROUP"),
            "ASSETTYPE": attrs.get("ASSETTYPE"),
            "created_user": attrs.get("created_user"),
            "created_date": attrs.get("created_date"),
            "last_edited_user": attrs.get("last_edited_user"),
            "last_edited_date": attrs.get("last_edited_date"),
            "Material": attrs.get("Material"),
            "ConductorInsulation": attrs.get("ConductorInsulation"),
            "geometry": geom,
        })
    records.sort(key=lambda item: item["OBJECTID"])
    exact_match = (
        len(records) > 1 and bool(geometry_signatures)
        and all(signature is not None for signature in geometry_signatures)
        and len(set(geometry_signatures)) == 1
    )
    geom_status = (
        "Identical XY vertex sequences (path order/reversal ignored)"
        if exact_match else
        "No exact-vertex match established; visually inspect spatial overlap"
        if len(records) > 1 else
        "No pair to compare"
    )
    output = Path(output_xlsx).expanduser().resolve()
    if output.suffix.lower() != ".xlsx":
        raise ValueError("Output report must be .xlsx.")
    output = output.with_name(f"{output.stem}_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    if output.exists():
        raise FileExistsError(f"File already exists: {output}")
    book = Workbook()
    summary = book.active
    summary.title = "Duplicate Assessment"
    for row in (
        ("Check", "Result"),
        ("GlobalID", gid),
        ("Source", _layer_url(service, LINE_LAYER_ID)),
        ("Version", version),
        ("Distinct OBJECTIDs", len(records)),
        ("Duplicated source GlobalID", "YES" if len(records) > 1 else "NO"),
        ("Geometry comparison", geom_status),
        ("OBJECTIDs", ", ".join(str(row["OBJECTID"]) for row in records)),
        ("Action", "Review geometry, related network associations and attachments before any edits."),
        ("Topology", "Dirty areas must be validated by authorized Utility Network editors; never ignore trace consistency."),
        ("Interpretation", "Two distinct OBJECTIDs returned directly by the FeatureServer confirm duplicate GlobalID in this version."),
    ):
        summary.append(row)
    detail = book.create_sheet("Electric Line Records")
    headers = [
        "OBJECTID", "GlobalID", "SHAPE Length", "Asset Group", "Asset Type",
        "Created By", "Created Date", "Last Edited By", "Last Edited Date",
        "Material", "Insulation", "Geometry Vertex Signature",
    ]
    detail.append(headers)
    for rec in records:
        signature = _canonical_paths(rec["geometry"])
        detail.append([
            rec["OBJECTID"], rec["GLOBALID"], _readable_value(rec["SHAPE_Length"]),
            rec["ASSETGROUP"], rec["ASSETTYPE"], rec["created_user"],
            _readable_value(rec["created_date"]), rec["last_edited_user"],
            _readable_value(rec["last_edited_date"]), rec["Material"],
            rec["ConductorInsulation"],
            "Available" if signature is not None else "Unavailable",
        ])
    for sheet in book.worksheets:
        sheet.freeze_panes = "A2"
        sheet.sheet_view.showGridLines = False
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.alignment = Alignment(wrap_text=True)
        for column in sheet.columns:
            cells = list(column)
            sheet.column_dimensions[cells[0].column_letter].width = min(
                max(14, max(len(str(cell.value or "")) for cell in cells[:100]) + 2), 68
            )
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.data_type = "s"
    output.parent.mkdir(parents=True, exist_ok=True)
    book.save(output)
    return {
        "read_only": True,
        "output_xlsx": str(output),
        "globalid": gid,
        "version": version,
        "matched_source_objects": len(records),
        "duplicate_globalid": len(records) > 1,
        "objectids": sorted(seen_objectids),
        "same_exact_geometry": exact_match,
        "geometry_assessment": geom_status,
    }

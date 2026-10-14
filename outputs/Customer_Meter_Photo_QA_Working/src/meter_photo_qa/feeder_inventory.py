"""Full source-transformer-connected LV feeder inventory for progress workbooks.

NO inference from matching text labels, proximity, individual surveyor, or
district clips. A topology-connected component is not guaranteed energized;
switching/direction need a separate operational network model.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence


def assess_source_feeder_inventory(
    groups: Sequence[Mapping[str, Any]],
    line_attributes: Sequence[Mapping[str, Any]],
    line_areas: Mapping[int, Mapping[str, list[str]]],
    origin_district: str,
    period_record_ids: set[int] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Every distinct line OBJECTID appears once; ambiguous sources never counted twice."""
    if not origin_district:
        raise ValueError("Source-transformer district is required for feeder inventory.")
    ids_from_trace: dict[int, set[str]] = defaultdict(set)
    by_group: dict[str, Mapping[str, Any]] = {}
    for group in groups:
        key = str(group["key"])
        if key in by_group:
            raise ValueError("Duplicate source-transformer key.")
        by_group[key] = group
        for oid in group["trace_line_objectids"]:
            ids_from_trace[int(oid)].add(key)
    lines: dict[int, Mapping[str, Any]] = {}
    gid_groups: dict[str, set[int]] = defaultdict(set)
    for attributes in line_attributes:
        oid = int(attributes["OBJECTID"])
        if oid in lines:
            raise ValueError(f"Repeated LV line OBJECTID {oid} in full feeder inventory.")
        if int(attributes.get("ASSETGROUP") or -1) not in (9,10):
            raise ValueError(f"Non-LV record {oid} returned by source trace.")
        lines[oid] = attributes
        gid = str(attributes.get("GLOBALID") or "").strip().strip("{}").casefold()
        if gid:
            gid_groups[gid].add(oid)
    missing = set(ids_from_trace) - set(lines)
    unexpected = set(lines) - set(ids_from_trace)
    if missing or unexpected:
        raise RuntimeError(
            f"Full feeder inventory is incomplete: missing {len(missing)} "
            f"and unexpected {len(unexpected)} line ObjectIDs."
        )
    included = period_record_ids or set()
    rows: list[dict] = []
    for oid, attributes in sorted(lines.items()):
        source_keys = ids_from_trace[oid]
        unique = len(source_keys) == 1
        group = by_group[next(iter(source_keys))] if unique else None
        reliable = bool(unique and group.get("trackable"))
        areas = line_areas.get(oid) or {}
        district_labels = sorted(
            {str(x).strip() for x in areas.get("district", []) if str(x).strip()},
            key=str.casefold,
        )
        if not district_labels:
            area_status = "LOCATION_UNVERIFIED"
        elif origin_district.casefold() in {x.casefold() for x in district_labels}:
            area_status = ("CROSSES_OR_TOUCHES_BORDER" if len(district_labels)>1
                           else "INSIDE_SOURCE_DISTRICT")
        else:
            area_status = "OUTSIDE_SOURCE_DISTRICT"
        origin = group if reliable else None
        status = (
            "VERIFIED_UNIQUE_CONNECTED_SOURCE"
            if reliable else "AMBIGUOUS_MULTIPLE_TRANSFORMERS"
            if (not unique or (group and not group.get("trackable")))
            else "SOURCE_UNVERIFIED"
        )
        gid = str(attributes.get("GLOBALID") or "").strip()
        peers = sorted(gid_groups.get(gid.strip("{}").casefold(),set())-{oid}) if gid else []
        length = attributes.get("Shape__Length",attributes.get("SHAPE__Length",0))
        length_m = float(length or 0.0)
        if length_m < 0:
            raise RuntimeError(f"Negative line length for OBJECTID {oid}.")
        line_name = str(attributes.get("Transformer_Name") or "").strip()
        source_name = str(origin.get("transformer_name") or "").strip() if origin else ""
        name_check = (
            "NAME_REVIEW" if source_name and line_name and
            " ".join(line_name.lower().split()) != " ".join(source_name.lower().split())
            else "NAME_MISSING" if source_name and not line_name
            else "MATCH" if source_name else "SOURCE_UNVERIFIED"
        )
        rows.append({
            "line_objectid":oid,
            "line_globalid":gid,
            "source_transformer_objectid":int(origin["objectids"][0]) if origin else None,
            "source_transformer_name":source_name,
            "candidate_source_objectids":"; ".join(
                str(int(by_group[k]["objectids"][0])) for k in sorted(source_keys)
            ),
            "source_status":status,
            "districts":"; ".join(district_labels),
            "sectors":"; ".join(sorted(set(areas.get("sector",[])),key=str.casefold)),
            "cells":"; ".join(sorted(set(areas.get("cell",[])),key=str.casefold)),
            "boundary_status":area_status,
            "length_km":length_m/1000,
            "created_user":str(attributes.get("created_user") or "").strip(),
            "recorded_transformer_name":line_name,
            "name_status":name_check,
            "in_requested_surveyor_period":oid in included,
            "duplicate_globalid_peer_objectids":"; ".join(map(str,peers)),
        })

    by_source: dict[str,list[dict]] = defaultdict(list)
    for row in rows:
        if row["source_transformer_objectid"] is not None:
            by_source[str(row["source_transformer_objectid"])].append(row)
    summaries=[]
    for group in sorted(groups,key=lambda g:str(g["transformer_no"])):
        source_oid=int(group["objectids"][0])
        verified=by_source.get(str(source_oid),[])
        summaries.append({
            "transformer_number":group["transformer_no"],
            "source_transformer_objectid":source_oid,
            "source_transformer_name":group["transformer_name"],
            "source_status":"UNIQUE_TRACE" if group.get("trackable") else "SOURCE_REQUIRES_REVIEW",
            "traced_line_ids":len(group["trace_line_objectids"]),
            "uniquely_assigned_segments":len(verified),
            "unique_trace_length_km":sum(row["length_km"] for row in verified),
            "crossing_or_outside_segments":sum(row["boundary_status"] in
                  ("CROSSES_OR_TOUCHES_BORDER","OUTSIDE_SOURCE_DISTRICT")
                  for row in verified),
            "crossing_or_outside_length_km":sum(
                row["length_km"] for row in verified if row["boundary_status"] in
                ("CROSSES_OR_TOUCHES_BORDER","OUTSIDE_SOURCE_DISTRICT")
            ),
            "in_requested_period":sum(row["in_requested_surveyor_period"]
                                      for row in verified),
        })
    statuses=Counter(r["source_status"] for r in rows)
    border=Counter(r["boundary_status"] for r in rows)
    issues={
        "all_trace_connected_line_records":len(rows),
        "verified_unique_source_segments":statuses["VERIFIED_UNIQUE_CONNECTED_SOURCE"],
        "ambiguous_or_unverified_source_segments":len(rows)-statuses["VERIFIED_UNIQUE_CONNECTED_SOURCE"],
        "outside_source_district_segments":border["OUTSIDE_SOURCE_DISTRICT"],
        "cross_border_segments":border["CROSSES_OR_TOUCHES_BORDER"],
        "unverified_location_segments":border["LOCATION_UNVERIFIED"],
        "duplicate_line_globalid_records":sum(bool(r["duplicate_globalid_peer_objectids"]) for r in rows),
        "surveyed_user_period_segment_records":sum(r["in_requested_surveyor_period"] for r in rows),
        "trace_mode":"connected topology, not proven energized feeder direction",
    }
    return rows, summaries, issues


def add_feeder_inventory_sheets(
    workbook,
    rows: Sequence[Mapping[str,Any]],
    summaries: Sequence[Mapping[str,Any]],
    scope: Mapping[str,Any],
):
    """Append separated cross-border inventory; never overwrite field-progress sheet."""
    from openpyxl.styles import Font, PatternFill, Alignment

    overview=workbook.create_sheet("Feeder Coverage Summary")
    details=workbook.create_sheet("Full Feeder Segments")
    caveats=workbook.create_sheet("Feeder Evidence Notes")
    overview_headers=[
        "Source Transformer No", "Transformer OBJECTID", "Source Transformer Name",
        "Trace Evidence", "All traced ObjectIDs", "Uniquely assigned segments",
        "Uniquely assigned length (km)", "Crossing/outside segments",
        "Crossing/outside length (km)", "Surveyor/date-matched segments",
    ]
    overview.append(overview_headers)
    for item in summaries:
        overview.append([
            item["transformer_number"], item["source_transformer_objectid"],
            item["source_transformer_name"],item["source_status"],
            item["traced_line_ids"],item["uniquely_assigned_segments"],
            item["unique_trace_length_km"],
            item["crossing_or_outside_segments"],
            item["crossing_or_outside_length_km"],item["in_requested_period"],
        ])
    detail_headers=[
        "LV Line OBJECTID","LV Line GlobalID","Source Transformer OBJECTID",
        "Source Transformer Name","Candidate Transformer OBJECTIDs",
        "Trace Source Status","District(s) Intersected","Sector(s) Intersected",
        "Cell(s) Intersected","Boundary Status","Line Length (km)",
        "Created User","Recorded Line Transformer Name",
        "Recorded Name Check","Matches Requested Surveyor AND Dates",
        "Other OBJECTIDs Sharing Line GlobalID",
    ]
    details.append(detail_headers)
    for row in rows:
        details.append([
            row["line_objectid"],row["line_globalid"],
            row["source_transformer_objectid"],row["source_transformer_name"],
            row["candidate_source_objectids"],row["source_status"],
            row["districts"],row["sectors"],row["cells"],
            row["boundary_status"],row["length_km"],row["created_user"],
            row["recorded_transformer_name"],row["name_status"],
            "YES" if row["in_requested_surveyor_period"] else "NO",
            row["duplicate_globalid_peer_objectids"],
        ])
    for name,value in [
        ("Origin district",scope.get("district","")),
        ("Source rule","Distribution transformers geographically inside requested district/sector."),
        ("Feeder extent","ALL utility-network trace-connected LV lines, including beyond district."),
        ("Surveyor/date filter","APPLIES ONLY to the original Sheet2 progress and indicated YES/NO column, not to the full feeder inventory."),
        ("Network evidence","Connected topology; does not determine energized source, switch state or feeder direction."),
        ("Ambiguity","Multi-transformer components and warning-bearing traces are not assigned to one source."),
        ("Geography","Spatial intersection with hosted national cell boundaries; a segment can touch multiple districts."),
        ("Source record IDs","One row per distinct line OBJECTID. Repeated GlobalIDs are indicated rather than silently deduplicated."),
        ("Existing gaps","The original LV progress report and its status logs are preserved."),
        ("Version",scope.get("version","")),
        ("Site-wide feature counts",scope.get("all_trace_connected_line_records",0)),
        ("Ambiguous/unverified source segments",scope.get("ambiguous_or_unverified_source_segments",0)),
        ("Outside-origin segments",scope.get("outside_source_district_segments",0)),
        ("Cross-border segments",scope.get("cross_border_segments",0)),
        ("Unverified administrative location",scope.get("unverified_location_segments",0)),
    ]:
        caveats.append([name,value])
    for sheet in (overview,details,caveats):
        sheet.freeze_panes="A2"
        sheet.sheet_view.showGridLines=False
        for cell in sheet[1]:
            cell.fill=PatternFill("solid",fgColor="17365D")
            cell.font=Font(bold=True,color="FFFFFF")
            cell.alignment=Alignment(wrap_text=True)
        for column in sheet.columns:
            cells=list(column)
            sheet.column_dimensions[cells[0].column_letter].width=min(
                63,max(15,max(len(str(c.value or "")) for c in cells[:200])+2)
            )
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value,str) and cell.value.startswith("="):
                    cell.data_type="s"
    for sheet in (overview,details):
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if "Length (km)" in str(sheet.cell(1,cell.column).value) or \
                   "length (km)" in str(sheet.cell(1,cell.column).value):
                    cell.number_format="0.000"

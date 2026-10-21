"""Full source-transformer-connected LV feeder inventory for progress workbooks.

NO inference from matching text labels, proximity, individual surveyor, or
district clips. A topology-connected component is not guaranteed energized;
switching/direction need a separate operational network model.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from typing import Any, Mapping, Sequence


def assess_source_feeder_inventory(
    groups: Sequence[Mapping[str, Any]],
    line_attributes: Sequence[Mapping[str, Any]],
    line_areas: Mapping[int, Mapping[str, list[str]]],
    origin_district: str,
    period_record_ids: set[int] | None = None,
    selected_origin_sectors: Sequence[str] | None = None,
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
    selected_sector_set = {
        str(value).strip().casefold()
        for value in (selected_origin_sectors or [])
        if str(value).strip()
    }
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
        if length is None or str(length).strip() == "":
            raise RuntimeError(
                f"Missing Shape__Length for LV line {oid}; cannot publish "
                "a reliable transformer-origin kilometre total."
            )
        length_m = float(length)
        if not isfinite(length_m) or length_m < 0:
            raise RuntimeError(
                f"Non-finite or negative line length for OBJECTID {oid}."
            )
        line_sectors = {
            str(v).strip().casefold() for v in areas.get("sector", [])
            if str(v).strip()
        }
        if not line_sectors:
            sector_status = "LOCATION_UNVERIFIED"
        elif selected_sector_set and line_sectors - selected_sector_set:
            sector_status = "TOUCHES_OTHER_SECTOR"
        elif len(line_sectors) > 1:
            sector_status = "TOUCHES_MULTIPLE_SECTORS"
        elif selected_sector_set:
            sector_status = "WITHIN_SELECTED_START_SECTORS"
        else:
            sector_status = "SECTOR_RECORDED_ORIGIN_NOT_RESOLVED"
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
            "sector_continuation_status":sector_status,
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
    continued = {
        "TOUCHES_OTHER_SECTOR", "TOUCHES_MULTIPLE_SECTORS"
    }
    assured = [
        row for row in rows
        if row["source_status"] == "VERIFIED_UNIQUE_CONNECTED_SOURCE"
    ]
    unresolved = [
        row for row in rows
        if row["source_status"] != "VERIFIED_UNIQUE_CONNECTED_SOURCE"
    ]
    total_km = sum(row["length_km"] for row in rows)
    assured_km = sum(row["length_km"] for row in assured)
    unresolved_km = sum(row["length_km"] for row in unresolved)
    if abs(total_km - assured_km - unresolved_km) > 1e-8:
        raise RuntimeError("Transformer-origin kilometre reconciliation failed.")
    issues={
        "all_trace_connected_line_records":len(rows),
        "all_trace_connected_length_km":total_km,
        "unique_connected_source_length_km":assured_km,
        "ambiguous_or_unverified_source_length_km":unresolved_km,
        "sector_continuation_segment_records":sum(
            row["sector_continuation_status"] in continued for row in rows
        ),
        "full_length_of_sector_continuation_segments_km":sum(
            row["length_km"] for row in rows
            if row["sector_continuation_status"] in continued
        ),
        "duplicate_globalid_review_length_km":sum(
            row["length_km"] for row in rows
            if row["duplicate_globalid_peer_objectids"]
        ),
        "selected_origin_sectors":"; ".join(sorted(selected_sector_set)),
        "scope_warning":(
            "Complete feature length for each traced LV OBJECTID. "
            "Cross-sector line kilometres are NOT split by polygon. "
            "Connected trace does NOT prove energized supply."
        ),
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

    primary=workbook.create_sheet("Transformer-Origin Overview",0)
    overview=workbook.create_sheet("Feeder Coverage Summary")
    details=workbook.create_sheet("Full Feeder Segments")
    caveats=workbook.create_sheet("Feeder Evidence Notes")
    primary.append(["TRANSFORMER-ORIGIN LV CONNECTED COVERAGE", "Result / explanation"])
    for key, value in [
        ("Report priority", "Origin-transformer coverage; not geographic sector km"),
        ("Starting transformer district", scope.get("district","")),
        ("Selected starting sector(s)", scope.get("selected_origin_sectors") or
         "All selected source points; individual origin sectors not verified"),
        ("Traced LV line OBJECTIDs", scope.get("all_trace_connected_line_records",0)),
        ("All traced LV length (km)", scope.get("all_trace_connected_length_km",0)),
        ("Unique connected-source length (km)",
         scope.get("unique_connected_source_length_km",0)),
        ("Unassigned/multiple-source length (km)",
         scope.get("ambiguous_or_unverified_source_length_km",0)),
        ("Lines reaching/touching multiple or other sectors",
         scope.get("sector_continuation_segment_records",0)),
        ("Full length of those lines (km; NOT length inside other sectors)",
         scope.get("full_length_of_sector_continuation_segments_km",0)),
        ("Duplicate-GlobalID review length (km; included in above totals)",
         scope.get("duplicate_globalid_review_length_km",0)),
        ("Surveyor/date matching", "Shown separately in Sheet2 and Full Feeder Segments"),
        ("Coverage measurement", scope.get("scope_warning","")),
        ("Electrical evidence", scope.get("trace_mode","")),
        ("Source version", scope.get("version","")),
    ]:
        primary.append([key,value])
    primary.freeze_panes="B2"
    primary.sheet_view.showGridLines=False
    primary.column_dimensions["A"].width=64
    primary.column_dimensions["B"].width=92
    for cell in primary[1]:
        cell.fill=PatternFill("solid",fgColor="17365D")
        cell.font=Font(bold=True,color="FFFFFF")
    for row in primary.iter_rows(min_row=2):
        label, value = row[:2]
        label.font=Font(bold=True,color="17365D")
        if isinstance(value.value,(int,float)):
            value.number_format="0.000" if "km" in str(label.value).lower() else "#,##0"
        value.alignment=Alignment(wrap_text=True,vertical="top")
        primary.row_dimensions[row[0].row].height=29 if len(str(value.value or ""))>100 else 20
    overview_headers=[
        "Source Transformer No", "Transformer OBJECTID", "Source Transformer Name",
        "Trace Evidence", "All traced ObjectIDs", "Uniquely assigned segments",
        "Uniquely assigned length (km)", "Crossing/outside segments",
        "Full length of crossing/outside features (km)", "Surveyor/date-matched segments",
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
        "Cell(s) Intersected","Boundary Status","Sector Continuation Status",
        "Line Length (km)", "Created User","Recorded Line Transformer Name",
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
            row["boundary_status"],row["sector_continuation_status"],
            row["length_km"],row["created_user"],
            row["recorded_transformer_name"],row["name_status"],
            "YES" if row["in_requested_surveyor_period"] else "NO",
            row["duplicate_globalid_peer_objectids"],
        ])
    for name,value in [
        ("Origin district",scope.get("district","")),
        ("Source rule","Distribution transformers geographically inside requested district/sector."),
        ("Feeder extent","ALL utility-network trace-connected LV lines, including beyond originating sector/district."),
        ("Sector continuation","Sector labels are obtained by spatial intersection; boundary touches can be listed. A line's ENTIRE length appears in the origin-transformer total. It is NOT a geographic allocation."),
        ("Source attribution","'Unique' means the only transformer in connected topology, with no warnings; not a verified energized source."),
        ("Duplicate GlobalIDs","Duplicate GUID records are marked for review; topology uses OBJECTIDs. Physical length may be overstated if records represent the same conductor."),
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

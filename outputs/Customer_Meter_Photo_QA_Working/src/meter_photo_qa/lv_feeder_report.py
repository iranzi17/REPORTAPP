"""Read-only LV feeder report: sources selected in district, lines traced nationwide.

Topology is connected (not directional or energized source). Reports label
multi-source components and trace warnings. No regional line clipping.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from pathlib import Path
from .asset_quality import resolve_fields
from .asset_quality_runner import _filters_for_area
from .connectivity_trace import trace_connected_lv_lines
from .progress_report import (
    DEFAULT_BOUNDARY_SERVICE_URL, DEFAULT_LINE_SERVICE_URL,
    LINE_LAYER_ID, TRANSFORMER_LAYER_ID, SECTOR_LAYER_ID, CELL_LAYER_ID,
    _get_gis, _get_sector_features, _layer_url, _query_with_retry,
)
from .quality_query_batches import query_attributes_in_batches
from .transformer_line_audit import _fetch_line_attributes_by_ids
from .transformer_line_names import assess_line_transformer_names


def run_lv_feeder_report(output_folder, district, usernames=None,
                         service_url=None, boundary_service_url=None,
                         version="sde.DEFAULT", gis=None,
                         progress=None, transformer_asset_types=(1,2,3,4,5,6),
                         method="geometry", endpoint_tolerance=1.5,
                         seed_tolerance=7.0):
    """LV feeder report: provisional geometry by default, topology by choice.

    Username filters select report rows, NEVER trace seeds or topology extent.
    Date filters are intentionally not applied to avoid truncating feeders.
    """
    if not district:
        raise ValueError("Starting-transformer district is required.")
    if method == "geometry":
        from .geometry_feeder_runner import run_provisional_geometry_feeder_report
        return run_provisional_geometry_feeder_report(
            output_folder, district, usernames=usernames,
            service_url=service_url,
            boundary_service_url=boundary_service_url,
            version=version, gis=gis, progress=progress,
            endpoint_tolerance=endpoint_tolerance,
            seed_tolerance=seed_tolerance,
        )
    if method != "topology":
        raise ValueError("Feeder report method must be geometry or topology.")
    from arcgis.features import FeatureLayer
    active=_get_gis(gis)
    service=str(service_url or DEFAULT_LINE_SERVICE_URL).rstrip("/")
    boundary=str(boundary_service_url or DEFAULT_BOUNDARY_SERVICE_URL).rstrip("/")
    lines=FeatureLayer(_layer_url(service,LINE_LAYER_ID),active)
    transformers=FeatureLayer(_layer_url(service,TRANSFORMER_LAYER_ID),active)
    sectors=FeatureLayer(_layer_url(boundary,SECTOR_LAYER_ID),active)
    cells=FeatureLayer(_layer_url(boundary,CELL_LAYER_ID),active)
    boundaries=_get_sector_features(sectors,district,None,cells,None)
    if not boundaries:
        raise RuntimeError("No confirmed starting-transformer administrative boundary.")
    filters=_filters_for_area(boundaries,None)
    name_field=resolve_fields([dict(f) for f in transformers.properties.fields],
                              "transformer").get("name")
    if not name_field:
        raise RuntimeError("Cannot resolve distribution-transformer name in live schema.")
    def notify(text):
        if progress:
            progress(text)
    points=query_attributes_in_batches(
        transformers,
        "ASSETGROUP = 12 AND ASSETTYPE IN ("+
        ",".join(map(str,transformer_asset_types))+")",
        version,
        ["OBJECTID","GLOBALID","ASSETGROUP","ASSETTYPE",name_field],
        filters,_query_with_retry,asset_label="Distribution transformer",
        progress=notify,duplicate_globalid_policy="error",
    )
    notify(f"{len(points)} starting transformers within {district}; tracing beyond district boundaries.")
    traces=trace_connected_lv_lines(
        active,service,points,version,LINE_LAYER_ID,TRANSFORMER_LAYER_ID,progress=notify
    )
    all_ids=set().union(*(t["line_objectids"] for t in traces.values())) if traces else set()
    available={f["name"].casefold():f["name"] for f in lines.properties.fields}
    essential=["OBJECTID","GLOBALID","ASSETGROUP","ASSETTYPE",
               "Transformer_Name","created_user"]
    if not all(v.casefold() in available for v in essential):
        raise RuntimeError("Missing essential LV line fields; cannot safely report.")
    optional=["Voltage_Level_kV","Phases","Material","CondustorSize",
              "Rated_Current","ConductorInsulation","SHAPE__Length","SHAPE_Length",
              "last_edited_user","last_edited_date"]
    selected=[available[k.casefold()] for k in essential+optional
              if k.casefold() in available]
    records=_fetch_line_attributes_by_ids(
        lines,all_ids,version,selected,usernames=usernames
    )
    point_rows=[{**p,"Transfomer_name_":p.get(name_field)} for p in points]
    evaluations=assess_line_transformer_names(records,point_rows,traces)
    output_dir=Path(output_folder).expanduser().resolve()
    if not output_dir.is_dir():
        raise ValueError("Destination folder must exist: "+str(output_dir))
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output=output_dir / f"LV_Feeders_Starting_{district}_{stamp}.xlsx"
    from openpyxl import Workbook
    from openpyxl.styles import Font,PatternFill
    book=Workbook()
    summary=book.active;summary.title="Summary"
    details=book.create_sheet("Connected LV Lines")
    review=book.create_sheet("Engineering Review")
    sources=book.create_sheet("Starting Transformers")
    checks=book.create_sheet("Method and Caveats")
    issues=Counter(e["status"] for e in evaluations)
    for row in [
        ("Metric","Value"),
        ("Starting transformer district",district),
        ("Scope","All LV connected components from local transformer points, including cross-district line segments"),
        ("Version requested",version),
        ("Network source",service),
        ("Starting distribution transformers",len(points)),
        ("Connected LV line OBJECTIDs before username filter",len(all_ids)),
        ("LV line OBJECTIDs in requested surveyor report",len(records)),
        ("Created-user filter","; ".join(usernames) if usernames else "All"),
        ("Matches",issues["MATCH"]),
        ("Name mismatch requiring review",issues["NAME_MISMATCH_REVIEW"]),
        ("Ambiguous sources",issues["AMBIGUOUS_CONNECTED_SOURCES"]),
        ("Trace warnings",issues["TRACE_WARNING_UNVERIFIED"]),
        ("Distinct printed line OBJECTIDs",len({e["objectid"] for e in evaluations})),
    ]: summary.append(row)
    headers=["Status","Line GlobalID","Line OBJECTID","Created By",
             "Recorded Transformer Name","Connected Transformer Name",
             "Source Transformer GlobalID","Source Transformer OBJECTID",
             "Candidate Local Transformers","Evidence"] + [
                 v for v in selected if v.casefold() not in
                 ("objectid","globalid","created_user","transformer_name")
             ]
    details.append(headers)
    review.append(headers)
    by_oid={int(v["OBJECTID"]):v for v in records}
    for e in evaluations:
        record=by_oid[e["objectid"]]
        values=[
            e["status"],e["globalid"],e["objectid"],e["username"],
            e["line_transformer_name"],e["connected_transformer_name"],
            e["transformer_globalid"],e["transformer_objectid"],
            e["candidate_transformer_count"],e["evidence"]
        ] + [record.get(v) for v in selected if v.casefold() not in
               ("objectid","globalid","created_user","transformer_name")]
        details.append(values)
        if e["status"]!="MATCH":
            review.append(values)
    sources.append(["Transformer OBJECTID","Transformer GlobalID","Transformer Name","Trace LV line count","Other Connected Transformer Count","Trace Warnings"])
    for p in points:
        info=traces[int(p["OBJECTID"])]
        sources.append([p["OBJECTID"],p["GLOBALID"],p.get(name_field),
             len(info["line_objectids"]),
             len(info["connected_transformer_objectids"]),"; ".join(map(str,info.get("warnings",[])))])
    for item in [
        ("Rule","Interpretation"),
        ("Starting boundary","Only selecting transformers; never clips downstream lines"),
        ("Surveyor filter","Selects connected line records after topology trace, not the full feeder's connectivity"),
        ("Connected vs energized","Connectivity alone does not prove actual electrical source, isolation, or current flow"),
        ("Cross-border feeders","Included if returned by the Utility Network source transformer trace"),
        ("Multi-source","Not assigned a unique supplying transformer; flagged for engineering review"),
        ("Dirty network","Trace consistency verification remains enabled; incomplete reports fail"),
        ("Date range","No date restriction is applied; feeder must include older segments"),
        ("Admin location","Starting district verified spatially; downstream lines are not assumed to remain there"),
        ("Conductor capacity","Rated_Current is conductor carrying capacity, not measured load"),
        ("Safety","Read-only report; no GIS edits"),
    ]:checks.append(item)
    for sheet in book.worksheets:
        sheet.freeze_panes="A2";sheet.sheet_view.showGridLines=False
        for cell in sheet[1]:
            cell.font=Font(color="FFFFFF",bold=True)
            cell.fill=PatternFill("solid",fgColor="17365D")
        for column in sheet.columns:
            cells=list(column)
            sheet.column_dimensions[cells[0].column_letter].width=min(
                72,max(14,max(len(str(c.value or "")) for c in cells[:300])+2))
        for row in sheet:
            for cell in row:
                if isinstance(cell.value,str) and cell.value.startswith(("=","+","-","@")):
                    cell.data_type="s"
    book.save(output)
    return {
        "output_xlsx":str(output),
        "starting_transformers":len(points),
        "connected_lv_line_ids":len(all_ids),
        "surveyed_connected_lines":len(records),
        "engineering_review_lines":len(evaluations)-issues["MATCH"],
        "read_only":True,
        "boundary_rule":"Starting transformer district only; connected lines may cross borders",
    }

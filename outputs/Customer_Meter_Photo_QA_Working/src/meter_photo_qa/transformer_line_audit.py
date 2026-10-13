"""ArcGIS Pro read-only cross-layer transformer-name consistency report."""
from __future__ import annotations

import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from .area_selection import selected_districts
from .asset_quality import resolve_fields
from .asset_quality_runner import _filters_for_area
from .connectivity_trace import trace_connected_lv_lines
from .progress_report import (
    DEFAULT_BOUNDARY_SERVICE_URL, DEFAULT_LINE_SERVICE_URL,
    LINE_LAYER_ID, TRANSFORMER_LAYER_ID, SECTOR_LAYER_ID, CELL_LAYER_ID,
    _as_date, _get_gis, _get_sector_features, _layer_url,
    _query_with_retry,
)
from .quality_query_batches import query_attributes_in_batches
from .quality_watcher import build_quality_where
from .transformer_line_names import assess_line_transformer_names, summary_by_surveyor

REVIEW_STATUSES = {"NAME_MISMATCH_REVIEW", "MISSING_LINE_TRANSFORMER_NAME"}
UNVERIFIED_STATUSES = {
    "AMBIGUOUS_CONNECTED_SOURCES", "SOURCE_UNVERIFIED",
    "TRANSFORMER_NAME_UNVERIFIED",
}


def _progress(message):
    try:
        import arcpy
        arcpy.AddMessage(message)
    except ImportError:
        pass


def _write_workbook(
    output_path: Path,
    rows: list[dict],
    source_count: int,
    boundary_scope: list[str],
    start: date,
    end: date,
    source_service: str,
    version: str,
) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    overview = wb.active
    overview.title = "Summary"
    review = wb.create_sheet("Name Mismatch Review")
    all_lines = wb.create_sheet("All Checked LV Lines")
    surveyors = wb.create_sheet("Surveyor Summary")
    definition = wb.create_sheet("Rule and Limitations")

    totals = Counter(item["status"] for item in rows)
    overview.append(["LV Line Transformer Name — Network Consistency"])
    for label, value in [
        ("District(s)", ", ".join(boundary_scope) if boundary_scope else "All Rwanda"),
        ("From", start.isoformat()),
        ("To (inclusive)", end.isoformat()),
        ("Date rule", "Line created or edited during selected period; transformers have no date restriction"),
        ("LV lines examined", len(rows)),
        ("Transformers traced", source_count),
        ("Matched", totals["MATCH"]),
        ("Different transformer name — REVIEW", totals["NAME_MISMATCH_REVIEW"]),
        ("Line transformer name missing — REVIEW", totals["MISSING_LINE_TRANSFORMER_NAME"]),
        ("Ambiguous connected sources", totals["AMBIGUOUS_CONNECTED_SOURCES"]),
        ("Source unverified", totals["SOURCE_UNVERIFIED"]),
        ("Transformer name unavailable", totals["TRANSFORMER_NAME_UNVERIFIED"]),
        ("Source version", version),
        ("Source FeatureServer", source_service),
    ]:
        overview.append([label, value])

    headers = [
        "Status", "Line GlobalID", "Line OBJECTID", "Surveyor",
        "Recorded Line Transformer Name", "Connected Transformer Name",
        "Transformer GlobalID", "Transformer OBJECTID",
        "Number of Local Candidate Sources", "Explanation / Evidence",
    ]
    for sheet in (review, all_lines):
        sheet.append(headers)

    for item in rows:
        values = [
            item["status"], item["globalid"], item["objectid"],
            item["username"], item["line_transformer_name"],
            item["connected_transformer_name"], item["transformer_globalid"],
            item["transformer_objectid"], item["candidate_transformer_count"],
            item["evidence"],
        ]
        all_lines.append(values)
        if item["status"] in REVIEW_STATUSES:
            review.append(values)

    surveyors.append([
        "Surveyor", "LV Lines Checked", "Match",
        "Name Mismatch Review", "Missing Name Review",
        "Ambiguous Sources", "Source Unverified",
        "Transformer Name Unverified",
    ])
    for user, counts in summary_by_surveyor(rows).items():
        surveyors.append([
            user, counts.get("checked", 0), counts.get("MATCH", 0),
            counts.get("NAME_MISMATCH_REVIEW", 0),
            counts.get("MISSING_LINE_TRANSFORMER_NAME", 0),
            counts.get("AMBIGUOUS_CONNECTED_SOURCES", 0),
            counts.get("SOURCE_UNVERIFIED", 0),
            counts.get("TRANSFORMER_NAME_UNVERIFIED", 0),
        ])

    definition.append(["Rule", "Meaning"])
    definition.append(["Name consistency", "Line Transformer_Name should match Transfomer_name_ of the verified supplying distribution transformer."])
    definition.append(["Evidence", "REG Utility Network connected trace from the distribution transformer's secondary terminal; validateConsistency=True."])
    definition.append(["Caution", "Connected topology alone cannot prove energized source/direction or switching state."])
    definition.append(["MISMATCH_REVIEW", "One connected distribution transformer is identified, but names differ. Verify switching/source before correcting."])
    definition.append(["MISSING_LINE_TRANSFORMER_NAME", "Line name blank and one connected transformer name available."])
    definition.append(["MULTISOURCE", "If connected trace reaches multiple transformer points, do not force an automatic match."])
    definition.append(["SCOPE", "Only transformer points inside selected administrative area are starting points. Lines supplied across boundaries can remain SOURCE_UNVERIFIED."])
    definition.append(["Source records", "All transformer points are queried irrespective of selected survey dates. LV line dates and surveyor filters select lines for review."])
    definition.append(["Excluded", "Other Electric Device asset groups (CT, VT, breakers, switches etc.) are excluded."])
    definition.append(["Read-only", "No GIS attributes or associations are changed automatically."])
    definition.append(["Date caveat", "A recent-date selection cannot establish historical network-wide compliance."])
    definition.append(["Name normalization", "Case and repeated whitespace are ignored; no fuzzy/substring name matching."])

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(wrap_text=True)
        for col in sheet.columns:
            cells = list(col)
            sheet.column_dimensions[cells[0].column_letter].width = min(
                70, max(14, max(len(str(c.value or "")) for c in cells[:1200]) + 2)
            )
        # Prevent external attribute text from becoming Excel formulas.
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.data_type = "s"
    for sheet, table_name in (
        (review, "LVTransformerNameReview"), (all_lines, "AllLVTransformerNames"),
        (surveyors, "LVTransformerSurveyors")
    ):
        if sheet.max_row > 1:
            table = Table(
                displayName=table_name,
                ref=f"A1:{sheet.cell(1,sheet.max_column).column_letter}{sheet.max_row}",
            )
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            sheet.add_table(table)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"Report already exists: {output_path}")
    wb.save(output_path)


def run_transformer_line_name_audit(
    output_xlsx: str | Path,
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    district: str | Sequence[str] | None = None,
    sectors: Sequence[str] | None = None,
    cells: Sequence[str] | None = None,
    usernames: Sequence[str] | None = None,
    custom_boundary_geometry: dict | None = None,
    service_url: str | None = None,
    boundary_service_url: str | None = None,
    version: str = "sde.DEFAULT",
    gis: Any | None = None,
) -> dict[str, Any]:
    """Verify only trace-supported name differences; all other lines are unverified."""
    start, end = _as_date(start_date), _as_date(end_date)
    if end < start:
        raise ValueError("End date precedes start date.")
    output = Path(output_xlsx).expanduser().resolve()
    if output.suffix.casefold() != ".xlsx":
        raise ValueError("Output must be an .xlsx workbook.")
    output = output.with_name(
        f"{output.stem}_{datetime.now():%Y%m%d_%H%M%S}{output.suffix}"
    )
    active_gis = _get_gis(gis)
    service = service_url or os.environ.get("UN_REPORT_SERVICE_URL", DEFAULT_LINE_SERVICE_URL)
    boundary_url = boundary_service_url or os.environ.get(
        "UN_SECTOR_BOUNDARY_URL", DEFAULT_BOUNDARY_SERVICE_URL
    )
    from arcgis.features import FeatureLayer
    lines = FeatureLayer(_layer_url(service, LINE_LAYER_ID), active_gis)
    transformers = FeatureLayer(_layer_url(service, TRANSFORMER_LAYER_ID), active_gis)
    sector_layer = FeatureLayer(_layer_url(boundary_url, SECTOR_LAYER_ID), active_gis)
    cell_layer = FeatureLayer(_layer_url(boundary_url, CELL_LAYER_ID), active_gis)
    boundary_features = None
    if custom_boundary_geometry is None:
        boundary_features = _get_sector_features(
            sector_layer, district, sectors, cell_layer, cells
        )
    filters = _filters_for_area(boundary_features, custom_boundary_geometry)

    transformer_name_field = resolve_fields(
        [dict(v) for v in transformers.properties.fields], "transformer"
    ).get("name")
    if not transformer_name_field:
        raise RuntimeError(
            "Cannot verify live distribution-transformer name field. "
            "Expected Transfomer_name_ or a unique recognized alias."
        )
    fields = {str(v["name"]).casefold(): str(v["name"])
              for v in lines.properties.fields}
    if "transformer_name" not in fields:
        raise RuntimeError(
            "LV line layer lacks Transformer_Name; cannot compare names."
        )
    line_fields = [
        "OBJECTID", "GLOBALID", "ASSETGROUP", "ASSETTYPE",
        "Transformer_Name", "created_user",
    ]
    transformer_fields = [
        "OBJECTID", "GLOBALID", "ASSETGROUP", "ASSETTYPE",
        transformer_name_field,
    ]
    _progress("Searching LV lines within selected districts and survey dates.")
    selected_lines = query_attributes_in_batches(
        lines, build_quality_where(start,end,usernames), version,
        line_fields, filters, _query_with_retry,
        asset_label="LV line", progress=_progress,
    )
    _progress("Searching eligible distribution transformers in selected area.")
    points = query_attributes_in_batches(
        transformers, "ASSETGROUP = 12 AND ASSETTYPE IN (1,2,3,4,5,6)",
        version, transformer_fields, filters, _query_with_retry,
        asset_label="Distribution transformer", progress=_progress,
    )
    if selected_lines and not points:
        _progress("No local distribution transformer points: all line sources will remain unverified.")
    _progress(
        f"Tracing {len(points)} distribution transformers against current Utility Network topology. "
        "This may take longer than the attribute-only LV watcher."
    )
    # Every trace is required: skipping failed traces could falsely assign
    # a single transformer to a multi-supply component.
    traces = trace_connected_lv_lines(
        active_gis, service, points, version, LINE_LAYER_ID, TRANSFORMER_LAYER_ID
    )
    canonical_points = [
        {
            **point,
            "Transfomer_name_": point.get(transformer_name_field),
        }
        for point in points
    ]
    findings = assess_line_transformer_names(selected_lines, canonical_points, traces)
    totals = Counter(item["status"] for item in findings)
    _write_workbook(
        output, findings, len(points), selected_districts(district),
        start, end, service, version,
    )
    return {
        "read_only": True,
        "output_xlsx": str(output),
        "districts": selected_districts(district),
        "lines_checked": len(findings),
        "transformer_points_traced": len(points),
        "matches": totals["MATCH"],
        "name_mismatches_for_review": totals["NAME_MISMATCH_REVIEW"],
        "missing_line_transformer_names": totals["MISSING_LINE_TRANSFORMER_NAME"],
        "ambiguous_sources": totals["AMBIGUOUS_CONNECTED_SOURCES"],
        "unverified_sources": totals["SOURCE_UNVERIFIED"],
        "unnamed_transformer_points": totals["TRANSFORMER_NAME_UNVERIFIED"],
    }

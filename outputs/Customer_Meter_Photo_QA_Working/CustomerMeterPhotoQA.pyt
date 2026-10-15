"""ArcGIS Pro Python toolbox for customer meter-photo quality checks."""

from __future__ import annotations

import re
import json
import importlib
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import arcpy


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
# ArcGIS Pro may cache the identically named meter_photo_qa package from
# another toolbox folder (for example Customer_Meter_Photo_QA_Clean).
# Remove only modules loaded from outside this toolbox's own src directory.
# This is necessary even when SRC has already been added to sys.path.
if str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

def _uses_other_toolbox(module):
    path = getattr(module, "__file__", None)
    if not path:
        package_paths = getattr(module, "__path__", ())
        return bool(package_paths) and not any(
            Path(p).resolve() == (SRC / "meter_photo_qa").resolve()
            for p in package_paths
        )
    try:
        return not Path(path).resolve().is_relative_to(SRC.resolve())
    except (OSError, ValueError):
        return True

if any(
    name == "meter_photo_qa" or name.startswith("meter_photo_qa.")
    for name in sys.modules
    if _uses_other_toolbox(sys.modules[name])
):
    for name in list(sys.modules):
        if name == "meter_photo_qa" or name.startswith("meter_photo_qa."):
            sys.modules.pop(name, None)

try:
    from meter_photo_qa.arcgis_inventory import run_inventory
    from meter_photo_qa import progress_report as _progress_report
    from meter_photo_qa import quality_watcher as _quality_watcher
    from meter_photo_qa import substation_containment as _substation_containment
    from meter_photo_qa import relay_associations as _relay_associations
    from meter_photo_qa import asset_quality_runner as _asset_quality_runner
    from meter_photo_qa import transformer_line_audit as _transformer_line_audit
    from meter_photo_qa import duplicate_line_inspector as _duplicate_line_inspector
    from meter_photo_qa import duplicate_line_scanner as _duplicate_line_scanner
    from meter_photo_qa import gicumbi_pamela_profile as _gicumbi_pamela_profile
    from meter_photo_qa import smart_query as _smart_query
    from meter_photo_qa import smart_query_runner as _smart_query_runner
    from meter_photo_qa import lv_feeder_report as _lv_feeder_report
    from meter_photo_qa import combined_qa_report as _combined_qa_report
    from meter_photo_qa import template_attribute_audit as _template_attribute_audit
    from meter_photo_qa import template_audit_runner as _template_audit_runner
    from meter_photo_qa import notification_setup as _notification_setup

    # ArcGIS Pro keeps imported Python modules in memory after a toolbox refresh.
    # Reload the helpers so newly added parameters and logic become available
    # immediately without requiring the user to restart Pro.
    _progress_report = importlib.reload(_progress_report)
    _quality_watcher = importlib.reload(_quality_watcher)
    _substation_containment = importlib.reload(_substation_containment)
    _relay_associations = importlib.reload(_relay_associations)
    _asset_quality_runner = importlib.reload(_asset_quality_runner)
    _transformer_line_audit = importlib.reload(_transformer_line_audit)
    _duplicate_line_inspector = importlib.reload(_duplicate_line_inspector)
    _duplicate_line_scanner = importlib.reload(_duplicate_line_scanner)
    _gicumbi_pamela_profile = importlib.reload(_gicumbi_pamela_profile)
    _smart_query = importlib.reload(_smart_query)
    _smart_query_runner = importlib.reload(_smart_query_runner)
    _lv_feeder_report = importlib.reload(_lv_feeder_report)
    _combined_qa_report = importlib.reload(_combined_qa_report)
    _template_attribute_audit = importlib.reload(_template_attribute_audit)
    _template_audit_runner = importlib.reload(_template_audit_runner)
    _notification_setup = importlib.reload(_notification_setup)
except Exception:
    try:
        error_folder = ROOT / "outputs"
        error_folder.mkdir(parents=True, exist_ok=True)
        (error_folder / "toolbox_import_error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
    except Exception:
        pass
    raise

DEFAULT_BOUNDARY_SERVICE_URL = _progress_report.DEFAULT_BOUNDARY_SERVICE_URL
DEFAULT_LINE_SERVICE_URL = _progress_report.DEFAULT_LINE_SERVICE_URL
DEFAULT_USER_NAME_MAP_PATH = _progress_report.DEFAULT_USER_NAME_MAP_PATH
CUSTOM_BOUNDARY_TEMPLATE = ROOT / "config" / "custom_boundary_template.lyrx"
generate_progress_report = _progress_report.generate_progress_report
load_boundary_index = _progress_report.load_boundary_index
load_cell_index = _progress_report.load_cell_index
load_province_index = _progress_report.load_province_index
DEFAULT_QUALITY_RULES_PATH = _quality_watcher.DEFAULT_QUALITY_RULES_PATH
run_quality_watcher = _quality_watcher.run_quality_watcher
run_asset_quality = _asset_quality_runner.run_asset_quality
run_transformer_line_name_audit = _transformer_line_audit.run_transformer_line_name_audit
inspect_duplicate_line_globalid = _duplicate_line_inspector.inspect_duplicate_line_globalid
scan_electric_line_duplicate_globalids = _duplicate_line_scanner.scan_electric_line_duplicate_globalids
run_gicumbi_pamela_profile = _gicumbi_pamela_profile.run_gicumbi_pamela_profile
run_smart_query = _smart_query_runner.run_smart_query
run_lv_feeder_report = _lv_feeder_report.run_lv_feeder_report
run_combined_qa_report = _combined_qa_report.run_combined_qa_report
run_template_surveyor_audit = _template_audit_runner.run_template_surveyor_audit
configure_quality_notifications = _notification_setup.configure_monitoring
DEFAULT_SUBSTATION_SERVICE_URL = _substation_containment.DEFAULT_SUBSTATION_SERVICE_URL
KIGALI_MODE = _substation_containment.KIGALI_MODE
PROVINCE_MODE = _substation_containment.PROVINCE_MODE
ADMIN_MODE = _substation_containment.ADMIN_MODE
CUSTOM_MODE = _substation_containment.CUSTOM_MODE
AREA_MODES = _substation_containment.AREA_MODES
PREVIEW_MODE = _substation_containment.PREVIEW_MODE
APPLY_MODE = _substation_containment.APPLY_MODE
OPERATION_MODES = _substation_containment.OPERATION_MODES
run_substation_containment = _substation_containment.run_substation_containment
run_relay_associations = _relay_associations.run_relay_associations


class Toolbox:
    def __init__(self):
        self.label = "Customer Meter Photo QA - Read Only"
        self.alias = "customer_meter_photo_qa"
        self.tools = [
            PreflightMeterPhotoInventory,
            GenerateSurveyProgressReport,
            WatchLVLineDataQuality,
            WatchDistributionTransformerQuality,
            WatchLVPoleQuality,
            CheckLVTransformerNames,
            InspectElectricLineGlobalID,
            ScanAllElectricLineDuplicates,
            ReviewGicumbiPamelaTeam,
            AskReportApp,
            ConfigureQualityNotifications,
        ]


class PreflightMeterPhotoInventory:
    def __init__(self):
        self.label = "Preflight Meter Photo Inventory"
        self.description = "Read-only check for meter numbers and image attachments on LV Service-Meter objects."
        self.canRunInBackground = False

    def getParameterInfo(self):
        output = arcpy.Parameter(
            displayName="Output CSV",
            name="output_csv",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
        )
        output.filter.list = ["csv"]
        output.value = str(ROOT / "outputs" / "pilot_preflight.csv")

        limit = arcpy.Parameter(
            displayName="Maximum records",
            name="record_limit",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        limit.value = 500

        where = arcpy.Parameter(
            displayName="Additional SQL filter",
            name="extra_where",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        where.value = "1=1"

        service = arcpy.Parameter(
            displayName="Feature service URL",
            name="service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        ocr_engine = arcpy.Parameter(
            displayName="OCR Engine",
            name="ocr_engine",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        ocr_engine.filter.list = ["tesseract", "easyocr"]
        ocr_engine.value = "tesseract"
        return [output, limit, where, service, ocr_engine]

    def execute(self, parameters, messages):
        summary = run_inventory(
            output_csv=parameters[0].valueAsText,
            limit=int(parameters[1].value or 500),
            extra_where=parameters[2].valueAsText or "1=1",
            service_url=parameters[3].valueAsText or None,
            ocr_engine=parameters[4].valueAsText or "tesseract",
        )
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))


def _split_multivalue(value):
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip().strip("'").strip('"') for item in text.split(";") if item.strip()]


def _mapped_usernames(path=DEFAULT_USER_NAME_MAP_PATH):
    """Return locally configured usernames without making a service request."""
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            mapping = json.load(handle)
        return sorted(str(username) for username in mapping if str(username).strip())
    except Exception:
        return []


def _boundary_index():
    """Return the fast local index used by the district/sector selectors."""
    try:
        return load_boundary_index()
    except Exception:
        return {}


def _cell_index():
    """Return the fast local district/sector/cell selector index."""
    try:
        return load_cell_index()
    except Exception:
        return {}


def _province_index():
    """Return the local Rwanda province-to-district selector index."""
    try:
        return load_province_index()
    except Exception:
        return {}


def _matching_district(index, value):
    requested = str(value or "").strip().casefold()
    return next((name for name in index if name.casefold() == requested), None)


def _available_cells(index, district, sectors):
    sector_map = index.get(district, {}) if district else {}
    selected = {str(item).strip().casefold() for item in sectors if str(item).strip()}
    return sorted(
        {
            cell
            for sector, cells in sector_map.items()
            if sector.casefold() in selected
            for cell in cells
        },
        key=str.casefold,
    )



def _apply_multi_boundary_filters(parameters, district_index, sector_index, cell_index):
    """Fast fully local multi-district selector; qualify sectors/cells by district.

    A plain sector/cell name is allowed only for a single selected district.
    When adding a second district, old selections are retained only if they
    identify a unique area, otherwise removed to prevent silent mis-selection.
    """
    district_index_data = _boundary_index()
    cell_index_data = _cell_index()
    district_param = parameters[district_index]
    districts_available = list(district_index_data)
    district_param.filter.list = districts_available
    district_lookup = {name.casefold(): name for name in districts_available}
    entered = _split_multivalue(district_param.valueAsText)
    selected = list(dict.fromkeys(
        district_lookup[item.casefold()]
        for item in entered if item.casefold() in district_lookup
    ))
    if entered != selected:
        district_param.value = ";".join(selected) if selected else None

    multi = len(selected) > 1
    sector_options = (
        [f"{district} :: {sector}"
         for district in selected
         for sector in district_index_data.get(district, [])]
        if multi else district_index_data.get(selected[0], []) if selected else []
    )
    sector_param = parameters[sector_index]
    sector_param.filter.list = sector_options
    sector_lookup = {name.casefold(): name for name in sector_options}
    sectors_entered = _split_multivalue(sector_param.valueAsText)
    sectors_selected = []
    for item in sectors_entered:
        found = sector_lookup.get(item.casefold())
        if found is None and multi and " :: " not in item:
            candidates = [name for name in sector_options
                          if name.rsplit(" :: ", 1)[-1].casefold() == item.casefold()]
            if len(candidates) == 1:
                found = candidates[0]
        if found is None and not multi and " :: " in item:
            parts = item.split(" :: ", 1)
            if len(parts) == 2 and selected and parts[0].casefold() == selected[0].casefold():
                found = sector_lookup.get(parts[1].casefold())
        if found is not None and found not in sectors_selected:
            sectors_selected.append(found)
    if sectors_entered != sectors_selected:
        sector_param.value = ";".join(sectors_selected) if sectors_selected else None

    selected_pairs = []
    for value in sectors_selected:
        if multi:
            district, sector = value.split(" :: ", 1)
        else:
            district, sector = selected[0], value
        selected_pairs.append((district, sector))
    cell_options = []
    for district, sector in selected_pairs:
        for cell in cell_index_data.get(district, {}).get(sector, []):
            name = (f"{district} :: {sector} :: {cell}" if multi else cell)
            if name not in cell_options:
                cell_options.append(name)
    cell_options.sort(key=str.casefold)
    cell_param = parameters[cell_index]
    cell_param.filter.list = cell_options
    cell_lookup = {name.casefold(): name for name in cell_options}
    cells_entered = _split_multivalue(cell_param.valueAsText)
    cells_selected = []
    for item in cells_entered:
        found = cell_lookup.get(item.casefold())
        if found is None and multi and " :: " not in item:
            candidates = [name for name in cell_options
                          if name.rsplit(" :: ", 1)[-1].casefold() == item.casefold()]
            if len(candidates) == 1:
                found = candidates[0]
        if found is None and not multi and " :: " in item:
            parts = item.split(" :: ")
            if len(parts) == 3 and selected and parts[0].casefold() == selected[0].casefold():
                found = cell_lookup.get(parts[2].casefold())
        if found is not None and found not in cells_selected:
            cells_selected.append(found)
    if cells_entered != cells_selected:
        cell_param.value = ";".join(cells_selected) if cells_selected else None


def _apply_boundary_filters(
    parameters,
    district_index,
    sector_index,
    cell_index,
    province_index=None,
):
    """Populate and cascade districts, sectors, and cells locally."""
    if getattr(parameters[district_index], "multiValue", False) and province_index is None:
        return _apply_multi_boundary_filters(
            parameters, district_index, sector_index, cell_index
        )
    index = _boundary_index()
    cells_by_area = _cell_index()
    available_districts = list(index)
    if province_index is not None:
        provinces = _province_index()
        parameters[province_index].filter.list = list(provinces)
        requested_province = str(parameters[province_index].valueAsText or "").casefold()
        matched_province = next(
            (name for name in provinces if name.casefold() == requested_province), None
        )
        if matched_province:
            available_districts = provinces[matched_province]
    parameters[district_index].filter.list = available_districts
    requested_district = str(parameters[district_index].valueAsText or "").casefold()
    district = next(
        (name for name in available_districts if name.casefold() == requested_district),
        None,
    )
    if requested_district and district is None:
        parameters[district_index].value = None
    available = index.get(district, []) if district else []
    parameters[sector_index].filter.list = available

    selected = _split_multivalue(parameters[sector_index].valueAsText)
    lookup = {sector.casefold(): sector for sector in available}
    valid = [lookup[item.casefold()] for item in selected if item.casefold() in lookup]
    if selected != valid:
        parameters[sector_index].value = ";".join(valid) if valid else None

    available_cells = _available_cells(cells_by_area, district, valid)
    parameters[cell_index].filter.list = available_cells
    selected_cells = _split_multivalue(parameters[cell_index].valueAsText)
    cell_lookup = {cell.casefold(): cell for cell in available_cells}
    valid_cells = [
        cell_lookup[item.casefold()]
        for item in selected_cells
        if item.casefold() in cell_lookup
    ]
    if selected_cells != valid_cells:
        parameters[cell_index].value = ";".join(valid_cells) if valid_cells else None


def _drawn_boundary_geometry(parameter):
    """Return one REST polygon made from the user's feature-set sketches."""
    source = parameter.value
    if source in (None, ""):
        return None

    rings = []
    spatial_reference = None
    serialized = getattr(source, "JSON", None)
    if serialized:
        feature_set = json.loads(serialized)
        spatial_reference = feature_set.get("spatialReference")
        for feature in feature_set.get("features", []):
            geometry = feature.get("geometry") or {}
            rings.extend(geometry.get("rings", []))
            spatial_reference = (
                spatial_reference or geometry.get("spatialReference")
            )
        if rings and spatial_reference:
            return {"rings": rings, "spatialReference": spatial_reference}
        rings = []

    try:
        with arcpy.da.SearchCursor(source, ["SHAPE@"]) as cursor:
            for (shape,) in cursor:
                if shape is None:
                    continue
                geometry = json.loads(shape.JSON)
                rings.extend(geometry.get("rings", []))
                spatial_reference = (
                    spatial_reference or geometry.get("spatialReference")
                )
    except Exception as exc:
        # The default layer file supplies only the sketch schema and contains
        # no feature. It is therefore equivalent to no custom boundary.
        value_text = str(parameter.valueAsText or "").strip()
        if value_text.lower().endswith(".lyrx"):
            return None
        raise ValueError(
            "The custom boundary could not be read. Clear it and draw the polygon again."
        ) from exc

    if not rings:
        return None
    if not spatial_reference:
        described = arcpy.Describe(source).spatialReference
        if described.factoryCode:
            spatial_reference = {"wkid": int(described.factoryCode)}
        else:
            spatial_reference = {"wkt": described.exportToString()}
    return {"rings": rings, "spatialReference": spatial_reference}


def _log_tool_open_errors(method):
    """Preserve ArcGIS Pro's hidden parameter-pane traceback for support."""
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            details = traceback.format_exc()
            try:
                output_folder = ROOT / "outputs"
                output_folder.mkdir(parents=True, exist_ok=True)
                (output_folder / "toolbox_open_error.log").write_text(
                    details, encoding="utf-8"
                )
            except Exception:
                pass
            arcpy.AddError(details)
            raise
    return wrapped


class GenerateSurveyProgressReport:
    _districts = None
    _sector_cache = {}
    _user_cache = {}

    def __init__(self):
        self.label = "Generate Survey Progress Report"
        self.description = (
            "Create a styled Excel report of surveyed LV line kilometres for one "
            "or many selected surveyors. Distribution transformers inside the selected "
            "boundary are followed with a read-only Connected utility-network trace; "
            "the selected dates and surveyors are applied to the connected LV lines."
        )
        self.canRunInBackground = False

    @_log_tool_open_errors
    def getParameterInfo(self):
        today = datetime.now().date()
        boundary_index = _boundary_index()
        cell_index = _cell_index()
        districts = list(boundary_index)
        default_district = _matching_district(boundary_index, "Gasabo")
        default_sectors = boundary_index.get(default_district, []) if default_district else []
        selected_default_sectors = [
            sector for sector in ("Remera", "Rusororo", "Rutunga")
            if sector in default_sectors
        ]
        default_cells = _available_cells(
            cell_index, default_district, selected_default_sectors
        )

        output = arcpy.Parameter(
            displayName="Output Excel report",
            name="output_xlsx",
            datatype="DEFile",
            parameterType="Required",
            direction="Output",
        )
        output.filter.list = ["xlsx"]
        output.value = str(
            ROOT / "outputs" / f"survey_progress_report_{today:%Y%m%d}.xlsx"
        )

        start = arcpy.Parameter(
            displayName="From date",
            name="start_date",
            datatype="GPDate",
            parameterType="Required",
            direction="Input",
        )
        start.value = datetime.combine(today - timedelta(days=14), datetime.min.time())

        end = arcpy.Parameter(
            displayName="To date (inclusive)",
            name="end_date",
            datatype="GPDate",
            parameterType="Required",
            direction="Input",
        )
        end.value = datetime.combine(today, datetime.min.time())

        district = arcpy.Parameter(
            displayName="District(s) - select one or more",
            name="district",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        district.filter.type = "ValueList"
        district.filter.list = districts
        district.value = default_district

        sectors = arcpy.Parameter(
            displayName="Sector(s)",
            name="sectors",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        sectors.filter.type = "ValueList"
        sectors.filter.list = default_sectors
        sectors.value = ";".join(selected_default_sectors)

        cells = arcpy.Parameter(
            displayName="Cell(s)",
            name="cells",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        cells.filter.type = "ValueList"
        cells.filter.list = default_cells

        custom_boundary = arcpy.Parameter(
            displayName="Custom boundary (draw polygon) - optional",
            name="custom_boundary",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Optional",
            direction="Input",
        )
        custom_boundary.value = str(CUSTOM_BOUNDARY_TEMPLATE)

        users = arcpy.Parameter(
            displayName="Surveyor(s)",
            name="usernames",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True,
        )
        users.filter.type = "ValueList"
        users.filter.list = _mapped_usernames()
        users.value = ";".join(users.filter.list)

        service = arcpy.Parameter(
            displayName="Line feature service URL",
            name="line_service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        service.value = DEFAULT_LINE_SERVICE_URL
        service.category = "Advanced"

        boundaries = arcpy.Parameter(
            displayName="Sector and cell boundary service URL",
            name="boundary_service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        boundaries.value = DEFAULT_BOUNDARY_SERVICE_URL
        boundaries.category = "Advanced"

        version = arcpy.Parameter(
            displayName="Utility network version",
            name="gdb_version",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        version.value = "sde.DEFAULT"
        version.category = "Advanced"

        name_map = arcpy.Parameter(
            displayName="Surveyor name mapping JSON",
            name="user_name_map_path",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        name_map.filter.list = ["json"]
        name_map.value = str(DEFAULT_USER_NAME_MAP_PATH)
        name_map.category = "Advanced"

        return [
            output,
            start,
            end,
            district,
            sectors,
            cells,
            custom_boundary,
            users,
            service,
            boundaries,
            version,
            name_map,
        ]

    def updateParameters(self, parameters):
        # Tool validation stays fast: boundaries and users come from local
        # indexes, while live feature services are queried only when Run starts.
        _apply_boundary_filters(parameters, 3, 4, 5)
        name_map_path = parameters[11].valueAsText or DEFAULT_USER_NAME_MAP_PATH
        parameters[7].filter.list = _mapped_usernames(name_map_path)

    def updateMessages(self, parameters):
        if parameters[1].value and parameters[2].value:
            if parameters[2].value < parameters[1].value:
                parameters[2].setErrorMessage(
                    "The end date cannot be earlier than the start date."
                )
        has_custom_boundary = _drawn_boundary_geometry(parameters[6]) is not None
        if parameters[4].valueAsText and not parameters[3].valueAsText and not has_custom_boundary:
            parameters[3].setErrorMessage(
                "Choose a district before choosing sectors."
            )
        if parameters[5].valueAsText and not parameters[4].valueAsText and not has_custom_boundary:
            parameters[4].setErrorMessage(
                "Choose at least one sector before choosing cells."
            )

    def execute(self, parameters, messages):
        sectors = _split_multivalue(parameters[4].valueAsText)
        cells = _split_multivalue(parameters[5].valueAsText)
        custom_boundary_geometry = _drawn_boundary_geometry(parameters[6])
        usernames = _split_multivalue(parameters[7].valueAsText)
        summary = generate_progress_report(
            output_xlsx=parameters[0].valueAsText,
            start_date=parameters[1].value,
            end_date=parameters[2].value,
            usernames=usernames,
            district=_split_multivalue(parameters[3].valueAsText),
            sectors=sectors,
            cells=cells,
            custom_boundary_geometry=custom_boundary_geometry,
            service_url=parameters[8].valueAsText or None,
            boundary_service_url=parameters[9].valueAsText or None,
            version=parameters[10].valueAsText or "sde.DEFAULT",
            user_name_map_path=parameters[11].valueAsText or None,
        )
        arcpy.SetParameterAsText(0, summary["output_xlsx"])
        arcpy.AddMessage(
            f"Created {summary['output_xlsx']} for {len(summary['reported_users'])} "
            f"surveyor(s), totalling {summary['total_km']:.2f} km."
        )
        if summary.get("tracking_log_sheet"):
            arcpy.AddMessage(
                f"Traced {summary.get('localized_transformers', 0)} localized transformer(s) "
                f"to {summary.get('connected_lv_feature_ids', 0)} distinct LV feature(s). "
                f"The {summary.get('boundary_crossing_records', 0)} boundary-crossing "
                f"and {summary.get('followed_outside_records', 0)} followed-outside "
                f"record(s) are detailed in {summary['tracking_log_sheet']}."
            )
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))


class WatchLVLineDataQuality:
    _districts = None
    _sector_cache = {}
    _user_cache = {}

    def __init__(self):
        self.label = "Watch LV Line Data Quality"
        self.description = (
            "Check newly created or edited LV lines across Rwanda. "
            "Transformer Name is mandatory; meeting the completion threshold is not final approval."
        )
        self.canRunInBackground = False

    @_log_tool_open_errors
    def getParameterInfo(self):
        opened_at = datetime.now()
        today = opened_at.date()
        boundary_index = _boundary_index()
        districts = list(boundary_index)
        try:
            default_gdb = arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
        except Exception:
            default_gdb = arcpy.env.scratchGDB

        output = arcpy.Parameter(
            displayName="Output Excel QA report",
            name="output_xlsx",
            datatype="DEFile",
            parameterType="Required",
            direction="Output",
        )
        output.filter.list = ["xlsx"]
        output.value = str(ROOT / "outputs" / f"lv_line_quality_watcher_{opened_at:%Y%m%d_%H%M%S}.xlsx")

        flagged_fc = arcpy.Parameter(
            displayName="Flagged LV lines",
            name="output_flagged_lines",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Output",
        )
        flagged_fc.value = str(Path(default_gdb) / f"Flagged_LV_Lines_{opened_at:%Y%m%d_%H%M%S}")

        start = arcpy.Parameter(
            displayName="From date (created or edited)",
            name="start_date",
            datatype="GPDate",
            parameterType="Required",
            direction="Input",
        )
        start.value = datetime.combine(today - timedelta(days=1), datetime.min.time())

        end = arcpy.Parameter(
            displayName="To date (inclusive)",
            name="end_date",
            datatype="GPDate",
            parameterType="Required",
            direction="Input",
        )
        end.value = datetime.combine(today, datetime.min.time())

        district = arcpy.Parameter(
            displayName="District(s) - blank for all Rwanda",
            name="district",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        district.filter.type = "ValueList"
        district.filter.list = districts

        sectors = arcpy.Parameter(
            displayName="Sector(s) - blank for all sectors in district",
            name="sectors",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        sectors.filter.type = "ValueList"
        sectors.filter.list = []

        cells = arcpy.Parameter(
            displayName="Cell(s)",
            name="cells",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        cells.filter.type = "ValueList"
        cells.filter.list = []

        custom_boundary = arcpy.Parameter(
            displayName="Custom boundary (draw polygon) - optional",
            name="custom_boundary",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Optional",
            direction="Input",
        )
        custom_boundary.value = str(CUSTOM_BOUNDARY_TEMPLATE)

        users = arcpy.Parameter(
            displayName="Surveyor(s) - leave blank for all",
            name="usernames",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        users.filter.type = "ValueList"
        users.filter.list = _mapped_usernames()

        threshold = arcpy.Parameter(
            displayName="Minimum completion threshold (%)",
            name="minimum_completion_percent",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input",
        )
        self._loaded_default_threshold = float(_quality_watcher.load_quality_rules()["minimum_completion_percent"])
        threshold.value = self._loaded_default_threshold
        threshold.filter.type = "Range"
        threshold.filter.list = [0, 100]

        service = arcpy.Parameter(
            displayName="Line feature service URL",
            name="line_service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        service.value = DEFAULT_LINE_SERVICE_URL
        service.category = "Advanced"

        boundaries = arcpy.Parameter(
            displayName="Sector and cell boundary service URL",
            name="boundary_service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        boundaries.value = DEFAULT_BOUNDARY_SERVICE_URL
        boundaries.category = "Advanced"

        version = arcpy.Parameter(
            displayName="Utility network version",
            name="gdb_version",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        version.value = "sde.DEFAULT"
        version.category = "Advanced"

        name_map = arcpy.Parameter(
            displayName="Surveyor name mapping JSON",
            name="user_name_map_path",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        name_map.filter.list = ["json"]
        name_map.value = str(DEFAULT_USER_NAME_MAP_PATH)
        name_map.category = "Advanced"

        rules = arcpy.Parameter(
            displayName="Quality rules JSON",
            name="quality_rules_path",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        rules.filter.list = ["json"]
        rules.value = str(DEFAULT_QUALITY_RULES_PATH)
        rules.category = "Advanced"

        previous_report = arcpy.Parameter(
            displayName="Previous QA report (carry forward reviews) - blank uses latest",
            name="previous_review_report",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        previous_report.filter.list = ["xlsx"]
        previous_report.category = "Advanced"

        return [
            output, flagged_fc, start, end, district, sectors, cells,
            custom_boundary, users, threshold, service, boundaries, version,
            name_map, rules, previous_report,
        ]

    def updateParameters(self, parameters):
        # Keep the pane responsive; the actual feature service is queried only
        # when Run is clicked. Selectors come from the local boundary index.
        _apply_boundary_filters(parameters, 4, 5, 6)
        name_map_path = parameters[13].valueAsText or DEFAULT_USER_NAME_MAP_PATH
        parameters[8].filter.list = _mapped_usernames(name_map_path)
        try:
            active_rules = _quality_watcher.load_quality_rules(parameters[14].valueAsText or None)
            new_default = float(active_rules["minimum_completion_percent"])
            current_value = float(parameters[9].value) if parameters[9].value is not None else None
            if current_value is None or current_value == getattr(self, "_loaded_default_threshold", None):
                parameters[9].value = new_default
            self._loaded_default_threshold = new_default
        except Exception:
            pass

    def updateMessages(self, parameters):
        if parameters[2].value and parameters[3].value:
            if parameters[3].value < parameters[2].value:
                parameters[3].setErrorMessage(
                    "The end date cannot be earlier than the start date."
                )
        has_custom_boundary = _drawn_boundary_geometry(parameters[7]) is not None
        if parameters[5].valueAsText and not parameters[4].valueAsText and not has_custom_boundary:
            parameters[4].setErrorMessage("Choose a district before choosing sectors.")
        if parameters[6].valueAsText and not parameters[5].valueAsText and not has_custom_boundary:
            parameters[5].setErrorMessage(
                "Choose at least one sector before choosing cells."
            )
        if parameters[9].value is not None:
            threshold = float(parameters[9].value)
            if not 0 <= threshold <= 100:
                parameters[9].setErrorMessage("Enter a percentage from 0 to 100.")
        try:
            _quality_watcher.load_quality_rules(parameters[14].valueAsText or None)
        except Exception as exc:
            parameters[14].setErrorMessage(str(exc))
        if not parameters[4].valueAsText and not has_custom_boundary:
            parameters[4].setWarningMessage("The run will check all Rwanda districts and sectors in the selected dates.")

    def execute(self, parameters, messages):
        summary = run_quality_watcher(
            output_xlsx=parameters[0].valueAsText,
            output_flagged_feature_class=parameters[1].valueAsText or None,
            start_date=parameters[2].value,
            end_date=parameters[3].value,
            district=_split_multivalue(parameters[4].valueAsText),
            sectors=_split_multivalue(parameters[5].valueAsText),
            cells=_split_multivalue(parameters[6].valueAsText),
            custom_boundary_geometry=_drawn_boundary_geometry(parameters[7]),
            usernames=_split_multivalue(parameters[8].valueAsText),
            minimum_completion_percent=float(parameters[9].value if parameters[9].value is not None else _quality_watcher.load_quality_rules(parameters[14].valueAsText or None)["minimum_completion_percent"]),
            service_url=parameters[10].valueAsText or None,
            boundary_service_url=parameters[11].valueAsText or None,
            version=parameters[12].valueAsText or "sde.DEFAULT",
            user_name_map_path=parameters[13].valueAsText or None,
            rules_path=parameters[14].valueAsText or None,
            previous_review_report=parameters[15].valueAsText or None,
        )
        arcpy.SetParameterAsText(0, summary["output_xlsx"])
        if summary["output_flagged_feature_class"]:
            arcpy.SetParameterAsText(1, summary["output_flagged_feature_class"])
        arcpy.AddMessage(
            f"Checked {summary['total_lines']} LV lines: "
            f"{summary['met_threshold_lines']} met the threshold and {summary['flagged_lines']} flagged. "
            f"The Review Queue carries {summary['review_queue_items']} item(s)."
        )
        if summary["total_lines"] == 0:
            arcpy.AddWarning("No matching LV lines were found. Check the dates and area before treating this as a clean result.")
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))



class _AssetQualityTool:
    asset = None
    label = "Asset Data Quality"
    canRunInBackground = False

    def __init__(self):
        self.description = (
            "Read-only REG Utility Network QA. Checks the selected asset "
            "group only, uses live field names, and separates unverified "
            "schema fields from confirmed missing attribute values."
        )

    @_log_tool_open_errors
    def getParameterInfo(self):
        opened = datetime.now()
        today = opened.date()
        output = arcpy.Parameter(
            displayName="Output Excel QA report",
            name="output_xlsx",
            datatype="DEFile", parameterType="Required", direction="Output",
        )
        output.filter.list = ["xlsx"]
        output.value = str(
            ROOT / "outputs" / f"{self.asset}_quality_{opened:%Y%m%d_%H%M%S}.xlsx"
        )
        start = arcpy.Parameter(
            displayName="From date (created or edited)", name="start_date",
            datatype="GPDate", parameterType="Required", direction="Input",
        )
        start.value = datetime.combine(today - timedelta(days=14), datetime.min.time())
        end = arcpy.Parameter(
            displayName="To date (inclusive)", name="end_date",
            datatype="GPDate", parameterType="Required", direction="Input",
        )
        end.value = datetime.combine(today, datetime.min.time())
        district = arcpy.Parameter(
            displayName="District(s) - blank for all Rwanda", name="district",
            datatype="GPString", parameterType="Optional", direction="Input",
            multiValue=True,
        )
        district.filter.type = "ValueList"
        district.filter.list = list(_boundary_index())
        sectors = arcpy.Parameter(
            displayName="Sector(s) - blank for all in districts", name="sectors",
            datatype="GPString", parameterType="Optional", direction="Input",
            multiValue=True,
        )
        sectors.filter.type = "ValueList"
        sectors.filter.list = []
        cells = arcpy.Parameter(
            displayName="Cell(s)", name="cells",
            datatype="GPString", parameterType="Optional", direction="Input",
            multiValue=True,
        )
        cells.filter.type = "ValueList"
        cells.filter.list = []
        custom = arcpy.Parameter(
            displayName="Custom boundary (draw polygon) - optional",
            name="custom_boundary",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Optional", direction="Input",
        )
        custom.value = str(CUSTOM_BOUNDARY_TEMPLATE)
        users = arcpy.Parameter(
            displayName="Surveyor(s) - blank for all",
            name="usernames", datatype="GPString",
            parameterType="Optional", direction="Input", multiValue=True,
        )
        users.filter.type = "ValueList"
        users.filter.list = _mapped_usernames()
        service = arcpy.Parameter(
            displayName="Utility Network FeatureServer URL",
            name="service_url", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        service.value = DEFAULT_LINE_SERVICE_URL
        service.category = "Advanced"
        boundaries = arcpy.Parameter(
            displayName="Administrative Boundary FeatureServer URL",
            name="boundary_service_url", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        boundaries.value = DEFAULT_BOUNDARY_SERVICE_URL
        boundaries.category = "Advanced"
        version = arcpy.Parameter(
            displayName="Utility Network Version",
            name="gdb_version", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        version.value = "sde.DEFAULT"
        version.category = "Advanced"
        return [output, start, end, district, sectors, cells,
                custom, users, service, boundaries, version]

    def updateParameters(self, parameters):
        _apply_boundary_filters(parameters, 3, 4, 5)

    def updateMessages(self, parameters):
        if parameters[1].value and parameters[2].value and parameters[2].value < parameters[1].value:
            parameters[2].setErrorMessage("The end date cannot be earlier than the start date.")
        custom = _drawn_boundary_geometry(parameters[6]) is not None
        if parameters[4].valueAsText and not parameters[3].valueAsText and not custom:
            parameters[3].setErrorMessage("Select district(s) before sectors.")
        if parameters[5].valueAsText and not parameters[4].valueAsText and not custom:
            parameters[4].setErrorMessage("Select sector(s) before cells.")

    def execute(self, parameters, messages):
        summary = run_asset_quality(
            asset=self.asset,
            output_xlsx=parameters[0].valueAsText,
            start_date=parameters[1].value,
            end_date=parameters[2].value,
            district=_split_multivalue(parameters[3].valueAsText),
            sectors=_split_multivalue(parameters[4].valueAsText),
            cells=_split_multivalue(parameters[5].valueAsText),
            custom_boundary_geometry=_drawn_boundary_geometry(parameters[6]),
            usernames=_split_multivalue(parameters[7].valueAsText),
            service_url=parameters[8].valueAsText or None,
            boundary_service_url=parameters[9].valueAsText or None,
            version=parameters[10].valueAsText or "sde.DEFAULT",
        )
        arcpy.SetParameterAsText(0, summary["output_xlsx"])
        arcpy.AddMessage(
            f"Checked {summary['total']} {self.asset}(s): "
            f"{summary['with_gaps']} with confirmed gaps, "
            f"{summary['not_verified']} not fully verified, "
            f"{summary['no_gaps_found']} with no gaps in verified fields."
        )
        if summary["unverified_live_fields"]:
            arcpy.AddWarning(
                "Unverified live schema fields: " +
                ", ".join(summary["unverified_live_fields"]) +
                ". Review the Schema Verification worksheet; "
                "do not treat these checks as complete."
            )
        if summary["duplicate_globalid_groups"]:
            arcpy.AddWarning(
                f"{summary['duplicate_globalid_groups']} repeated GlobalID group(s) "
                f"across {summary['duplicate_feature_records']} distinct "
                f"{self.asset} OBJECTIDs. Every record was retained in the QA "
                "workbook; see Duplicate GlobalIDs and Duplicate Asset Records. "
                "The identity issues are separate from the seven original "
                "transformer field checks. Do not delete GIS features automatically."
            )
        if summary["surveyor_filter"]:
            arcpy.AddWarning(
                f"This report includes ONLY {len(summary['surveyor_filter'])} "
                "selected surveyor account(s). To assess the full outstanding "
                "backlog, CLEAR Surveyor(s) entirely so the filter is blank. "
                "Do not interpret a lower gap count as confirmed corrections "
                "unless the same GlobalIDs are checked in both runs."
            )
        if summary["total"] and summary["incomplete_recorded_locations"]:
            arcpy.AddWarning(
                f"{summary['incomplete_recorded_locations']}/{summary['total']} "
                "features lack one or more recorded District/Sector/Cell "
                "attributes. 'By Recorded Location' is NOT a spatially "
                "verified sector/cell breakdown."
            )
        if summary["total"] == 0:
            arcpy.AddWarning(
                "No matching asset features. Verify date range, districts "
                "and surveyor filters before concluding there are no gaps."
            )
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))


class WatchDistributionTransformerQuality(_AssetQualityTool):
    asset = "transformer"
    label = "Watch Distribution Transformer Data Quality"


class WatchLVPoleQuality(_AssetQualityTool):
    asset = "pole"
    label = "Watch LV Pole Data Quality"






class AskReportApp:
    """Simple-language read-only attribute/spatial queries from ArcGIS Pro."""
    label = "Ask REPORTAPP - Query and Filter Attributes"
    description = (
        "Type a plain-language query, ask which surveyors have template " 
        "gaps or unusual field values, or 'Prepare LV Lines Report for "
        "Kwizerwa Edison in Gicumbi' to create a consolidated original "
        "LV Lines, Distribution Transformer and LV Pole QA Excel report. "
        "The tool validates live field names "
        "and previews a filtered count. Optionally make a local feature "
        "class containing matches and add it to the current map. "
        "No edits are made to the REG FeatureServer. For example: "
        "'Show LV poles in Gicumbi with missing manufacturer' or "
        "'Find transformers in Burera with protection switch is unknown'. "
        "This is a bounded interpreter, not an unrestricted AI chatbot."
    )
    canRunInBackground = False

    @_log_tool_open_errors
    def getParameterInfo(self):
        query = arcpy.Parameter(
            displayName="Tell REPORTAPP what to find",
            name="natural_language_query",
            datatype="GPString",
            parameterType="Required", direction="Input",
        )
        query.value = "Show LV poles in Gicumbi with missing manufacturer"
        mode = arcpy.Parameter(
            displayName="Action (preview first recommended)",
            name="query_mode",
            datatype="GPString",
            parameterType="Required", direction="Input",
        )
        mode.filter.type = "ValueList"
        mode.filter.list = [
            "Preview query and count only (read-only)",
            "Create local filtered layer and add to map (read-only source)",
            "Generate consolidated Excel QA report (Lines, Transformers, Poles)",
            "Generate surveyor attribute audit Excel report",
        ]
        mode.value = mode.filter.list[0]
        report = arcpy.Parameter(
            displayName="Output query interpretation (JSON)",
            name="output_query_log",
            datatype="DEFile",
            parameterType="Required", direction="Output",
        )
        report.filter.list = ["json"]
        report.value = str(
            ROOT / "outputs" /
            f"REPORTAPP_smart_query_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
        service = arcpy.Parameter(
            displayName="Utility Network FeatureServer URL",
            name="service_url",
            datatype="GPString", parameterType="Optional", direction="Input",
        )
        service.value = DEFAULT_LINE_SERVICE_URL
        service.category = "Advanced"
        boundary = arcpy.Parameter(
            displayName="Administrative Boundary FeatureServer URL",
            name="boundary_service_url",
            datatype="GPString", parameterType="Optional", direction="Input",
        )
        boundary.value = DEFAULT_BOUNDARY_SERVICE_URL
        boundary.category = "Advanced"
        destination = arcpy.Parameter(
            displayName="Destination folder for Excel reports and surveyor audits",
            name="report_destination", datatype="DEFolder",
            parameterType="Optional", direction="Input",
        )
        destination.value = str(ROOT / "outputs")
        feeder_method = arcpy.Parameter(
            displayName="LV feeder continuity mode (for Prepare LV Lines Report)",
            name="lv_feeder_method", datatype="GPString",
            parameterType="Required", direction="Input",
        )
        feeder_method.filter.type = "ValueList"
        feeder_method.filter.list = [
            "Geometry continuity - no Utility Network trace required",
            "Skip optional continuity appendix - three-asset QA only",
        ]
        feeder_method.value = feeder_method.filter.list[0]
        endpoint_gap = arcpy.Parameter(
            displayName="Maximum LV endpoint gap (metres; geometry mode)",
            name="endpoint_tolerance", datatype="GPDouble",
            parameterType="Required", direction="Input",
        )
        endpoint_gap.value = 1.5
        qa_start = arcpy.Parameter(
            displayName="QA from date (created or last edited)",
            name="qa_start_date", datatype="GPDate",
            parameterType="Required", direction="Input",
        )
        qa_start.value = datetime(2026, 1, 1)
        qa_end = arcpy.Parameter(
            displayName="QA to date (inclusive)",
            name="qa_end_date", datatype="GPDate",
            parameterType="Required", direction="Input",
        )
        qa_end.value = datetime.combine(datetime.now().date(), datetime.min.time())
        return [query, mode, report, service, boundary, destination,
                feeder_method, endpoint_gap, qa_start, qa_end]

    def updateParameters(self, params):
        """Relative date phrases keep the visible QA date controls in sync."""
        request=params[0].valueAsText or ""
        if _smart_query.is_report_instruction(request):
            params[1].value="Generate consolidated Excel QA report (Lines, Transformers, Poles)"
            try:
                parsed=_smart_query.parse_lv_report_request(request)
            except ValueError:
                return
            if parsed["date_start"] is not None:
                params[8].value=datetime.combine(parsed["date_start"], datetime.min.time())
                params[9].value=datetime.combine(parsed["date_end"], datetime.min.time())
        elif re.search(r"\\bsurveyors?\\b",request,re.I):
            params[1].value="Generate surveyor attribute audit Excel report"
        elif (params[1].valueAsText or "").startswith("Generate "):
            params[1].value="Preview query and count only (read-only)"

    def updateMessages(self, params):
        if params[0].valueAsText:
            try:
                if _smart_query.is_report_instruction(params[0].valueAsText):
                    _smart_query.parse_lv_report_request(params[0].valueAsText)
                elif re.search(r"\bsurveyors?\b", params[0].valueAsText, re.I):
                    _template_attribute_audit.parse_surveyor_template_request(
                        params[0].valueAsText
                    )
                else:
                    _smart_query.parse_request(params[0].valueAsText)
            except ValueError as exc:
                params[0].setErrorMessage(str(exc))

    def execute(self, parameters, messages):
        request = parameters[0].valueAsText or ""
        if _smart_query.is_report_instruction(request):
            parsed = _smart_query.parse_lv_report_request(request)
            destination = parameters[5].valueAsText
            if not destination:
                raise ValueError("Choose the Destination folder for the LV Lines report.")
            arcpy.AddMessage(
                "Starting transformers in " + parsed["district"] +
                "; including connected LV feeder segments even beyond district boundaries."
            )
            method = (
                "none" if parameters[6].valueAsText.startswith(
                    "Skip optional continuity"
                ) else "geometry"
            )
            if method == "geometry":
                arcpy.AddWarning(
                    "Cross-district continuity will be an OPTIONAL PROVISIONAL "
                    "APPENDIX. The three original QA audits are mandatory and "
                    "their gap counts are not replaced by geometric estimates."
                )
            arcpy.AddMessage(
                "Preparing the ORIGINAL three-asset QA checks in one Excel workbook: "
                "LV Lines, Distribution Transformers, and LV Poles."
            )
            period_from=parsed["date_start"] or parameters[8].value
            period_to=parsed["date_end"] or parameters[9].value
            if parsed["date_expression"]:
                arcpy.AddMessage(
                    f"Requested period ({parsed['date_expression']}): "
                    f"{period_from} to {period_to}, inclusive. "
                    "The date stated in the command overrides the QA date pickers."
                )
            report = run_combined_qa_report(
                output_folder=destination,
                district=parsed["district"],
                usernames=parsed["usernames"] or None,
                start_date=period_from,
                end_date=period_to,
                service_url=parameters[3].valueAsText or None,
                boundary_service_url=parameters[4].valueAsText or None,
                include_continuity=(method=="geometry"),
                endpoint_tolerance=float(parameters[7].value or 1.5),
                progress=arcpy.AddMessage,
            )
            arcpy.AddMessage(
                "Combined QA report saved: " + report["output_xlsx"]
            )
            arcpy.AddMessage(
                "Unmodified original component workbooks: " +
                report["components_folder"]
            )
            if report["geometry"]["status"] != "COMPLETE":
                arcpy.AddWarning(
                    "Provisional cross-district continuity NOT included: " +
                    str(report["geometry"].get("reason",report["geometry"]["status"]))
                )
            arcpy.AddMessage(
                f"All three mandatory QA checks completed. "
                f"Scope {report['district']} from {report['start_date']} "
                f"to {report['end_date']}."
            )
            return
        if re.search(r"\bsurveyors?\b", request, re.I):
            arcpy.AddMessage(
                "Running a read-only surveyor audit against the live asset "
                "template and authoritative geographic boundaries."
            )
            report = run_template_surveyor_audit(
                request=request,
                output_folder=parameters[5].valueAsText,
                output_json=parameters[2].valueAsText,
                service_url=parameters[3].valueAsText or None,
                boundary_service_url=parameters[4].valueAsText or None,
            )
            arcpy.SetParameterAsText(2, report["output_json"])
            arcpy.AddMessage(
                "Verified template conditions: " +
                json.dumps(report["resolved_criteria"],indent=2)
            )
            arcpy.AddMessage(
                f"{report['matching_features']:,} matching features from "
                f"{report['matching_surveyors']:,} surveyor account(s)."
            )
            arcpy.AddMessage(
                "Surveyor template audit Excel: " + report["output_xlsx"]
            )
            arcpy.AddWarning(
                "Source GIS data were not edited. No notifications have been "
                "sent. Recorded user is an account, not proof of historical "
                "personal authorship when accounts were transferred."
            )
            return
        mode = (
            "local_copy" if parameters[1].valueAsText.startswith(
                "Create local filtered layer"
            ) else "preview"
        )
        result = run_smart_query(
            request=parameters[0].valueAsText,
            mode=mode,
            output_json=parameters[2].valueAsText,
            service_url=parameters[3].valueAsText or None,
            boundary_service_url=parameters[4].valueAsText or None,
        )
        arcpy.SetParameterAsText(2, result["audit_log"])
        arcpy.AddMessage(
            "REPORTAPP interpreted your request as:\n" +
            json.dumps(result["interpreted"], indent=2)
        )
        arcpy.AddMessage("Verified SQL: " + result["attribute_sql"])
        if result["spatial_boundary_sql"]:
            arcpy.AddMessage("Administrative boundary SQL: " +
                             result["spatial_boundary_sql"])
        arcpy.AddMessage(
            f"{result['matched_features']:,} matching "
            f"{result['interpreted']['asset']} feature(s)."
        )
        if result["local_feature_class"]:
            arcpy.AddMessage(
                "Matching features copied locally to " +
                result["local_feature_class"] +
                " (source Utility Network unchanged)."
            )
        for caution in result["cautions"]:
            arcpy.AddWarning(caution)


class ConfigureQualityNotifications:
    """Explicit opt-in selected account monitoring; no task auto-starts."""
    label = "Configure Surveyor Quality Notifications (5-minute)"
    description = (
        "Choose specific ArcGIS surveyor accounts to monitor for new or edited "
        "LV Lines, Distribution Transformers and LV Poles. Creates local "
        "JSON configuration and a one-minute Windows Task Scheduler installation "
        "script. Notifications become active ONLY after you execute that script. "
        "Checks existing REG QA rules after five minutes and suppresses "
        "repeated unchanged issues. No Utility Network edits."
    )
    canRunInBackground=False

    @_log_tool_open_errors
    def getParameterInfo(self):
        from meter_photo_qa.smart_query import USER_NAMES_PATH
        usernames=json.loads(USER_NAMES_PATH.read_text(encoding="utf-8"))
        people=arcpy.Parameter(
            displayName="Select surveyors to watch (login — current name)",
            name="watched_surveyors",
            datatype="GPString",parameterType="Required",
            direction="Input",multiValue=True,
        )
        people.filter.type="ValueList"
        people.filter.list=[
            login+" — "+str(name)
            for login,name in sorted(usernames.items(),key=lambda v:v[0].casefold())
        ]
        folder=arcpy.Parameter(
            displayName="Notification storage folder",
            name="notification_folder",datatype="DEFolder",
            parameterType="Required",direction="Input",
        )
        folder.value=str(ROOT/"outputs")
        source=arcpy.Parameter(
            displayName="Assets monitored",
            name="asset_classes",datatype="GPString",
            parameterType="Required",direction="Input",
        )
        source.filter.type="ValueList"
        source.filter.list=[
            "All: LV Lines, Distribution Transformers, LV Poles",
            "LV Lines only","Distribution Transformers only","LV Poles only",
        ]
        source.value=source.filter.list[0]
        channel=arcpy.Parameter(
            displayName="Notification delivery",
            name="notification_delivery",datatype="GPString",
            parameterType="Required",direction="Input",
        )
        channel.filter.type="ValueList"
        channel.filter.list=[
            "Windows desktop notifications (when signed in)",
            "Email via configured SMTP environment variables",
        ]
        channel.value=channel.filter.list[0]
        recipient=arcpy.Parameter(
            displayName="Recipient email (only for SMTP mode)",
            name="recipient_email",datatype="GPString",
            parameterType="Optional",direction="Input",
        )
        replace=arcpy.Parameter(
            displayName="Replace an existing selected-surveyor configuration",
            name="replace_existing",datatype="GPBoolean",
            parameterType="Optional",direction="Input",
        )
        replace.value=False
        activate=arcpy.Parameter(
            displayName="Activate monitoring now (register Windows scheduled task)",
            name="activate_monitoring_now",datatype="GPBoolean",
            parameterType="Optional",direction="Input",
        )
        activate.value=False
        return [people,folder,source,channel,recipient,replace,activate]

    def execute(self,parameters,messages):
        raw=parameters[0].valueAsText or ""
        names=[name.strip().strip("'\"") for name in raw.split(";") if name.strip()]
        label=parameters[2].valueAsText or ""
        if label.startswith("LV Lines only"):
            assets=("line",)
        elif label.startswith("Distribution Transformers only"):
            assets=("transformer",)
        elif label.startswith("LV Poles only"):
            assets=("pole",)
        else:
            assets=("line","transformer","pole")
        channel="smtp" if (parameters[3].valueAsText or "").startswith("Email") else "desktop"
        result=configure_quality_notifications(
            usernames=names,
            output_folder=parameters[1].valueAsText,
            channel=channel,
            recipient_email=parameters[4].valueAsText or None,
            assets=assets,
            python_path=sys.executable,
            src_path=SRC,
            replace_existing=bool(parameters[5].value),
        )
        arcpy.AddMessage("Monitoring configuration created: "+result["configuration"])
        arcpy.AddMessage("Selected accounts: "+", ".join(result["watching_usernames"]))
        arcpy.AddMessage("Windows setup script: "+result["installation_script"])
        if bool(parameters[6].value):
            import subprocess
            if sys.platform != "win32":
                raise RuntimeError(
                    "Windows Task Scheduler activation requires Windows. "
                    "The configuration and installer script are preserved."
                )
            result_task=subprocess.run(
                ["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass",
                 "-File",result["installation_script"]],
                capture_output=True,text=True,timeout=90,check=False,
            )
            if result_task.returncode!=0:
                raise RuntimeError(
                    "Task registration failed; monitoring has NOT started. "
                    "Install manually with the generated PowerShell script. "
                    "PowerShell details: "+(result_task.stderr or result_task.stdout)
                )
            arcpy.AddMessage(
                "Windows confirmed registration of the one-minute task: "
                + result["task_name"]
            )
        else:
            arcpy.AddWarning(
                "NOT ACTIVATED YET. Execute the generated "
                "Install_One_Minute_Monitor.ps1 file while logged into Windows, "
                "or rerun this setup tool with Activate monitoring now checked."
            )
        arcpy.AddWarning(
            "Check desktop/email delivery with --send-test and verify the first "
            "monitor.log checks. A scheduled task alone does not prove REG "
            "authentication or notification delivery."
        )
        if channel=="desktop":
            arcpy.AddWarning(
                "Install winotify into arcgispro-py3 first: "
                "python -m pip install winotify. Windows user must be logged in."
            )
        else:
            arcpy.AddWarning(
                "SMTP host/user/password/sender environment variables must be "
                "configured outside GitHub and visible to the scheduled task."
            )
        arcpy.AddMessage("No notifications have been sent during setup.")


class ReviewGicumbiPamelaTeam:
    """Focused regional team profile, using verified portal account mapping."""
    label = "Review Gicumbi - Pamela Team (LV Lines, Transformers, Poles)"
    description = (
        "Read-only Gicumbi QA for Senior Supervisor Pamela / Supervisor Derrick. "
        "Applies the six planned sectors from September 2026 to LV lines, "
        "distribution transformers and LV poles consistently. The first "
        "team mode includes all 12 mapped surveyor accounts, including "
        "Kwizerwa Edison using the transferred Manzi Intime portal account. "
        "Older records on that account require separate authorship review. "
        "Outputs three QA workbooks, roster CSV and an audit manifest."
    )
    canRunInBackground = False

    @_log_tool_open_errors
    def getParameterInfo(self):
        output_folder = arcpy.Parameter(
            displayName="Output parent folder (one timestamped subfolder created)",
            name="output_folder", datatype="DEFolder",
            parameterType="Required", direction="Input",
        )
        output_folder.value = str(ROOT / "outputs")
        start = arcpy.Parameter(
            displayName="Review from (created or last edited)",
            name="start_date", datatype="GPDate",
            parameterType="Required", direction="Input",
        )
        start.value = datetime(2026, 9, 14)
        end = arcpy.Parameter(
            displayName="Review to (inclusive)",
            name="end_date", datatype="GPDate",
            parameterType="Required", direction="Input",
        )
        end.value = datetime.combine(datetime.now().date(), datetime.min.time())
        assets = arcpy.Parameter(
            displayName="Asset classes to review",
            name="assets", datatype="GPString",
            parameterType="Required", direction="Input",
        )
        assets.filter.type = "ValueList"
        assets.filter.list = [
            "All: LV Lines, Distribution Transformers and LV Poles",
            "LV Lines only", "Distribution Transformers only", "LV Poles only",
        ]
        assets.value = assets.filter.list[0]
        scope = arcpy.Parameter(
            displayName="Account scope",
            name="account_scope", datatype="GPString",
            parameterType="Required", direction="Input",
        )
        scope.filter.type = "ValueList"
        scope.filter.list = [
            "Mapped Pamela team accounts only (12 confirmed)",
            "All accounts in the six sectors (find missing usernames)",
        ]
        scope.value = scope.filter.list[0]
        service = arcpy.Parameter(
            displayName="Utility Network FeatureServer URL",
            name="service_url", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        service.value = DEFAULT_LINE_SERVICE_URL
        service.category = "Advanced"
        boundaries = arcpy.Parameter(
            displayName="Administrative Boundary FeatureServer URL",
            name="boundary_service_url", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        boundaries.value = DEFAULT_BOUNDARY_SERVICE_URL
        boundaries.category = "Advanced"
        version = arcpy.Parameter(
            displayName="Utility Network Version",
            name="gdb_version", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        version.value = "sde.DEFAULT"
        version.category = "Advanced"
        return [
            output_folder,start,end,assets,scope,
            service,boundaries,version,
        ]

    def updateMessages(self, parameters):
        if parameters[1].value and parameters[2].value and parameters[2].value < parameters[1].value:
            parameters[2].setErrorMessage("The end date cannot precede the start date.")

    def execute(self, parameters, messages):
        choices = {
            "All: LV Lines, Distribution Transformers and LV Poles": "all",
            "LV Lines only": "lv_line",
            "Distribution Transformers only": "transformer",
            "LV Poles only": "pole",
        }
        asset = choices[parameters[3].valueAsText]
        scope = (
            "all_in_assigned_sectors"
            if parameters[4].valueAsText ==
            "All accounts in the six sectors (find missing usernames)"
            else "team_only"
        )
        arcpy.AddMessage(
            "Gicumbi Pamela profile: Muko, Mutete, Nyamiyaga, "
            "Nyankenke, Rukomo, Rushaki. Supervisor Derrick. "
            "All source edits are disabled."
        )
        arcpy.AddWarning(
            "Gicumbi roster updated: Kwizerwa Edison uses ninamenye9683, "
            "Ringuyeneza Frederic uses maniraguhatheogene01 and "
            "Usabyeyezu Jean Dieu uses janviersafari515. "
            "Earlier account-holder labels may describe older records; "
            "handover dates are not confirmed."
        )
        summary = run_gicumbi_pamela_profile(
            output_folder=parameters[0].valueAsText,
            start_date=parameters[1].value,
            end_date=parameters[2].value,
            assets=asset,scope=scope,
            service_url=parameters[5].valueAsText or None,
            boundary_service_url=parameters[6].valueAsText or None,
            version=parameters[7].valueAsText or "sde.DEFAULT",
        )
        for report in summary["reports"]:
            arcpy.AddMessage(
                f"{report['asset']} QA completed: {report['checked']} records; "
                f"{report['outstanding_features']} feature(s) with gaps. "
                f"Excel: {report['file']}"
            )
        arcpy.AddMessage(
            "Pamela profile complete; manifest/roster: " +
            summary["manifest_json"] + " ; " + summary["roster_csv"]
        )


class ScanAllElectricLineDuplicates:
    """Full-network read-only duplicate GlobalID Excel register with location."""
    label = "Scan All Electric Line Duplicate GlobalIDs"
    description = (
        "Read-only country-wide scan for repeated Electric Line GlobalIDs. "
        "Exports one row per duplicate source feature with its OBJECTID, "
        "GlobalID, District, Sector and Cell derived by spatial intersection. "
        "No dates or surveyor restrictions. Do not delete Electric Lines "
        "from this tool."
    )
    canRunInBackground = False

    def getParameterInfo(self):
        output = arcpy.Parameter(
            displayName="Output Excel duplicate register",
            name="output_xlsx", datatype="DEFile",
            parameterType="Required", direction="Output",
        )
        output.filter.list = ["xlsx"]
        output.value = str(
            ROOT / "outputs" /
            f"all_electric_line_duplicate_globalids_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        )
        types = arcpy.Parameter(
            displayName="Electric Line assets to scan",
            name="asset_scope", datatype="GPString",
            parameterType="Required", direction="Input",
        )
        types.filter.type = "ValueList"
        types.filter.list = [
            "All Electric Lines (LV, MV and HV)",
            "LV Electric Lines only",
        ]
        types.value = types.filter.list[0]
        service = arcpy.Parameter(
            displayName="Utility Network FeatureServer URL",
            name="service_url", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        service.value = DEFAULT_LINE_SERVICE_URL
        boundary = arcpy.Parameter(
            displayName="Administrative Boundary FeatureServer URL",
            name="boundary_service_url", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        boundary.value = DEFAULT_BOUNDARY_SERVICE_URL
        version = arcpy.Parameter(
            displayName="Utility Network Version",
            name="gdb_version", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        version.value = "sde.DEFAULT"
        return [output, types, service, boundary, version]

    def execute(self, parameters, messages):
        selected = parameters[1].valueAsText
        summary = scan_electric_line_duplicate_globalids(
            output_xlsx=parameters[0].valueAsText,
            classes="lv" if selected == "LV Electric Lines only" else "all",
            service_url=parameters[2].valueAsText or None,
            boundary_service_url=parameters[3].valueAsText or None,
            version=parameters[4].valueAsText or "sde.DEFAULT",
        )
        arcpy.SetParameterAsText(0, summary["output_xlsx"])
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))
        if summary["duplicate_globalid_groups"]:
            arcpy.AddWarning(
                f"Found {summary['duplicate_globalid_groups']} duplicate GlobalID "
                f"groups in {summary['duplicate_feature_records']} Electric Line "
                "records. Review Excel before any authorized edits."
            )
        if summary["records_without_admin_location"]:
            arcpy.AddWarning(
                f"{summary['records_without_admin_location']} duplicate line records "
                "had no verified district/sector/cell. See Admin Status in Excel."
            )

class InspectElectricLineGlobalID:
    """Confirm actual source records before any Utility Network data cleanup."""
    label = "Inspect Electric Line Duplicate GlobalID"
    description = (
        "Read-only FeatureServer query by GlobalID, comparing distinct OBJECTIDs "
        "and exact polyline vertices. Does not change any GIS records."
    )
    canRunInBackground = False

    def getParameterInfo(self):
        output = arcpy.Parameter(
            displayName="Output Excel diagnostic",
            name="output_xlsx", datatype="DEFile",
            parameterType="Required", direction="Output",
        )
        output.filter.list = ["xlsx"]
        output.value = str(ROOT / "outputs" / f"duplicate_electric_line_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
        gid = arcpy.Parameter(
            displayName="Electric Line GlobalID (include braces or omit)",
            name="globalid", datatype="GPString", parameterType="Required",
            direction="Input",
        )
        service = arcpy.Parameter(
            displayName="Utility Network FeatureServer URL",
            name="service_url", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        service.value = DEFAULT_LINE_SERVICE_URL
        version = arcpy.Parameter(
            displayName="Utility Network Version",
            name="gdb_version", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        version.value = "sde.DEFAULT"
        return [output, gid, service, version]

    def updateMessages(self, parameters):
        if parameters[1].valueAsText:
            try:
                _duplicate_line_inspector.canonical_globalid(parameters[1].valueAsText)
            except ValueError as exc:
                parameters[1].setErrorMessage(str(exc))

    def execute(self, parameters, messages):
        result = inspect_duplicate_line_globalid(
            globalid=parameters[1].valueAsText,
            output_xlsx=parameters[0].valueAsText,
            service_url=parameters[2].valueAsText or None,
            version=parameters[3].valueAsText or "sde.DEFAULT",
        )
        arcpy.SetParameterAsText(0, result["output_xlsx"])
        arcpy.AddMessage(json.dumps(result, indent=2, default=str))
        if result["duplicate_globalid"]:
            arcpy.AddWarning(
                "The FeatureServer returned distinct OBJECTIDs for the SAME GlobalID. "
                "Do not delete records without reviewing geometry, attachments, "
                "associations and network topology."
            )
        elif result["matched_source_objects"] == 0:
            arcpy.AddWarning(
                "No source records found in this version. Verify layer source "
                "and project version if the attribute table shows results."
            )

class CheckLVTransformerNames(_AssetQualityTool):
    asset = "line_transformer_name"
    label = "Check LV Line Transformer Names"

    def getParameterInfo(self):
        parameters = super().getParameterInfo()
        scope = arcpy.Parameter(
            displayName="Lines to check",
            name="network_scope",
            datatype="GPString", parameterType="Required", direction="Input",
        )
        scope.filter.type = "ValueList"
        scope.filter.list = [
            "All lines connected to selected transformers",
            "Only lines surveyed/edited in selected date range",
        ]
        scope.value = scope.filter.list[0]
        return parameters + [scope]

    def __init__(self):
        self.description = (
            "Read-only REG Utility Network trace check: compare the "
            "Transformer_Name of each selected LV line with the name of "
            "its connected distribution-transformer point. Ambiguous "
            "or unverified sources are never presented as name errors. "
            "This operation can take time because transformer traces "
            "must be executed."
        )

    def execute(self, parameters, messages):
        summary = run_transformer_line_name_audit(
            output_xlsx=parameters[0].valueAsText,
            start_date=parameters[1].value,
            end_date=parameters[2].value,
            district=_split_multivalue(parameters[3].valueAsText),
            sectors=_split_multivalue(parameters[4].valueAsText),
            cells=_split_multivalue(parameters[5].valueAsText),
            custom_boundary_geometry=_drawn_boundary_geometry(parameters[6]),
            usernames=_split_multivalue(parameters[7].valueAsText),
            service_url=parameters[8].valueAsText or None,
            boundary_service_url=parameters[9].valueAsText or None,
            version=parameters[10].valueAsText or "sde.DEFAULT",
            scope=(
                "edited_period" if parameters[11].valueAsText ==
                "Only lines surveyed/edited in selected date range"
                else "all_connected"
            ),
        )
        arcpy.SetParameterAsText(0, summary["output_xlsx"])
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))
        if (
            summary["ambiguous_sources"] or summary["unverified_sources"]
            or summary["trace_warnings_unverified"]
        ):
            arcpy.AddWarning(
                "Some lines have ambiguous or unverified source transformers. "
                "See All Checked LV Lines; do not automatically rename them."
            )
        if not summary["lines_checked"]:
            arcpy.AddWarning("No LV lines met the dates and selected area.")


class BuildSubstationContainment:
    def __init__(self):
        self.label = "Preview / Apply Substation Containment"
        self.description = (
            "Reproduce the proven Kibuye hierarchy: main substation boundary to "
            "electric bays, then bays to rule-allowed devices. Preview is the default; "
            "the result is one readable Excel workbook for any selected substations."
        )
        self.canRunInBackground = False

    @_log_tool_open_errors
    def getParameterInfo(self):
        today = datetime.now().date()
        province_index = _province_index()
        boundary_index = _boundary_index()
        cell_index = _cell_index()
        districts = list(boundary_index)
        default_province = next(
            (name for name in province_index if name.casefold() == "city of kigali"),
            next(iter(province_index), None),
        )
        default_district = _matching_district(boundary_index, "Gasabo")
        default_sectors = (
            boundary_index.get(default_district, []) if default_district else []
        )
        default_cells = _available_cells(cell_index, default_district, [])

        output = arcpy.Parameter(
            displayName="Substation containment report (Excel)",
            name="output_xlsx",
            datatype="DEFile",
            parameterType="Required",
            direction="Output",
        )
        output.filter.list = ["xlsx"]
        output.value = str(
            ROOT / "outputs" / f"substation_containment_report_{today:%Y%m%d}.xlsx"
        )

        area_mode = arcpy.Parameter(
            displayName="Area mode",
            name="area_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        area_mode.filter.type = "ValueList"
        area_mode.filter.list = AREA_MODES
        area_mode.value = KIGALI_MODE

        province = arcpy.Parameter(
            displayName="Province",
            name="province",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        province.filter.type = "ValueList"
        province.filter.list = list(province_index)
        province.value = default_province

        district = arcpy.Parameter(
            displayName="District",
            name="district",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        district.filter.type = "ValueList"
        district.filter.list = districts
        district.value = default_district

        sectors = arcpy.Parameter(
            displayName="Sector(s)",
            name="sectors",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        sectors.filter.type = "ValueList"
        sectors.filter.list = default_sectors

        cells = arcpy.Parameter(
            displayName="Cell(s)",
            name="cells",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        cells.filter.type = "ValueList"
        cells.filter.list = default_cells

        custom_boundary = arcpy.Parameter(
            displayName="Custom boundary (draw polygon)",
            name="custom_boundary",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Optional",
            direction="Input",
        )
        custom_boundary.value = str(CUSTOM_BOUNDARY_TEMPLATE)

        operation = arcpy.Parameter(
            displayName="Operation",
            name="operation",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        operation.filter.type = "ValueList"
        operation.filter.list = OPERATION_MODES
        operation.value = PREVIEW_MODE

        service = arcpy.Parameter(
            displayName="Substation utility network feature service URL",
            name="service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        service.value = DEFAULT_SUBSTATION_SERVICE_URL
        service.category = "Advanced"

        boundaries = arcpy.Parameter(
            displayName="Sector and cell boundary service URL",
            name="boundary_service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        boundaries.value = DEFAULT_BOUNDARY_SERVICE_URL
        boundaries.category = "Advanced"

        version = arcpy.Parameter(
            displayName="Utility network version",
            name="gdb_version",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        version.value = "sde.DEFAULT"
        version.category = "Advanced"

        return [
            output,
            area_mode,
            province,
            district,
            sectors,
            cells,
            custom_boundary,
            operation,
            service,
            boundaries,
            version,
        ]

    def updateParameters(self, parameters):
        _apply_boundary_filters(parameters, 3, 4, 5, province_index=2)
        mode = parameters[1].valueAsText or KIGALI_MODE
        province_mode = mode == PROVINCE_MODE
        administrative = mode == ADMIN_MODE
        custom = mode == CUSTOM_MODE
        parameters[2].enabled = province_mode or administrative
        parameters[3].enabled = administrative
        parameters[4].enabled = administrative
        parameters[5].enabled = administrative
        parameters[6].enabled = custom

    def updateMessages(self, parameters):
        mode = parameters[1].valueAsText or KIGALI_MODE
        if mode in {PROVINCE_MODE, ADMIN_MODE} and not parameters[2].valueAsText:
            parameters[2].setErrorMessage("Choose a province.")
        if mode == ADMIN_MODE and not parameters[3].valueAsText:
            parameters[3].setErrorMessage("Choose a district.")
        if mode == CUSTOM_MODE:
            try:
                has_geometry = _drawn_boundary_geometry(parameters[6]) is not None
            except Exception as exc:
                parameters[6].setErrorMessage(str(exc))
                has_geometry = False
            if not has_geometry:
                parameters[6].setErrorMessage("Draw at least one polygon.")

    def execute(self, parameters, messages):
        summary = run_substation_containment(
            output_xlsx=parameters[0].valueAsText,
            area_mode=parameters[1].valueAsText or KIGALI_MODE,
            province=parameters[2].valueAsText or None,
            district=parameters[3].valueAsText or None,
            sectors=_split_multivalue(parameters[4].valueAsText),
            cells=_split_multivalue(parameters[5].valueAsText),
            custom_boundary_geometry=_drawn_boundary_geometry(parameters[6]),
            operation=parameters[7].valueAsText or PREVIEW_MODE,
            service_url=parameters[8].valueAsText or None,
            boundary_service_url=parameters[9].valueAsText or None,
            version=parameters[10].valueAsText or "sde.DEFAULT",
        )
        arcpy.SetParameterAsText(0, summary["output_xlsx"])
        counts = summary.get("status_counts", {})
        arcpy.AddMessage(
            f"Containment audit created for {len(summary['substations'])} substation(s): "
            f"{counts.get('PROPOSE', 0)} proposed, "
            f"{counts.get('EXISTING', 0)} existing, "
            f"{counts.get('REVIEW', 0)} review, and "
            f"{counts.get('CONFLICT', 0)} conflict row(s)."
        )
        if summary["operation"] == APPLY_MODE:
            result = summary.get("apply_result", {})
            arcpy.AddMessage(
                f"Applied {result.get('succeeded', 0)} association(s); "
                f"{result.get('failed', 0)} failed."
            )
        if counts.get("REVIEW", 0) or counts.get("CONFLICT", 0):
            arcpy.AddWarning(
                "Review rows were not applied. Open the Containment sheet for reasons."
            )
        arcpy.AddMessage(
            f"{summary.get('missing_rule_equipment', 0)} equipment record(s) with "
            "no configured rule were excluded from the operation and listed on the "
            "Missing Rules sheet."
        )
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))


class BuildRelayAssociations:
    def __init__(self):
        self.label = "Preview / Apply Electric Relay Associations"
        self.description = (
            "Localize Electric Relay objects by line bay, transformer bay, or whole "
            "substation; then preview or apply only live-rule-valid terminal connections. "
            "Transformer differential relays use all configured winding terminals."
        )
        self.canRunInBackground = False

    @_log_tool_open_errors
    def getParameterInfo(self):
        today = datetime.now().date()
        province_index = _province_index()
        boundary_index = _boundary_index()
        cell_index = _cell_index()
        districts = list(boundary_index)
        default_province = next(
            (name for name in province_index if name.casefold() == "city of kigali"),
            next(iter(province_index), None),
        )
        default_district = _matching_district(boundary_index, "Gasabo")
        default_sectors = (
            boundary_index.get(default_district, []) if default_district else []
        )
        default_cells = _available_cells(cell_index, default_district, [])

        output = arcpy.Parameter(
            displayName="Electric relay association report (Excel)",
            name="output_xlsx",
            datatype="DEFile",
            parameterType="Required",
            direction="Output",
        )
        output.filter.list = ["xlsx"]
        output.value = str(
            ROOT / "outputs" / f"electric_relay_association_report_{today:%Y%m%d}.xlsx"
        )

        area_mode = arcpy.Parameter(
            displayName="Area mode",
            name="area_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        area_mode.filter.type = "ValueList"
        area_mode.filter.list = AREA_MODES
        area_mode.value = KIGALI_MODE

        province = arcpy.Parameter(
            displayName="Province",
            name="province",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        province.filter.type = "ValueList"
        province.filter.list = list(province_index)
        province.value = default_province

        district = arcpy.Parameter(
            displayName="District",
            name="district",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        district.filter.type = "ValueList"
        district.filter.list = districts
        district.value = default_district

        sectors = arcpy.Parameter(
            displayName="Sector(s)",
            name="sectors",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        sectors.filter.type = "ValueList"
        sectors.filter.list = default_sectors

        cells = arcpy.Parameter(
            displayName="Cell(s)",
            name="cells",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        cells.filter.type = "ValueList"
        cells.filter.list = default_cells

        custom_boundary = arcpy.Parameter(
            displayName="Custom boundary (draw polygon)",
            name="custom_boundary",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Optional",
            direction="Input",
        )
        custom_boundary.value = str(CUSTOM_BOUNDARY_TEMPLATE)

        operation = arcpy.Parameter(
            displayName="Operation",
            name="operation",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        operation.filter.type = "ValueList"
        operation.filter.list = OPERATION_MODES
        operation.value = PREVIEW_MODE

        service = arcpy.Parameter(
            displayName="Substation utility network feature service URL",
            name="service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        service.value = DEFAULT_SUBSTATION_SERVICE_URL
        service.category = "Advanced"

        boundaries = arcpy.Parameter(
            displayName="Sector and cell boundary service URL",
            name="boundary_service_url",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        boundaries.value = DEFAULT_BOUNDARY_SERVICE_URL
        boundaries.category = "Advanced"

        version = arcpy.Parameter(
            displayName="Utility network version",
            name="gdb_version",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        version.value = "sde.DEFAULT"
        version.category = "Advanced"

        return [
            output,
            area_mode,
            province,
            district,
            sectors,
            cells,
            custom_boundary,
            operation,
            service,
            boundaries,
            version,
        ]

    def updateParameters(self, parameters):
        _apply_boundary_filters(parameters, 3, 4, 5, province_index=2)
        mode = parameters[1].valueAsText or KIGALI_MODE
        province_mode = mode == PROVINCE_MODE
        administrative = mode == ADMIN_MODE
        custom = mode == CUSTOM_MODE
        parameters[2].enabled = province_mode or administrative
        parameters[3].enabled = administrative
        parameters[4].enabled = administrative
        parameters[5].enabled = administrative
        parameters[6].enabled = custom

    def updateMessages(self, parameters):
        mode = parameters[1].valueAsText or KIGALI_MODE
        if mode in {PROVINCE_MODE, ADMIN_MODE} and not parameters[2].valueAsText:
            parameters[2].setErrorMessage("Choose a province.")
        if mode == ADMIN_MODE and not parameters[3].valueAsText:
            parameters[3].setErrorMessage("Choose a district.")
        if mode == CUSTOM_MODE:
            try:
                has_geometry = _drawn_boundary_geometry(parameters[6]) is not None
            except Exception as exc:
                parameters[6].setErrorMessage(str(exc))
                has_geometry = False
            if not has_geometry:
                parameters[6].setErrorMessage("Draw at least one polygon.")

    def execute(self, parameters, messages):
        summary = run_relay_associations(
            output_xlsx=parameters[0].valueAsText,
            area_mode=parameters[1].valueAsText or KIGALI_MODE,
            province=parameters[2].valueAsText or None,
            district=parameters[3].valueAsText or None,
            sectors=_split_multivalue(parameters[4].valueAsText),
            cells=_split_multivalue(parameters[5].valueAsText),
            custom_boundary_geometry=_drawn_boundary_geometry(parameters[6]),
            operation=parameters[7].valueAsText or PREVIEW_MODE,
            service_url=parameters[8].valueAsText or None,
            boundary_service_url=parameters[9].valueAsText or None,
            version=parameters[10].valueAsText or "sde.DEFAULT",
        )
        arcpy.SetParameterAsText(0, summary["output_xlsx"])
        counts = summary.get("status_counts", {})
        arcpy.AddMessage(
            f"Relay audit created for {summary.get('selected_relays', 0)} relay(s): "
            f"{counts.get('PROPOSE', 0)} proposed, "
            f"{counts.get('EXISTING', 0)} existing, "
            f"{counts.get('APPLIED', 0)} applied, and "
            f"{summary.get('exception_rows', 0)} exception row(s)."
        )
        if summary["operation"] == APPLY_MODE:
            result = summary.get("apply_result", {})
            arcpy.AddMessage(
                f"Applied {result.get('succeeded', 0)} association(s); "
                f"{result.get('failed', 0)} failed."
            )
        if summary.get("exception_rows", 0):
            arcpy.AddWarning(
                "Exceptions were not applied. Open the Exceptions sheet for reasons."
            )
        arcpy.AddMessage(json.dumps(summary, indent=2, default=str))

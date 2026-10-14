"""Read-only template-aware audit grouped by ArcGIS created_user.

Spatially filters records against official boundary polygons and validates
criteria against the live schema. Produces a full audit Excel register,
surveyor summary and machine-readable results for future opt-in alerts.
No notifications are sent, no source features are edited.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime
import json
from pathlib import Path
import re

from .asset_quality import domain_map
from .progress_report import (
    DEFAULT_BOUNDARY_SERVICE_URL,DEFAULT_LINE_SERVICE_URL,
    SECTOR_LAYER_ID,CELL_LAYER_ID,_get_gis,_layer_url,
)
from .smart_query import QueryPlan,boundary_where,ASSET_LAYERS
from .template_attribute_audit import (
    parse_surveyor_template_request,compile_template_filter,
)
from .smart_query import USER_NAMES_PATH,ROSTER_PATH

MAX_AUDIT_FEATURES = 25000


def _safe(value):
    if isinstance(value,str) and value.startswith(("=","+","-","@")):
        return "'"+value
    return value


def _current_user_labels():
    names=json.loads(USER_NAMES_PATH.read_text(encoding="utf-8"))
    profile=json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    transfers={entry["username"].casefold()
               for entry in profile.get("account_mapping_history",{}).get("changed_logins",[])
               if entry.get("username")}
    return names,transfers


def _excel(destination,plan,criteria,records,sql,boundary_sql,layer_url,source_mode):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font,PatternFill
    from openpyxl.utils import get_column_letter

    names,transfers=_current_user_labels()
    grouped=defaultdict(list)
    for row in records:
        user=str(row.get("created_user") or "").strip() or "(unattributed)"
        grouped[user].append(row)
    totals=Counter(str(row.get("globalid") or "").casefold().strip("{}")
                   for row in records if row.get("globalid"))
    duplicates={gid:count for gid,count in totals.items() if count>1}
    work=Workbook()
    overview=work.active;overview.title="Audit Summary"
    survey=work.create_sheet("Surveyors")
    details=work.create_sheet("Matching Records")
    req=work.create_sheet("Resolved Template Criteria")
    review=work.create_sheet("Data Quality Warnings")
    readiness=work.create_sheet("Notification Readiness")
    for key,val in [
        ("Metric","Value"),
        ("Asset",plan.asset),
        ("District",plan.district),
        ("Sector",plan.sector or "ALL"),
        ("Cell",plan.cell or "ALL"),
        ("Matching distinct OBJECTIDs",len(records)),
        ("Matching surveyor logins",len(grouped)),
        ("Criteria logic",plan.condition_mode.upper()),
        ("Template SQL",sql),
        ("Official boundary SQL",boundary_sql),
        ("Source FeatureServer",layer_url),
        ("Data retrieval mode",source_mode),
        ("Repeated GlobalIDs",len(duplicates)),
        ("Account attribution","created_user is a login, NOT proof of current holder for past records"),
        ("Numerical units","Numeric limits use STORED field units, not assumed metres"),
        ("Notifications sent","NO — alerts require a separate opt-in workflow"),
        ("Source modifications","NONE (read-only)"),
    ]: overview.append([key,val])
    survey.append([
        "ArcGIS Username","Current Display Name","Affected Feature Count",
        "Distinct GlobalIDs","Earliest/Latest Scope","Historical Account Warning",
    ])
    for user,items in sorted(grouped.items(),
                             key=lambda pair:(-len(pair[1]),pair[0].casefold())):
        unique={str(item["globalid"]).casefold().strip("{}")
                for item in items if item["globalid"]}
        survey.append([
            user,names.get(user,"(not verified)" if user!="(unattributed)" else "(unattributed)"),
            len(items),len(unique),
            f"{plan.district}"+(f" / {plan.sector}" if plan.sector else ""),
            "ACCOUNT HOLDER TRANSFER DATE UNKNOWN" if user.casefold() in transfers else "",
        ])
    condition_fields=list(dict.fromkeys(criterion["live_field"] for criterion in criteria))
    details.append([
        "OBJECTID","GlobalID","Surveyor Username","Current Display Name",
        "Requested District","Requested Sector","Requested Cell",
        "Repeated GlobalID","Historical Attribution Warning",
        *condition_fields,
    ])
    for row in records:
        user=row["created_user"] or "(unattributed)"
        details.append([
            row["objectid"],_safe(row["globalid"]),_safe(user),
            _safe(names.get(user,"(not verified)")),
            plan.district,plan.sector or "",plan.cell or "",
            "YES" if totals.get(str(row.get("globalid") or "").casefold().strip("{}"),0)>1 else "NO",
            "REVIEW" if user.casefold() in transfers else "",
            *(_safe(row["field_values"].get(field)) for field in condition_fields),
        ])
    req.append([
        "Requested Field","Resolved Live Field","Field Alias","Source Data Type",
        "Operator","Threshold (stored units)","Unknown Domain Codes",
    ])
    for entry in criteria:
        req.append([
            entry["requested"],entry["live_field"],entry["alias"],entry["type"],
            entry["operator"],entry["value"] if entry["value"] is not None else "",
            ", ".join(entry["domain_unknown_codes"]),
        ])
    for items in [
        ("Issue","Meaning"),
        ("Unverified historical people","Account labels may have changed since a record was created. Grouping is by created_user only."),
        ("Duplicate GlobalIDs","One GlobalID can occur under distinct OBJECTIDs. Counted as distinct source features, not distinct physical assets."),
        ("Missing values","NULL, empty string and explicit 'Unknown' coded-domain values; numeric zero is valid unless live domain labels it Unknown."),
        ("Numeric units","If the field is stored in feet, 12 compares to 12 feet, NOT 12 metres. Check the schema before engineering conclusions."),
        ("Spatial intersection","Administrative filter selects features intersecting the chosen polygon; border features can occur in multiple areas."),
        ("Current feature snapshot","This query checks current feature attributes, not proof of what each person filled at initial creation."),
        ("Unrecorded creator","Blank created_user is placed in unattributed category, not assigned to a person."),
        ("Completeness threshold","Template conditions are exact specified filters, not an automatic assertion that the complete asset is correct."),
    ]: review.append(items)
    readiness.append([
        "Feature Identifier","Missing/Threshold Criterion","Affected Username",
        "Alert Candidate","Alert Status","Required Before Notifications",
    ])
    for row in records:
        username=row["created_user"] or "(unattributed)"
        readiness.append([
            _safe(row["globalid"] or str(row["objectid"])),
            "; ".join(c["requested"]+" "+c["operator"] for c in criteria),
            _safe(username),
            "YES" if username!="(unattributed)" else "UNATTRIBUTED",
            "NOT_SENT",
            "Opt-in recipients, baseline snapshot, state tracking, alert schedule and duplicate suppression",
        ])
    for sheet in work:
        sheet.freeze_panes="A2"
        sheet.sheet_view.showGridLines=False
        sheet.auto_filter.ref=sheet.dimensions if sheet!=overview else None
        for cell in sheet[1]:
            cell.font=Font(bold=True,color="FFFFFF")
            cell.fill=PatternFill("solid",fgColor="17365D")
        for col in sheet.columns:
            letter=get_column_letter(col[0].column)
            width=min(70,max(15,max((len(str(c.value or "")) for c in list(col)[:400]),default=0)+2))
            sheet.column_dimensions[letter].width=width
    if destination.exists():
        raise FileExistsError(f"Output already exists: {destination}")
    work.save(destination)
    work.close()
    return {
        "matching_surveyors":len(grouped),
        "duplicate_globalid_groups":len(duplicates),
    }


def run_template_surveyor_audit(
    request, output_folder, output_json=None, service_url=None,
    boundary_service_url=None, gis=None, arcpy_module=None,
    max_rows=MAX_AUDIT_FEATURES,
):
    """Use ArcGIS selected-feature read only; create XLSX and structured JSON."""
    plan=parse_surveyor_template_request(request)
    output=Path(output_folder).expanduser().resolve()
    if not output.is_dir():
        raise ValueError(f"Select an existing report destination folder: {output}")
    if arcpy_module is None:
        import arcpy as arcpy_module
    arcpy=arcpy_module
    from arcgis.features import FeatureLayer
    active=_get_gis(gis)
    service=str(service_url or DEFAULT_LINE_SERVICE_URL).rstrip("/")
    boundary=str(boundary_service_url or DEFAULT_BOUNDARY_SERVICE_URL).rstrip("/")
    asset_url=_layer_url(service,ASSET_LAYERS[plan.asset])
    layer=FeatureLayer(asset_url,active)
    fields=[dict(f) for f in layer.properties.fields]
    domain=domain_map(layer.properties,{"pole":7,"line":9,"transformer":12}[plan.asset])
    sql,columns,criteria=compile_template_filter(plan,fields,domain)
    # Reject empty or unconstrained query before service access.
    if not criteria:
        raise ValueError("At least one valid template condition is required.")
    field_lookup={f["name"].casefold():f["name"] for f in fields}
    identity_fields=[]
    for field in ["OBJECTID","GLOBALID","created_user"]:
        if field.casefold() not in field_lookup:
            raise ValueError(f"The source layer lacks essential identifier {field}.")
        identity_fields.append(field_lookup[field.casefold()])
    cursor_fields=list(dict.fromkeys([*identity_fields,*columns]))
    scope=QueryPlan("filter",plan.asset,plan.district,
                    plan.sector,plan.cell,(),())
    geographic=boundary_where(scope)
    if not geographic:
        raise ValueError("Administrative scope was not resolved.")
    timestamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temporary=None
    polygon=None
    try:
        temporary=arcpy.management.MakeFeatureLayer(
            asset_url,f"REPORTAPP_audit_{timestamp}",sql
        ).getOutput(0)
        admin_layer=CELL_LAYER_ID if plan.cell else SECTOR_LAYER_ID
        polygon_url=_layer_url(boundary,admin_layer)
        polygon=arcpy.management.MakeFeatureLayer(
            polygon_url,f"REPORTAPP_boundary_{timestamp}",geographic
        ).getOutput(0)
        if int(arcpy.management.GetCount(polygon).getOutput(0))<1:
            raise RuntimeError("Administrative boundary returned zero matching polygons.")
        arcpy.management.SelectLayerByLocation(
            temporary,"INTERSECT",polygon,selection_type="NEW_SELECTION"
        )
        count=int(arcpy.management.GetCount(temporary).getOutput(0))
        if count<0 or count>max_rows:
            raise ValueError(
                f"The query found {count:,} features. Narrow the geographic area "
                f"or field conditions; the audit maximum is {max_rows:,}. "
                "No partial report was generated."
            )
        records=[]
        seen=set()
        with arcpy.da.SearchCursor(temporary,cursor_fields) as cursor:
            for vals in cursor:
                attrs=dict(zip(cursor_fields,vals))
                oid=int(attrs[identity_fields[0]])
                if oid in seen:
                    raise RuntimeError(
                        f"Repeated OBJECTID {oid} in spatially filtered source; "
                        "cannot produce trustworthy surveyor counts."
                    )
                seen.add(oid)
                records.append({
                    "objectid":oid,
                    "globalid":str(attrs.get(identity_fields[1]) or ""),
                    "created_user":str(attrs.get(identity_fields[2]) or ""),
                    "field_values":{key:attrs.get(key) for key in columns},
                })
                if len(records)>max_rows:
                    raise RuntimeError("More records returned than safe reporting maximum.")
        if len(records)!=count:
            raise RuntimeError(
                f"Feature count changed during query: server indicated {count:,}, "
                f"retrieved {len(records):,}. No incomplete report saved."
            )
    finally:
        for layer_to_remove in (polygon,temporary):
            if layer_to_remove is not None:
                try: arcpy.management.Delete(layer_to_remove)
                except Exception: pass
    stamp=f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    location=re.sub(r"[^A-Za-z0-9_-]+","_",plan.district)
    destination=output/f"Surveyor_Template_Audit_{plan.asset}_{location}_{stamp}.xlsx"
    metrics=_excel(destination,plan,criteria,records,sql,geographic,asset_url,"ArcPy selected FeatureServer view")
    result={
        "status":"COMPLETE","input_request":request,
        "output_xlsx":str(destination),
        "read_only":True,"notifications_sent":0,
        "interpreted":plan.serialize(),
        "matching_features":len(records),
        "matching_surveyors":metrics["matching_surveyors"],
        "duplicate_globalid_groups":metrics["duplicate_globalid_groups"],
        "resolved_criteria":criteria,
        "attribute_sql":sql,
        "boundary_sql":geographic,
        "source_feature_service":asset_url,
        "account_attribution_caution":"created_user may reflect an earlier account holder; historical transfers not verified.",
        "alerts":"NOT_CONFIGURED (future opt-in workflow)",
    }
    if output_json:
        audit=Path(output_json).expanduser().resolve()
        if audit.suffix.lower()!=".json":
            raise ValueError("Query audit output path must end with .json.")
        if audit.exists():
            raise FileExistsError(f"Audit JSON path already exists: {audit}.")
        audit.parent.mkdir(parents=True,exist_ok=True)
        audit.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
        result["output_json"]=str(audit)
    return result

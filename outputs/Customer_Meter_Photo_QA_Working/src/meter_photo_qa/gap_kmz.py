"""Read-only QA gap companion KMZ with actual REG geometry.

The Excel workbook is the sole source of which features are flagged.
Geometry is requested for precisely those OBJECTIDs on the same REG version,
and GlobalID+Asset Group are verified. No GIS updates are performed.
"""
from __future__ import annotations

from collections import defaultdict
from html import escape
import json
import math
import os
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

SOURCE = {
    "line": {"layer":10,"groups":{9,10},"title":"LV Lines"},
    "transformer":{"layer":7,"groups":{12},"title":"Distribution Transformers"},
    "pole":{"layer":12,"groups":{7},"title":"LV Poles"},
}
COLORS={"line":"ff0000ff", "transformer":"ffff8800","pole":"ff00a5ff"}
KML_NS="http://www.opengis.net/kml/2.2"
ET.register_namespace("",KML_NS)

def _n(name): return "{"+KML_NS+"}"+name
def _add(node,name,value=None,**attrs):
    item=ET.SubElement(node,_n(name),attrs)
    if value is not None:item.text=str(value)
    return item
def _value(row,field):
    return str(row.get(field) if row.get(field) is not None else "").strip()
def _gid(v):
    return str(v or "").strip().strip("{}").casefold()
def _s(v):
    # KML is XML, and spreadsheet strings are never HTML/JS.
    return str(v or "").replace("\x00","")

def _read_sheet(path, name):
    from openpyxl import load_workbook
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        if name not in wb.sheetnames:
            raise ValueError(f"{path.name}: missing quality sheet '{name}'")
        sheet=wb[name]
        data=sheet.iter_rows(values_only=True)
        header=next(data,None)
        if not header:
            return []
        names=[str(v or "").strip() for v in header]
        return [dict(zip(names,raw)) for raw in data if any(v is not None for v in raw)]
    finally: wb.close()

def read_gap_index(report_xlsx, asset):
    """Use same workbook rows used for human corrections, not a fresh QA score."""
    asset=str(asset)
    if asset not in SOURCE:
        raise ValueError("Unsupported KMZ asset: "+asset)
    report=Path(report_xlsx)
    if asset!="line":
        result={}
        for row in _read_sheet(report,"Asset Details"):
            if _value(row,"Status").upper()!="GAP":
                continue
            oid=int(row["OBJECTID"])
            issues=_value(row,"Outstanding Issues")
            if not issues:
                raise ValueError("GAP row missing explanations (OBJECTID "+str(oid)+")")
            result[oid]={
                "asset":asset,"objectid":oid,"globalid":_value(row,"GlobalID"),
                "surveyor":_value(row,"Surveyor Username"),"issues":issues,
                "recorded_district":_value(row,"Recorded District"),
                "recorded_sector":_value(row,"Recorded Sector"),
                "recorded_cell":_value(row,"Recorded Cell"),
            }
        return result
    all_lines={}
    for row in _read_sheet(report,"Line Details"):
        if row.get("Source OBJECTID") is None:continue
        oid=int(row["Source OBJECTID"])
        issues=[]
        if _value(row,"Status")=="FLAG":
            issues.append("Below QA threshold")
        missing=_value(row,"Missing Attributes")
        invalid=_value(row,"Invalid Attributes")
        if missing:issues.append("Missing scored fields: "+missing)
        if invalid:issues.append("Invalid scored fields: "+invalid)
        all_lines[oid]={
            "asset":"line","objectid":oid,"globalid":_value(row,"GlobalID"),
            "surveyor":_value(row,"Username"),"issues_list":issues,
            "recorded_district":"","recorded_sector":"","recorded_cell":"",
        }
    for row in _read_sheet(report,"Outstanding LV Gaps"):
        if row.get("Source OBJECTID") is None:continue
        oid=int(row["Source OBJECTID"])
        if oid not in all_lines:
            raise ValueError("Priority line not in Line Details: "+str(oid))
        value=_value(row,"Issue Details") or _value(row,"Outstanding Issues")
        if value:all_lines[oid]["issues_list"].append("Priority corrections: "+value)
    for row in _read_sheet(report,"Duplicate Line Records"):
        if row.get("Source OBJECTID") is None:continue
        oid=int(row["Source OBJECTID"])
        if oid not in all_lines:
            raise ValueError("Duplicate line not in Line Details: "+str(oid))
        all_lines[oid]["issues_list"].append(
            "Duplicate GlobalID — other OBJECTIDs: "+_value(row,"Other OBJECTIDs")
        )
    result={}
    for oid,item in all_lines.items():
        issues=list(dict.fromkeys(item.pop("issues_list")))
        if issues:
            item["issues"]="; ".join(issues)
            result[oid]=item
    return result

def collect_gaps(reports):
    results={}
    for kind,report in reports.items():
        if kind not in SOURCE:
            raise ValueError("Unknown report asset "+str(kind))
        for oid,rec in read_gap_index(report,kind).items():
            key=(kind,int(oid))
            if key in results:
                raise ValueError("Duplicate source OBJECTID in KMZ index")
            results[key]=rec
    return results

def _xy(coord):
    if not isinstance(coord,(tuple,list)) or len(coord)<2:
        raise ValueError("Incomplete WGS84 coordinate")
    x,y=float(coord[0]),float(coord[1])
    if not math.isfinite(x) or not math.isfinite(y) or not -180<=x<=180 or not -90<=y<=90:
        raise ValueError("Geometry coordinates must be finite WGS84 longitude/latitude.")
    return f"{x:.8f},{y:.8f},0"

def _lines(geometry):
    paths=geometry.get("paths") or []
    if not paths:
        raise ValueError("Missing line geometry")
    out=[]
    for path in paths:
        if len(path)<2:raise ValueError("Invalid short line geometry")
        out.append(" ".join(_xy(point) for point in path))
    return out

def _write_geometry(mark,asset,geometry):
    if asset=="line":
        paths=_lines(geometry)
        container=_add(mark,"MultiGeometry") if len(paths)>1 else mark
        for coords in paths:
            line=_add(container,"LineString")
            _add(line,"tessellate","1")
            _add(line,"coordinates",coords)
    else:
        if "x" not in geometry or "y" not in geometry:
            raise ValueError("Missing point geometry")
        point=_add(mark,"Point")
        _add(point,"coordinates",_xy([geometry["x"],geometry["y"]]))

def _render_kml(index,geometry_by_key):
    # Build KML root separately so ElementTree emits correct KML element nesting.
    kml=ET.Element(_n("kml"))
    document=_add(kml,"Document")
    _add(document,"name","REG Outstanding QA Gaps — source geometry")
    _add(document,"description","Read-only REG features with outstanding QA gaps, WGS84. See companion Excel.")
    for kind in SOURCE:
        style=_add(document,"Style",None,id="style_"+kind)
        for tag,value in (("LineStyle",COLORS[kind]),("IconStyle",COLORS[kind])):
            child=_add(style,tag)
            _add(child,"color",value)
            if tag=="LineStyle":_add(child,"width","4")
            else:_add(child,"scale","1.1")
    for kind in SOURCE:
        selected=sorted((x for x in index if x[0]==kind and x in geometry_by_key),key=lambda x:x[1])
        if not selected:continue
        folder=_add(document,"Folder")
        _add(folder,"name",SOURCE[kind]["title"]+" — Outstanding Gaps")
        for key in selected:
            entry=index[key]
            place=_add(folder,"Placemark")
            _add(place,"name",f"{SOURCE[kind]['title']} OBJECTID {entry['objectid']}")
            _add(place,"styleUrl","#style_"+kind)
            _add(place,"description",
                "Outstanding issues: "+entry["issues"]+"\n"+
                "Surveyor: "+entry["surveyor"]+"\n"+
                "Source OBJECTID: "+str(entry["objectid"])+"\n"+
                "GlobalID: "+entry["globalid"])
            data=_add(place,"ExtendedData")
            for attr,value in (
                ("OBJECTID",entry["objectid"]),("GlobalID",entry["globalid"]),
                ("Surveyor",entry["surveyor"]),("Outstanding Issues",entry["issues"]),
                ("Recorded District",entry["recorded_district"]),
                ("Recorded Sector",entry["recorded_sector"]),
                ("Recorded Cell",entry["recorded_cell"]),
            ):
                d=_add(data,"Data",None,name=attr)
                _add(d,"value",str(value))
            _write_geometry(place,kind,geometry_by_key[key])
    return ET.tostring(kml,encoding="utf-8",xml_declaration=True)

def _lookup(index, service_url, version, gis=None, layer_factory=None):
    from .progress_report import DEFAULT_LINE_SERVICE_URL, _get_gis, _layer_url
    if layer_factory is None:
        from arcgis.features import FeatureLayer
        active=_get_gis(gis)
        def layer_factory(identifier):
            return FeatureLayer(_layer_url(
                service_url or os.environ.get("UN_REPORT_SERVICE_URL") or DEFAULT_LINE_SERVICE_URL,
                identifier
            ),active)
    result={}
    failures={}
    for kind in SOURCE:
        requested={oid:entry for (asset,oid),entry in index.items() if asset==kind}
        if not requested:continue
        service=layer_factory(SOURCE[kind]["layer"])
        for i in range(0,len(requested),100):
            subset=list(sorted(requested))[i:i+100]
            features=service.query(
                object_ids=",".join(str(oid) for oid in subset),
                out_fields="OBJECTID,GLOBALID,ASSETGROUP",
                out_sr=4326,
                return_geometry=True,
                gdb_version=version,
                return_all_records=True,
            )
            for feature in features.features:
                attrs=dict(feature.attributes or {})
                oid=int(attrs["OBJECTID"])
                if oid not in requested:continue
                expected=requested[oid]
                group=attrs.get("ASSETGROUP")
                if group is None or int(group) not in SOURCE[kind]["groups"]:
                    failures[(kind,oid)]="WRONG_ASSET_GROUP"
                    continue
                if _gid(attrs.get("GLOBALID"))!=_gid(expected["globalid"]):
                    failures[(kind,oid)]="GLOBALID_CHANGED"
                    continue
                geom=dict(feature.geometry or {})
                sr=dict(geom.get("spatialReference") or
                        getattr(features,"spatial_reference",None) or {})
                wkid=int(sr.get("latestWkid") or sr.get("wkid") or 0)
                # 'out_sr=4326' is requested, but a service can ignore it.
                if wkid not in (4326,0):
                    failures[(kind,oid)]="NOT_WGS84"
                    continue
                try:
                    if kind=="line":_lines(geom)
                    else:_xy([geom["x"],geom["y"]])
                    result[(kind,oid)]=geom
                except (ValueError,KeyError,TypeError):
                    failures[(kind,oid)]="INVALID_GEOMETRY"
        for oid in requested:
            if (kind,oid) not in result and (kind,oid) not in failures:
                failures[(kind,oid)]="SOURCE_RECORD_UNAVAILABLE"
    return result,failures

def export_gap_kmz(reports, output_path, *, service_url=None,version="sde.DEFAULT",
                   gis=None,layer_factory=None,fail_on_missing=True):
    """Return export manifest; Excel and REG services are never mutated.

    By default, refuse partial KMZ exports rather than silently hiding
    unreachable flagged features. A zero-gap report gets a valid empty KMZ.
    """
    index=collect_gaps(reports)
    geometries,failures=_lookup(index,service_url,version,gis,layer_factory)
    if failures and fail_on_missing:
        sample="; ".join(f"{asset}/{oid}: {reason}" for (asset,oid),reason
                         in list(sorted(failures.items()))[:8])
        raise RuntimeError("KMZ not published: flagged source geometries incomplete. "+sample)
    target=Path(output_path).expanduser().resolve()
    if target.suffix.lower()!=".kmz":raise ValueError("KMZ output must end in .kmz")
    if target.exists():raise FileExistsError("Refusing to overwrite KMZ: "+str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    xml=_render_kml(index,geometries)
    # Validate document XML before making user-facing archive.
    ET.fromstring(xml)
    temp=target.with_name(target.name+".pending")
    try:
        with ZipFile(temp,"w",compression=ZIP_DEFLATED) as z:
            z.writestr("doc.kml",xml)
        os.replace(temp,target)
    finally:
        temp.unlink(missing_ok=True)
    counts={kind:sum(asset==kind for asset,_ in geometries) for kind in SOURCE}
    return {
        "output_kmz":str(target),"total_gap_features":len(index),
        "features_exported":len(geometries),
        "features_not_mapped":len(failures),
        "skipped_records":[{"asset":a,"objectid":oid,"reason":reason}
                           for (a,oid),reason in sorted(failures.items())],
        "by_asset":counts,"source_version":version,
        "source_read_only":True,
        "geometries_wgs84":True,
        "buffer_width_m":None,
        "buffer_note":"Actual source line geometry, not a metric buffer. 1.5 m buffers require a separately verified projected-geometry step.",
    }

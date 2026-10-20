"""Offline network duplicate QA with fake FeatureServer; no REG requests."""
from __future__ import annotations
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from openpyxl import load_workbook

from meter_photo_qa.duplicate_network_scanner import (
    _all_ids, scan_network_duplicate_globalids,
)

GUID1="{11111111-1111-1111-1111-111111111111}"
GUID2="{22222222-2222-2222-2222-222222222222}"
GUID3="{33333333-3333-3333-3333-333333333333}"
GUID4="{44444444-4444-4444-4444-444444444444}"


def sample(oid,gid,kind,group,lon,lat):
    geometry={
        "paths":[[[lon,lat],[lon+0.0001,lat+0.0001]]],
        "spatialReference":{"wkid":4326}
    } if kind=="line" else {
        "x":lon,"y":lat,"spatialReference":{"wkid":4326}
    }
    attributes={
        "OBJECTID":oid,"GLOBALID":gid,"ASSETGROUP":group,
        "ASSETTYPE":1,"created_user":"operator",
        "last_edited_user":"operator",
        "created_date":1792500000000,"last_edited_date":1792500000000,
    }
    return SimpleNamespace(attributes=attributes,geometry=geometry)


class FakeLayer:
    def __init__(self,features):
        self.features=sorted(features,key=lambda f:f.attributes["OBJECTID"])
        self.calls=[]
        self.corrupt_projection=False
        self.count_change=0

    def query(self,**kwargs):
        self.calls.append(dict(kwargs))
        where=kwargs.get("where","")
        group_filter = None
        if "ASSETGROUP IN (9,10)" in where:
            group_filter={9,10}
        elif "ASSETGROUP = 7" in where:
            group_filter={7}
        elif "ASSETGROUP = 12" in where:
            group_filter={12}
        filtered=[
            feature for feature in self.features
            if group_filter is None or feature.attributes["ASSETGROUP"] in group_filter
        ]
        if kwargs.get("return_count_only"):
            return len(filtered)+self.count_change
        if kwargs.get("object_ids"):
            ids={int(x) for x in str(kwargs["object_ids"]).split(",") if x}
            selected=[f for f in filtered if f.attributes["OBJECTID"] in ids]
            if self.corrupt_projection and kwargs.get("out_sr")==4326:
                selected=[
                    SimpleNamespace(attributes=f.attributes,
                        geometry=dict(f.geometry,spatialReference={"wkid":32736}))
                    for f in selected
                ]
            return SimpleNamespace(
                features=selected,spatial_reference={"wkid":4326},
                exceeded_transfer_limit=False,
            )
        match=re.search(r"OBJECTID > (-?\d+)",where)
        if match is None:
            raise AssertionError("Unsafe full geometry scan or missing keyset: "+repr(kwargs))
        lower=int(match.group(1))
        take=kwargs.get("result_record_count",500)
        records=[f for f in filtered if f.attributes["OBJECTID"]>lower][:take]
        if kwargs.get("return_geometry") is not False:
            raise AssertionError("Identity scan asked for national geometries.")
        if kwargs.get("out_fields")!="OBJECTID,GLOBALID":
            raise AssertionError("Identity scan should fetch only two fields.")
        return SimpleNamespace(
            features=[
                SimpleNamespace(attributes=dict(f.attributes))
                for f in records
            ],
            exceeded_transfer_limit=False,
        )


class FakeCells:
    def __init__(self):
        self.calls=[]
    def query(self,**kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(features=[
            SimpleNamespace(attributes={
                "district":"Gasabo","sector":"Kimironko","cell":"Kibagabaga"
            })
        ],exceeded_transfer_limit=False)


class FullNetworkDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.line=FakeLayer([
            sample(1,GUID1,"line",9,30.02,-1.94),
            sample(2,GUID1.lower().strip("{}"),"line",9,30.02,-1.94),
            sample(3,GUID4,"line",2,30.11,-1.95),
        ])
        self.pole=FakeLayer([
            sample(40,GUID2,"pole",7,30.03,-1.93),
            sample(41,GUID3,"pole",7,30.07,-1.93),
        ])
        self.dt=FakeLayer([
            sample(50,GUID2,"transformer",12,30.04,-1.93),
            sample(51,"not-a-guid","transformer",12,30.08,-1.93),
        ])
        self.cells=FakeCells()
        self.layers={"line":self.line,"pole":self.pole,"transformer":self.dt}
        self.by_layer={10:self.line,12:self.pole,7:self.dt}
        self.urls=[]

    def layer_factory(self,url):
        self.urls.append(url)
        ending=int(url.rsplit("/",1)[-1])
        if ending in self.by_layer:
            return self.by_layer[ending]
        return self.cells

    def run_scan(self,path,**options):
        geo=types.ModuleType("arcgis.geometry")
        geo_filters=types.ModuleType("arcgis.geometry.filters")
        geo_filters.intersects=lambda geom,sr=None:geom
        with patch.dict(sys.modules,{
            "arcgis":types.ModuleType("arcgis"),
            "arcgis.geometry":geo,
            "arcgis.geometry.filters":geo_filters,
        }):
            return scan_network_duplicate_globalids(
                path,layer_factory=self.layer_factory,
                pause_seconds=0,page_size=2,**options,
            )

    def test_three_layers_cross_layer_duplicate_and_matching_kmz(self):
        with tempfile.TemporaryDirectory() as folder:
            result=self.run_scan(Path(folder)/"duplicates.xlsx")
            self.assertEqual(result["scanned_by_asset"],
                             {"line":3,"pole":2,"transformer":2})
            self.assertEqual(result["duplicate_globalid_groups"],2)
            self.assertEqual(result["duplicate_feature_records"],4)
            self.assertEqual(result["cross_layer_duplicate_groups"],1)
            self.assertEqual(result["kmz_features"],4)
            self.assertTrue(Path(result["output_xlsx"]).exists())
            self.assertTrue(Path(result["output_kmz"]).exists())
            self.assertEqual(Path(result["output_xlsx"]).with_suffix(".kmz"),
                             Path(result["output_kmz"]))
            book=load_workbook(result["output_xlsx"],read_only=True)
            try:
                self.assertIn("By District Sector Cell",book.sheetnames)
                grouped=list(book["Duplicate GlobalIDs"].values)
                self.assertEqual(len(grouped),3)
                self.assertTrue(any("POLE/40" in str(r[3]) and
                                    "TRANSFORMER/50" in str(r[3])
                                    for r in grouped[1:]))
                detailed=list(book["All Duplicate Records"].values)
                ids={(str(r[1]),int(r[3])) for r in detailed[1:]}
                self.assertEqual(ids,{
                    ("Electric Lines",1),("Electric Lines",2),
                    ("LV Poles",40),("Distribution Transformers",50),
                })
                self.assertEqual(detailed[1][7],"Gasabo")
            finally:
                book.close()
            with ZipFile(result["output_kmz"]) as z:
                self.assertEqual(z.namelist(),["doc.kml"])
                xml=ET.fromstring(z.read("doc.kml"))
                ns={"k":"http://www.opengis.net/kml/2.2"}
                marks=xml.findall(".//k:Placemark",ns)
                self.assertEqual(len(marks),4)
                self.assertEqual(
                    len(xml.findall(".//k:LineString",ns)),2)
                self.assertEqual(
                    len(xml.findall(".//k:Point",ns)),2)
            self.assertEqual(len(self.cells.calls),3)
            # One point of a cross-layer duplicate cannot overwrite its
            # peer's OBJECTID despite both datasets using integer IDs.
            for layer in (self.line,self.pole,self.dt):
                identity=[
                    call for call in layer.calls
                    if call.get("result_record_count") is not None
                ]
                self.assertTrue(identity)
                self.assertTrue(all(
                    call.get("out_fields")=="OBJECTID,GLOBALID" and
                    call.get("return_geometry") is False
                    for call in identity
                ))
                geometry=[
                    call for call in layer.calls if call.get("object_ids")
                ]
                self.assertTrue(geometry)
                self.assertTrue(all(
                    call.get("out_sr")!=4326 or call.get("return_geometry")
                    for call in geometry
                ))

    def test_lv_only_scope_excludes_mv_line_but_keeps_poles_transformers(self):
        # MV record GUID duplicates with another MV record must not be
        # reported by the LV-only option, but is included by full-network.
        self.line.features.append(
            sample(4,GUID4,"line",2,30.12,-1.95))
        with tempfile.TemporaryDirectory() as folder:
            result=self.run_scan(Path(folder)/"lv.xlsx",classes="lv")
            self.assertEqual(result["scanned_by_asset"]["line"],2)
            self.assertEqual(result["duplicate_globalid_groups"],2)

    def test_non_wgs84_geometry_rejected_with_no_partial_excel_or_kmz(self):
        self.dt.corrupt_projection=True
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,"WGS84 geometry not verified"):
                self.run_scan(Path(folder)/"invalid.xlsx")
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_changed_asset_group_fails_before_publishing_kmz(self):
        original_query=self.pole.query
        def changed_when_projected(**kwargs):
            result=original_query(**kwargs)
            if kwargs.get("out_sr")==4326 and kwargs.get("object_ids"):
                for feature in result.features:
                    feature.attributes=dict(feature.attributes,ASSETGROUP=8)
            return result
        self.pole.query=changed_when_projected
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,"asset group changed"):
                self.run_scan(Path(folder)/"asset_group_changed.xlsx")
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_arcgis_tool_has_derived_kmz_without_a_filter(self):
        import ast
        path=Path(__file__).resolve().parents[1]/"CustomerMeterPhotoQA.pyt"
        tree=ast.parse(path.read_text(encoding="utf-8"))
        tool=next(node for node in tree.body if isinstance(node,ast.ClassDef)
                  and node.name=="ScanAllElectricLineDuplicates")
        params=next(node for node in tool.body if isinstance(node,ast.FunctionDef)
                    and node.name=="getParameterInfo")
        source=ast.get_source_segment(path.read_text(encoding="utf-8"),params)
        self.assertIn('name="output_duplicates_kmz"',source)
        self.assertIn('parameterType="Derived"',source)
        self.assertIn('return [output, types, service, boundary, version, kmz]',source)
        self.assertNotIn("kmz.filter",source)
        action=next(node for node in tool.body if isinstance(node,ast.FunctionDef)
                    and node.name=="execute")
        code=ast.get_source_segment(path.read_text(encoding="utf-8"),action)
        self.assertIn('arcpy.SetParameterAsText(5, summary["output_kmz"])',code)

    def test_changed_count_rejects_all_outputs(self):
        self.pole.count_change=1
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,"count changed/incomplete"):
                self.run_scan(Path(folder)/"changed.xlsx")
            self.assertFalse(list(Path(folder).glob("*.xlsx")))

    def test_zero_duplicates_still_generates_valid_empty_kmz(self):
        self.line.features=self.line.features[:1]
        self.pole.features=self.pole.features[1:]
        self.dt.features=self.dt.features[1:]
        with tempfile.TemporaryDirectory() as folder:
            result=self.run_scan(Path(folder)/"empty.xlsx")
            self.assertEqual(result["duplicate_globalid_groups"],0)
            self.assertEqual(result["kmz_features"],0)
            with ZipFile(result["output_kmz"]) as z:
                root=ET.fromstring(z.read("doc.kml"))
                self.assertTrue(root.tag.endswith("kml"))

if __name__=="__main__":
    unittest.main()

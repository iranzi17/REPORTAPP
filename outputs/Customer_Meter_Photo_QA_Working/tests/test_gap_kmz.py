"""Verify matching source geometry and actual Excel issue details in Google Earth KMZ."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import hashlib

from openpyxl import Workbook
from meter_photo_qa.gap_kmz import collect_gaps,export_gap_kmz,read_gap_index

ROOT="{http://www.opengis.net/kml/2.2}"

def workbook(folder,name,sheets):
    path=Path(folder)/(name+".xlsx")
    wb=Workbook()
    first=wb.active
    first.title=next(iter(sheets))
    for title,rows in sheets.items():
        ws=first if title==first.title else wb.create_sheet(title)
        for row in rows:ws.append(row)
    wb.save(path)
    wb.close()
    return path

def input_reports(folder):
    lines=workbook(folder,"lines",{
        "Line Details":[
            ["Status","Source OBJECTID","GlobalID","Username",
             "Missing Attributes","Invalid Attributes"],
            ["FLAG",12,"{LINE-12}","julesmugae72","Transformer Name",""],
            ["MEETS_THRESHOLD",13,"{LINE-13}","ninamenye9683","",""],
            ["MEETS_THRESHOLD",14,"{LINE-14}","ninamenye9683","",""],
            ["MEETS_THRESHOLD",15,"{LINE-15}","janviersafari515","",""],
        ],
        "Outstanding LV Gaps":[
            ["Source OBJECTID","Outstanding Issues","Issue Details"],
            [13,"Supplying transformer","Transformer Name missing at incoming line"],
        ],
        "Duplicate Line Records":[
            ["Source OBJECTID","Other OBJECTIDs"],[14,"15"],[15,"14"],
        ],
    })
    pole=workbook(folder,"poles",{
        "Asset Details":[
            ["Status","OBJECTID","GlobalID","Surveyor Username",
             "Outstanding Issues","Recorded District","Recorded Sector",
             "Recorded Cell"],
            ["GAP",53,"{POLE-53}","ninamenye9683","Append Cable missing",
             "Gakenke","Nemba",""],
            ["NO_GAPS_FOUND",54,"{POLE-54}","ninamenye9683","","Gakenke","Nemba","Mugunga"],
        ]
    })
    trans=workbook(folder,"transformers",{
        "Asset Details":[
            ["Status","OBJECTID","GlobalID","Surveyor Username",
             "Outstanding Issues","Recorded District","Recorded Sector",
             "Recorded Cell"],
            ["GAP",31,"{TRANS-31}","martinnzubahimana","Protection Switch missing",
             "Burera","Cyanika",""],
            ["NO_GAPS_FOUND",32,"{TRANS-32}","martinnzubahimana","","","",""],
        ]
    })
    return {"line":lines,"pole":pole,"transformer":trans}

def data_layers():
    geometries={
        10:{i:{"paths":[[[30.0001+i/10000,-1.51],
                         [30.0002+i/10000,-1.512]]],
                 "spatialReference":{"wkid":4326}} for i in (12,13,14,15)},
        12:{53:{"x":30.03,"y":-1.45,"spatialReference":{"wkid":4326}}},
        7:{31:{"x":29.9,"y":-1.30,"spatialReference":{"wkid":4326}}},
    }
    gids={
        10:{i:"{LINE-"+str(i)+"}" for i in (12,13,14,15)},
        12:{53:"{POLE-53}"},
        7:{31:"{TRANS-31}"},
    }
    group={10:10,12:7,7:12}
    history=[]
    def layer_factory(layer):
        def query(**args):
            history.append((layer,args))
            ids=[int(x) for x in args["object_ids"].split(",")]
            return SimpleNamespace(
                spatial_reference={"wkid":4326},
                features=[
                    SimpleNamespace(
                        attributes={"OBJECTID":oid,"GLOBALID":gids[layer][oid],
                                    "ASSETGROUP":group[layer]},
                        geometry=geometries[layer][oid],
                    ) for oid in ids if oid in geometries[layer]
                ])
        return SimpleNamespace(query=query)
    return layer_factory,history

def buffer_test(line,metres):
    if metres!=1.5:raise AssertionError("Expected 1.5 metre buffer")
    return [[[30,-1.5],[30.001,-1.5],[30.001,-1.501],
             [30,-1.501],[30,-1.5]]]

class GapKMZTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.dir=Path(self.temp.name)
        self.reports=input_reports(self.dir)
        self.factory,self.history=data_layers()
        self.old={p:hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.reports.values()}

    def tearDown(self):
        self.temp.cleanup()

    def test_index_uses_original_gaps_not_only_threshold(self):
        lines=read_gap_index(self.reports["line"],"line")
        self.assertEqual(set(lines),{12,13,14,15})
        self.assertIn("Priority corrections",lines[13]["issues"])
        self.assertIn("Duplicate GlobalID",lines[14]["issues"])
        self.assertEqual(set(read_gap_index(self.reports["pole"],"pole")),{53})
        self.assertEqual(set(read_gap_index(self.reports["transformer"],"transformer")),{31})

    def test_excel_and_matching_kmz_same_run_with_true_line_buffer(self):
        dest=self.dir/"REG_Combined_LV_Quality_Gaps.kmz"
        report=export_gap_kmz(
            self.reports,dest,version="sde.DEFAULT",
            layer_factory=self.factory,buffer_fn=buffer_test
        )
        self.assertEqual(report["total_gap_features"],6)
        self.assertEqual(report["features_exported"],6)
        self.assertEqual(report["features_not_mapped"],0)
        self.assertEqual(report["by_asset"],{"line":4,"transformer":1,"pole":1})
        self.assertEqual(report["buffer_width_m"],1.5)
        self.assertTrue(dest.is_file())
        with ZipFile(dest) as kmz:
            self.assertIn("doc.kml",kmz.namelist())
            root=ET.fromstring(kmz.read("doc.kml"))
            placemarks=root.findall(".//"+ROOT+"Placemark")
            self.assertEqual(len(placemarks),6)
            self.assertEqual(len(root.findall(".//"+ROOT+"Point")),2)
            self.assertEqual(len(root.findall(".//"+ROOT+"LineString")),4)
            self.assertEqual(len(root.findall(".//"+ROOT+"Polygon")),4)
            text=" ".join(str(node.text) for node in root.iter() if node.text)
            self.assertIn("Transformer Name missing at incoming line",text)
            self.assertIn("Protection Switch missing",text)
            self.assertIn("OBJECTID 53",text)
            self.assertNotIn("OBJECTID 54",text)
        self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in self.reports.values()},self.old)
        self.assertEqual({layer for layer,_args in self.history},{7,10,12})
        self.assertTrue(all(args["gdb_version"]=="sde.DEFAULT"
                            and args["out_sr"]==4326
                            and args["return_geometry"] for _,args in self.history))

    def test_missing_geometry_blocks_partial_kmz(self):
        def missing(layer):
            obj=self.factory(layer)
            if layer!=12:return obj
            return SimpleNamespace(query=lambda **kw:
                SimpleNamespace(features=[],spatial_reference={"wkid":4326}))
        dest=self.dir/"partial.kmz"
        with self.assertRaisesRegex(RuntimeError,"not published"):
            export_gap_kmz(self.reports,dest,
                           layer_factory=missing,buffer_fn=buffer_test)
        self.assertFalse(dest.exists())

    def test_changed_globalid_blocks_wrong_geometry(self):
        def wrong(layer):
            obj=self.factory(layer)
            if layer!=12:return obj
            def query(**kw):
                feature=obj.query(**kw).features[0]
                feature.attributes["GLOBALID"]="{SOMEONE-ELSE}"
                return SimpleNamespace(features=[feature],
                                       spatial_reference={"wkid":4326})
            return SimpleNamespace(query=query)
        with self.assertRaisesRegex(RuntimeError,"GLOBALID_CHANGED"):
            export_gap_kmz(self.reports,self.dir/"wrong.kmz",
                           layer_factory=wrong,buffer_fn=buffer_test)

    def test_no_gaps_writes_valid_empty_kmz_without_gis_queries(self):
        clean=workbook(self.dir,"all_clean",{
            "Asset Details":[
                ["Status","OBJECTID","GlobalID","Surveyor Username",
                 "Outstanding Issues"],
                ["NO_GAPS_FOUND",1,"{CLEAN}","surveyor",""],
            ]
        })
        called=[]
        result=export_gap_kmz(
            {"pole":clean},self.dir/"empty.kmz",
            layer_factory=lambda x:called.append(x)
        )
        self.assertEqual(result["features_exported"],0)
        self.assertEqual(called,[])
        with ZipFile(self.dir/"empty.kmz") as z:
            self.assertEqual(ET.fromstring(z.read("doc.kml")).tag,ROOT+"kml")

    def test_refuses_to_overwrite_and_never_edits_source(self):
        target=self.dir/"already.kmz"
        target.write_bytes(b"not a kmz")
        with self.assertRaises(FileExistsError):
            export_gap_kmz(self.reports,target,
                           layer_factory=self.factory,buffer_fn=buffer_test)
        self.assertEqual(target.read_bytes(),b"not a kmz")
        self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in self.reports.values()},self.old)

    def test_missing_issue_description_fails_closed(self):
        bad=workbook(self.dir,"bad",{
            "Asset Details":[
                ["Status","OBJECTID","GlobalID","Surveyor Username",
                 "Outstanding Issues"],
                ["GAP",100,"{A}","survey",""],
            ]
        })
        with self.assertRaisesRegex(ValueError,"missing explanations"):
            collect_gaps({"pole":bad})

if __name__=="__main__":
    import unittest
    unittest.main()

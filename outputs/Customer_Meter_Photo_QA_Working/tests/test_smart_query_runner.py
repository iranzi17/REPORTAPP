from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meter_photo_qa.smart_query_runner import run_smart_query


class GPResult:
    def __init__(self, value):
        self.value=value
    def getOutput(self,idx):
        return self.value


class FakeArcPy:
    def __init__(self,count=3):
        self.count=count
        self.calls=[]
        self.added=[]
        self.env=SimpleNamespace(scratchGDB="/scratch/scratch.gdb")
        self.management=SimpleNamespace(
            MakeFeatureLayer=self.make,
            GetCount=self.get_count,
            SelectLayerByLocation=self.select,
            CopyFeatures=self.copy,
            Delete=self.delete,
        )
        self.mp=SimpleNamespace(ArcGISProject=lambda key:SimpleNamespace(
            activeMap=SimpleNamespace(addDataFromPath=self.add_map)
        ))
    def make(self,url,name,where):
        self.calls.append(("make",url,name,where))
        return GPResult(name)
    def get_count(self,layer):
        self.calls.append(("count",str(layer)))
        if "area" in str(layer):
            return GPResult("2")
        return GPResult(str(self.count))
    def select(self,layer,relation,admin,selection_type):
        self.calls.append(("select",layer,relation,admin,selection_type))
    def CreateUniqueName(self,name,gdb):
        return gdb+"/"+name
    def copy(self,layer,output):
        self.calls.append(("copy",layer,output))
        return GPResult(output)
    def delete(self,path):
        self.calls.append(("delete",str(path)))
    def add_map(self,path):
        self.added.append(path)


class SmartRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fake=FakeArcPy()
        self.feature_mod=types.ModuleType("arcgis.features")
        self.feature_mod.FeatureLayer=lambda url,gis:SimpleNamespace(
            properties=SimpleNamespace(
                fields=[
                    {"name":"ASSETGROUP","type":"esriFieldTypeInteger"},
                    {"name":"Manufacturers","type":"esriFieldTypeString"},
                    {"name":"Notes","type":"esriFieldTypeString"},
                ],
                types=[],
            )
        )

    def run_fake(self,request,mode="preview",arcpy=None):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder,patch.dict(
            sys.modules,{
                "arcgis":types.ModuleType("arcgis"),
                "arcgis.features":self.feature_mod,
            },
        ):
            result=run_smart_query(
                request,
                mode=mode,
                output_json=Path(folder)/"smart.json",
                arcpy_module=arcpy or self.fake,
                gis=object(),
            )
            snapshot=json.loads(Path(result["audit_log"]).read_text())
        return result,snapshot

    def test_preview_count_and_sql_does_not_copy_or_edit_source(self):
        result,snapshot=self.run_fake("Show LV poles in Gicumbi with missing manufacturer")
        self.assertEqual(result["matched_features"],3)
        self.assertIn("Manufacturers IS NULL",result["attribute_sql"])
        self.assertIn("'GICUMBI'",result["spatial_boundary_sql"])
        self.assertIsNone(result["local_feature_class"])
        self.assertFalse(result["added_to_map"])
        self.assertEqual(snapshot["matched_features"],3)
        self.assertEqual(sum(c[0]=="select" for c in self.fake.calls),1)
        self.assertFalse(any(c[0]=="copy" for c in self.fake.calls))
        self.assertTrue(any(c[0]=="delete" for c in self.fake.calls))
        self.assertTrue(all(c[0] in ("make","count","select","delete") for c in self.fake.calls))

    def test_local_copy_writes_only_to_scratchGDB(self):
        result,_=self.run_fake(
            "Show LV poles in Gicumbi with missing manufacturer",mode="local_copy"
        )
        self.assertEqual(result["matched_features"],3)
        self.assertTrue(result["added_to_map"])
        self.assertTrue(result["local_feature_class"].startswith("/scratch/scratch.gdb/"))
        self.assertEqual(self.fake.added,[result["local_feature_class"]])
        self.assertEqual(sum(c[0]=="copy" for c in self.fake.calls),1)
        self.assertNotIn(result["local_feature_class"],
                         [c[1] for c in self.fake.calls if c[0]=="delete"])

    def test_too_many_results_never_create_local_copy(self):
        fake=FakeArcPy(count=50000)
        with patch.dict(sys.modules,{
            "arcgis":types.ModuleType("arcgis"),
            "arcgis.features":self.feature_mod,
        }):
            with self.assertRaisesRegex(ValueError,"safety limit"):
                run_smart_query("Show LV poles",mode="local_copy",
                                arcpy_module=fake,gis=object())
        self.assertFalse(any(c[0]=="copy" for c in fake.calls))

    def test_no_geo_request_has_no_boundary_service_layer(self):
        result,_=self.run_fake("Count LV poles with missing manufacturer")
        self.assertIsNone(result["spatial_boundary_sql"])
        self.assertEqual(len([c for c in self.fake.calls if c[0]=="make"]),1)
        self.assertFalse(any(c[0]=="select" for c in self.fake.calls))

    def test_unverifiable_field_aborts_before_map_selection(self):
        self.feature_mod.FeatureLayer=lambda url,gis:SimpleNamespace(
            properties=SimpleNamespace(
                fields=[{"name":"BadField"}],types=[]
            )
        )
        with patch.dict(sys.modules,{
            "arcgis":types.ModuleType("arcgis"),
            "arcgis.features":self.feature_mod,
        }):
            with self.assertRaisesRegex(ValueError,"verify live"):
                run_smart_query("Show LV poles in Gicumbi with missing manufacturer",
                                arcpy_module=self.fake,gis=object())
        self.assertEqual(self.fake.calls,[])

    def test_bad_geographic_filter_fails_closed_without_unfiltered_output(self):
        fake=FakeArcPy(count=3)
        fake.management.SelectLayerByLocation=lambda *a,**k:(
            (_ for _ in ()).throw(RuntimeError("Boundary 503"))
        )
        with patch.dict(sys.modules,{
            "arcgis":types.ModuleType("arcgis"),
            "arcgis.features":self.feature_mod,
        }):
            with self.assertRaisesRegex(RuntimeError,"Boundary 503"):
                run_smart_query("Show LV poles in Gicumbi with missing manufacturer",
                                mode="local_copy",arcpy_module=fake,gis=object())
        self.assertFalse(any(c[0]=="copy" for c in fake.calls))
        self.assertTrue(any(c[0]=="delete" for c in fake.calls))

if __name__=="__main__":
    unittest.main()

from __future__ import annotations

import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class FakeParameter:
    def __init__(self,**kwargs):
        self.name=kwargs.get("name")
        self.filter=SimpleNamespace(type=None,list=[])
        self.value=None
        self.category=None
        self.error=None
    @property
    def valueAsText(self):
        return str(self.value) if self.value is not None else None
    def setErrorMessage(self,message):
        self.error=message


class SmartToolUiTests(unittest.TestCase):
    def setUp(self):
        self.output=[]
        self.fake=SimpleNamespace(
            Parameter=FakeParameter,
            env=SimpleNamespace(scratchGDB="/tmp/scratch.gdb"),
            mp=SimpleNamespace(ArcGISProject=lambda _:None),
            AddMessage=self.output.append,
            AddWarning=lambda x:self.output.append("WARNING: "+x),
            SetParameterAsText=lambda idx, value:self.output.append(f"OUTPUT {idx}: {value}"),
        )

    def toolbox(self):
        return runpy.run_path(str(ROOT/"CustomerMeterPhotoQA.pyt"))

    def test_parameters_and_invalid_commands(self):
        with patch.dict(sys.modules,{"arcpy":self.fake}):
            app=self.toolbox()
            tool=app["AskReportApp"]()
            self.assertIn(app["AskReportApp"],app["Toolbox"]().tools)
            params=tool.getParameterInfo()
            self.assertEqual(len(params),10)
            self.assertEqual(params[0].name,"natural_language_query")
            self.assertIn("Preview query and count only (read-only)",params[1].filter.list)
            self.assertEqual(params[2].name,"output_query_log")
            self.assertEqual(params[6].name,"lv_feeder_method")
            self.assertTrue(params[6].valueAsText.startswith("Geometry continuity"))
            self.assertEqual(params[7].name,"endpoint_tolerance")
            self.assertEqual(params[8].name,"qa_start_date")
            self.assertEqual(params[9].name,"qa_end_date")
            params[0].value="Delete LV poles in Gicumbi"
            tool.updateMessages(params)
            self.assertIn("not supported",params[0].error)

    def test_execute_passes_query_and_local_copy_only_when_selected(self):
        with patch.dict(sys.modules,{"arcpy":self.fake}):
            app=self.toolbox()
            tool=app["AskReportApp"]()
            params=tool.getParameterInfo()
            params[0].value="Show LV poles in Gicumbi with missing manufacturer"
            params[1].value="Create local filtered layer and add to map (read-only source)"
            fake_response={
                "audit_log":"c:/tmp/qa.json",
                "interpreted":{"asset":"pole","district":"Gicumbi"},
                "attribute_sql":"ASSETGROUP IN (7) AND (Manufacturers IS NULL)",
                "spatial_boundary_sql":"UPPER(district) = 'GICUMBI'",
                "matched_features":13,
                "local_feature_class":"c:/tmp/scratch.gdb/QA",
                "cautions":["Source unchanged."],
            }
            observed={}
            original=tool.execute.__globals__["run_smart_query"]
            tool.execute.__globals__["run_smart_query"]=lambda **kwargs:(
                observed.update(kwargs) or fake_response
            )
            try:
                tool.execute(params,None)
            finally:
                tool.execute.__globals__["run_smart_query"]=original
            self.assertEqual(observed["mode"],"local_copy")
            self.assertEqual(observed["request"],params[0].value)
            self.assertTrue(any("13 matching pole" in m for m in self.output))
            self.assertTrue(any("OUTPUT 2" in m for m in self.output))

    def test_prepare_lv_lines_routes_to_original_three_asset_combined_qa(self):
        from datetime import datetime
        with patch.dict(sys.modules,{"arcpy":self.fake}):
            app=self.toolbox()
            tool=app["AskReportApp"]()
            params=tool.getParameterInfo()
            params[0].value="Prepare LV Lines Report for Kwizerwa Edison in Gicumbi"
            params[5].value="C:/ReportDestination"
            params[6].value="Geometry continuity - no Utility Network trace required"
            params[7].value=1.5
            params[8].value=datetime(2026,9,14)
            params[9].value=datetime(2026,10,14)
            globals_=tool.execute.__globals__
            original_combined=globals_["run_combined_qa_report"]
            original_feeder=globals_["run_lv_feeder_report"]
            captured={}
            def combined(**kwargs):
                captured.update(kwargs)
                return {
                    "status":"COMPLETE","district":"Gicumbi",
                    "output_xlsx":"C:/ReportDestination/Combined/QA.xlsx",
                    "components_folder":"C:/ReportDestination/Combined/Components",
                    "date_start":"2026-09-14","date_end":"2026-10-14",
                    "start_date":"2026-09-14","end_date":"2026-10-14",
                    "geometry":{"status":"COMPLETE"},
                }
            try:
                globals_["run_combined_qa_report"]=combined
                globals_["run_lv_feeder_report"]=lambda **kwargs: (
                    (_ for _ in ()).throw(AssertionError(
                        "Old standalone geometry report MUST NOT replace combined QA."
                    ))
                )
                tool.execute(params,None)
            finally:
                globals_["run_combined_qa_report"]=original_combined
                globals_["run_lv_feeder_report"]=original_feeder
            self.assertEqual(captured["district"],"Gicumbi")
            self.assertEqual(captured["usernames"],["ninamenye9683"])
            self.assertEqual(captured["output_folder"],"C:/ReportDestination")
            self.assertTrue(captured["include_continuity"])
            self.assertEqual(captured["start_date"].date().isoformat(),"2026-09-14")
            self.assertEqual(captured["end_date"].date().isoformat(),"2026-10-14")
            self.assertTrue(any("Combined QA report saved" in m for m in self.output))

if __name__=="__main__":
    unittest.main()

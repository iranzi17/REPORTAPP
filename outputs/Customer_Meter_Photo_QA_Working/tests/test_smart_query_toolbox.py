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

    def test_screenshot_report_updates_action_dates_and_executes_combined(self):
        from datetime import date, datetime, timedelta
        with patch.dict(sys.modules,{"arcpy":self.fake}):
            app=self.toolbox()
            tool=app["AskReportApp"]()
            params=tool.getParameterInfo()
            self.assertIn("Generate consolidated Excel QA report (Lines, Transformers, Poles)",
                          params[1].filter.list)
            params[0].value="prepare report for julesmugae72 in Gicumbi the last 2 weeks"
            params[5].value="C:/ReportDestination"
            tool.updateParameters(params)
            self.assertEqual(params[1].valueAsText,
                             "Generate consolidated Excel QA report (Lines, Transformers, Poles)")
            expected_start=date.today()-timedelta(days=13)
            self.assertEqual(params[8].value.date(),expected_start)
            self.assertEqual(params[9].value.date(),date.today())
            tool.updateMessages(params)
            self.assertIsNone(params[0].error)
            observed={}
            original=tool.execute.__globals__["run_combined_qa_report"]
            def combined(**kwargs):
                observed.update(kwargs)
                return {
                    "status":"COMPLETE","district":"Gicumbi",
                    "output_xlsx":"C:/ReportDestination/Combined/Report.xlsx",
                    "components_folder":"C:/ReportDestination/Combined/Components",
                    "start_date":str(expected_start),"end_date":str(date.today()),
                    "geometry":{"status":"COMPLETE"},
                }
            tool.execute.__globals__["run_combined_qa_report"]=combined
            try:
                # Manual date picker modifications cannot silently override
                # explicitly requested periods written in the command.
                params[8].value=datetime(2026,1,1)
                tool.execute(params,None)
            finally:
                tool.execute.__globals__["run_combined_qa_report"]=original
            self.assertEqual(observed["usernames"],["julesmugae72"])
            self.assertEqual(observed["district"],"Gicumbi")
            self.assertEqual(observed["start_date"],expected_start)
            self.assertEqual(observed["end_date"],date.today())
            self.assertTrue(any("Requested period" in m for m in self.output))
            params[0].value="show LV poles in Gicumbi with missing manufacturer"
            tool.updateParameters(params)
            self.assertEqual(params[1].valueAsText,
                             "Preview query and count only (read-only)")

    def test_surveyor_templates_auto_choose_excel_action(self):
        with patch.dict(sys.modules,{"arcpy":self.fake}):
            app=self.toolbox()
            tool=app["AskReportApp"]()
            params=tool.getParameterInfo()
            params[0].value="Show surveyors missing manufacturer on LV poles in Gicumbi"
            tool.updateParameters(params)
            self.assertEqual(params[1].valueAsText,
                             "Generate surveyor attribute audit Excel report")
            tool.updateMessages(params)
            self.assertIsNone(params[0].error)

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

    def test_surveyor_template_query_uses_live_schema_excel_audit(self):
        with patch.dict(sys.modules,{"arcpy":self.fake}):
            app=self.toolbox()
            tool=app["AskReportApp"]()
            params=tool.getParameterInfo()
            params[0].value=(
                "Give me surveyors who are filling the height of pole "
                "with the values greater than 12 in Gicumbi"
            )
            params[2].value="C:/ReportDestination/Query_Height.json"
            params[5].value="C:/ReportDestination"
            tool.updateMessages(params)
            self.assertIsNone(params[0].error)
            backend=tool.execute.__globals__
            original=backend["run_template_surveyor_audit"]
            captured={}
            def audit(**kw):
                captured.update(kw)
                return {
                    "output_xlsx":"C:/ReportDestination/surveyors.xlsx",
                    "output_json":"C:/ReportDestination/Query_Height.json",
                    "resolved_criteria":[{
                        "live_field":"Pole_Height","operator":"gt","value":12,
                    }],
                    "matching_features":14,
                    "matching_surveyors":3,
                }
            backend["run_template_surveyor_audit"]=audit
            try:
                tool.execute(params,None)
            finally:
                backend["run_template_surveyor_audit"]=original
            self.assertEqual(captured["output_folder"],"C:/ReportDestination")
            self.assertEqual(captured["request"],params[0].value)
            self.assertTrue(any("14 matching features" in str(message)
                                for message in self.output))
            self.assertTrue(any("surveyor template audit excel" in str(message).lower()
                                for message in self.output))

if __name__=="__main__":
    unittest.main()

"""Make the KMZ genuinely visible as a geoprocessing output (no ArcGIS login)."""
from __future__ import annotations
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
import json

TOOLBOX = Path(__file__).resolve().parents[1] / "CustomerMeterPhotoQA.pyt"
TREE = ast.parse(TOOLBOX.read_text(encoding="utf-8"))


def method_in_class(cls, name):
    node = next(x for x in TREE.body
                if isinstance(x, ast.ClassDef) and x.name == cls)
    return next(x for x in node.body
                if isinstance(x, ast.FunctionDef) and x.name == name)


class DerivedKMZOutputTests(TestCase):
    def test_pole_and_transformer_derive_kmz_without_changing_inputs(self):
        parameter_list = method_in_class("_AssetQualityTool", "getParameterInfo")
        last = next(x.value for x in ast.walk(parameter_list)
                    if isinstance(x, ast.Return))
        self.assertIsInstance(last, ast.List)
        self.assertEqual(len(last.elts), 12)
        self.assertEqual(last.elts[-1].id, "gap_kmz")
        parameters = [x for x in ast.walk(parameter_list)
                      if isinstance(x, ast.Call)
                      and isinstance(x.func, ast.Attribute)
                      and x.func.attr == "Parameter"]
        self.assertTrue(any(
            any(kw.arg == "name" and isinstance(kw.value, ast.Constant)
                and kw.value.value == "output_gap_kmz" for kw in call.keywords)
            and any(kw.arg == "parameterType" and kw.value.value == "Derived"
                    for kw in call.keywords)
            for call in parameters))
        self.assertTrue(any(
            isinstance(x, ast.ClassDef) and x.name == "WatchLVPoleQuality"
            for x in TREE.body))
        self.assertTrue(any(
            isinstance(x, ast.ClassDef) and x.name == "WatchDistributionTransformerQuality"
            for x in TREE.body))

    def test_line_quality_derived_kmz_added_after_all_existing_parameters(self):
        method = method_in_class("WatchLVLineDataQuality", "getParameterInfo")
        outputs = [x.value for x in ast.walk(method)
                   if isinstance(x, ast.Return)]
        self.assertEqual(len(outputs), 1)
        self.assertIsInstance(outputs[0], ast.List)
        self.assertEqual(len(outputs[0].elts), 17)
        self.assertEqual(outputs[0].elts[-1].id, "gap_kmz")

    def test_pole_tool_exposes_path_only_after_successful_kmz_export(self):
        # Extract only the real execute() body without importing arcpy or
        # reading credentials / the live REG FeatureServer.
        fn = method_in_class("_AssetQualityTool", "execute")
        fn.decorator_list = []
        snippet = ast.fix_missing_locations(
            ast.Module(body=[fn], type_ignores=[]))
        gp = Mock()
        summary = {
            "output_xlsx": "C:/Reports/poles.xlsx",
            "total": 599, "with_gaps": 62,
            "not_verified": 0, "no_gaps_found": 537,
            "unverified_live_fields": [],
            "duplicate_globalid_groups": 0,
            "surveyor_filter": ["surveyor"],
            "incomplete_recorded_locations": 0,
        }
        result = {"output_kmz": "C:/Reports/poles_Gaps.kmz"}
        parameters = [SimpleNamespace(valueAsText="", value=None)
                      for _ in range(12)]
        names = {
            "arcpy": gp,
            "json": json,
            "_export_companion_kmz": Mock(return_value=result),
            "run_asset_quality": Mock(return_value=summary),
            "_split_multivalue": Mock(return_value=[]),
            "_drawn_boundary_geometry": Mock(return_value=None),
        }
        exec(compile(snippet, str(TOOLBOX), "exec"), names)
        tool = SimpleNamespace(asset="pole")
        names["execute"](tool, parameters, None)
        gp.SetParameterAsText.assert_any_call(0, "C:/Reports/poles.xlsx")
        gp.SetParameterAsText.assert_any_call(11, "C:/Reports/poles_Gaps.kmz")
        self.assertEqual(names["_export_companion_kmz"].call_count, 1)
        # If source geometry is incomplete, Excel output remains valid, but
        # no KMZ derived path must be advertised as a successful output.
        gp.reset_mock()
        names["_export_companion_kmz"].return_value = {"status": "UNAVAILABLE"}
        names["execute"](tool, parameters, None)
        gp.SetParameterAsText.assert_called_once_with(0, "C:/Reports/poles.xlsx")


if __name__ == "__main__":
    import unittest
    unittest.main()

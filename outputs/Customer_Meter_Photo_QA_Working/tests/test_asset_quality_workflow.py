from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import load_workbook

from meter_photo_qa.asset_quality_runner import run_asset_quality
from meter_photo_qa.progress_report import DEFAULT_LINE_SERVICE_URL


class FakeLayer:
    def __init__(self, rows):
        self.rows = rows
        names = ["OBJECTID", "GLOBALID", "ASSETGROUP", "ASSETTYPE",
                 "created_user", "created_date", "last_edited_date",
                 "Transfomer_name_", "Manufacturer", "Serial_No",
                 "Phases", "Rated_kVA", "Notes"]
        self.properties = SimpleNamespace(
            fields=[{"name": x, "alias": x, "type": "esriFieldTypeString"} for x in names],
            types=[], maxRecordCount=500,
        )
        self.requests = []

    def query(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs.get("return_ids_only"):
            return {"objectIds": [item["OBJECTID"] for item in self.rows]}
        ids = {int(v) for v in kwargs["object_ids"].split(",")}
        return SimpleNamespace(features=[
            SimpleNamespace(attributes=item)
            for item in self.rows if item["OBJECTID"] in ids
        ])


def transformer(gid, oid, **values):
    return {
        "OBJECTID": oid, "GLOBALID": gid, "ASSETGROUP": 12,
        "ASSETTYPE": 4, "created_user": "survey.user",
        "created_date": 1789420000000, "last_edited_date": 1789420000000,
        "Transfomer_name_": "TR-1", "Manufacturer": "ABB",
        "Serial_No": "SN-1", "Phases": 3, "Rated_kVA": 100,
        **values,
    }


def pole(gid, oid, note="", manufacturer=None, atype=1):
    return {
        "OBJECTID": oid, "GLOBALID": gid, "ASSETGROUP": 7,
        "ASSETTYPE": atype, "created_user": "pole.user",
        "created_date": 1789420000000, "last_edited_date": 1789420000000,
        "Manufacturer": manufacturer, "Notes": note,
    }


class AssetWorkflowTests(unittest.TestCase):
    def run_fake(self, asset, records):
        layer = FakeLayer(records)
        module_arcgis = types.ModuleType("arcgis")
        module_features = types.ModuleType("arcgis.features")
        module_filters = types.ModuleType("arcgis.geometry.filters")
        module_geometry = types.ModuleType("arcgis.geometry")
        module_features.FeatureLayer = lambda url, gis: layer
        module_filters.intersects = lambda geometry, sr=None: geometry
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            with patch.dict(sys.modules, {
                "arcgis": module_arcgis, "arcgis.features": module_features,
                "arcgis.geometry": module_geometry,
                "arcgis.geometry.filters": module_filters,
            }):
                output = run_asset_quality(
                    asset, Path(folder)/"asset_qc.xlsx",
                    "2026-10-01", "2026-10-13",
                    service_url=DEFAULT_LINE_SERVICE_URL, gis=object(),
                )
                wb = load_workbook(output["output_xlsx"], read_only=True)
                snapshot = {
                    sheet.title: list(sheet.values)
                    for sheet in wb
                }
                wb.close()
                return output, snapshot, layer.requests

    def test_transformer_reads_group12_and_reports_gaps(self):
        report, sheets, requests = self.run_fake(
            "transformer",
            [transformer("{G1}", 1), transformer("{G2}", 2, Manufacturer=None)],
        )
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["with_gaps"], 1)
        self.assertEqual(report["no_gaps_found"], 1)
        self.assertEqual(report["not_verified"], 0)
        self.assertIn("ASSETGROUP = 12", requests[0]["where"])
        self.assertNotIn("Branch", str(sheets["Asset Details"][0]))
        self.assertIn("Manufacturer missing", sheets["Asset Details"][1][5])
        self.assertIn("Schema Verification", sheets)
        self.assertTrue(any(x[0] == "name" and x[1] == "Transfomer_name_"
                            for x in sheets["Schema Verification"]))

    def test_poles_documented_absent_nameplate(self):
        report, sheets, requests = self.run_fake(
            "pole", [pole("{P1}", 1, "No name plate"),
                     pole("{P2}", 2, ""), pole("{P3}", 3, "checked", "Pole Inc", 3)],
        )
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["with_gaps"], 1)
        self.assertEqual(report["no_gaps_found"], 2)
        self.assertIn("ASSETGROUP = 7", requests[0]["where"])
        rows = sheets["Asset Details"]
        self.assertTrue(any(row[12] == "DOCUMENTED_NO_NAMEPLATE" for row in rows[1:]))
        self.assertTrue(any("Manufacturer missing" in str(row[5]) for row in rows[1:]))

    def test_schema_not_found_is_not_counted_as_clean(self):
        report, sheets, _ = self.run_fake("transformer", [transformer("{T}", 1)])
        self.assertEqual(report["no_gaps_found"], 1)


if __name__ == "__main__":
    unittest.main()

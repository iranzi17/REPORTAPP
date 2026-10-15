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
                 "Transfomer_name_", "Owner_Name", "Type_of_Installation",
                 "Phase_Normal", "Transformer_Protection_Switch",
                 "Transformer_mounting_support", "Number_of_Low_Voltage_feeders",
                 "Manufacturer", "Serial_No", "Rated_kVA", "Notes",
                 "Append_Cable", "Pole_Height",
                 "District", "Sector", "Cell"]
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
        "Transfomer_name_": "TR-1", "Owner_Name": "REG",
        "Type_of_Installation": "Outdoor", "Phase_Normal": 3,
        "Transformer_Protection_Switch": "DropOut",
        "Transformer_mounting_support": "PH Wooden",
        "Number_of_Low_Voltage_feeders": 2,
        "Manufacturer": "ABB", "Serial_No": "SN-1", "Rated_kVA": 100,
        "District": "Burera", "Sector": "Cyanika", "Cell": "Gasiza",
        **values,
    }


def pole(gid, oid, note="", manufacturer=None, atype=1,
         append_cable="No"):
    return {
        "OBJECTID": oid, "GLOBALID": gid, "ASSETGROUP": 7,
        "ASSETTYPE": atype, "created_user": "pole.user",
        "created_date": 1789420000000, "last_edited_date": 1789420000000,
        "Manufacturer": manufacturer, "Notes": note,
        "Append_Cable": append_cable, "Pole_Height": 10,
        "District": "Rulindo", "Sector": "Buyoga", "Cell": "Munyana",
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
            [transformer("{G1}", 1), transformer("{G2}", 2, Owner_Name=None)],
        )
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["with_gaps"], 1)
        self.assertEqual(report["no_gaps_found"], 1)
        self.assertEqual(report["not_verified"], 0)
        self.assertIn("ASSETGROUP = 12", requests[0]["where"])
        self.assertNotIn("Branch", str(sheets["Asset Details"][0]))
        self.assertIn("Owner Name missing", sheets["Asset Details"][1][8])
        self.assertIn("Schema Verification", sheets)
        self.assertIn("By Recorded Location", sheets)
        schema_headers = [row[0] for row in sheets["Schema Verification"]
                          if row[0] == "Rule / Field Purpose"]
        self.assertEqual(len(schema_headers), 1)
        overview = {row[0]: row[1] for row in sheets["Summary"] if row[0]}
        self.assertEqual(overview["Surveyor filter"], "ALL surveyors (no filter)")
        self.assertEqual(overview["Surveyor accounts returned"], 1)
        self.assertEqual(overview["Records lacking all three recorded location fields"], 0)
        self.assertIn("District", requests[1]["out_fields"])
        detail = sheets["Asset Details"]
        self.assertEqual(detail[0][5:8], (
            "Recorded District", "Recorded Sector", "Recorded Cell"
        ))
        self.assertEqual(detail[1][5:8], ("Burera", "Cyanika", "Gasiza"))
        location = sheets["By Recorded Location"]
        self.assertEqual(location[1][:6], ("Burera", "Cyanika", "Gasiza", 2, 1, 1))
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
        self.assertTrue(any(row[21] == "DOCUMENTED_NO_NAMEPLATE" for row in rows[1:]))
        self.assertEqual(sheets["By Recorded Location"][1][:5],
                         ("Rulindo", "Buyoga", "Munyana", 3, 1))
        self.assertTrue(any("Manufacturer missing" in str(row[8]) for row in rows[1:]))
        self.assertIn("Append_Cable", requests[1]["out_fields"])
        self.assertEqual(rows[0][-2:], ("Append Cable", "Append Cable QA"))
        self.assertEqual(
            [row[-1] for row in rows[1:]], ["RECORDED", "RECORDED", "RECORDED"]
        )
        self.assertTrue(any(
            row[0] == "append_cable" and row[1] == "Append_Cable"
            for row in sheets["Schema Verification"]
        ))

    def test_missing_append_cable_in_pole_report_is_mandatory_issue(self):
        report, sheets, _ = self.run_fake(
            "pole", [
                pole("{P1}", 101, "No name plate", append_cable=None),
                pole("{P2}", 102, "No name plate", append_cable="No"),
                pole("{P3}", 103, "No name plate", append_cable="Unknown"),
            ],
        )
        self.assertEqual(report["with_gaps"], 2)
        self.assertEqual(report["original_attribute_gap_records"], 2)
        self.assertEqual(report["original_attribute_issue_count"], 2)
        details=sheets["Asset Details"]
        self.assertEqual(details[0][-2:], ("Append Cable", "Append Cable QA"))
        self.assertEqual(
            sum("Append Cable missing/unknown" in str(row[8])
                for row in details[1:]), 2
        )
        summary=dict((row[0],row[1]) for row in sheets["Summary"]
                     if row[0] and len(row)>1)
        self.assertEqual(summary["Append Cable (mandatory) — missing/unknown"], 2)
        self.assertEqual(summary["Append Cable — schema not verified"], 0)
        self.assertTrue(any(
            "Append Cable" in str(row[1])
            for row in sheets["Rules"]
        ))

    def test_duplicate_transformer_ids_across_multiple_attribute_batches_are_reported(self):
        # Distinct OBJECTIDs with one repeated GlobalID must not stop the QA.
        # 151+ records intentionally cross the default 150-feature batch size.
        duplicate_gid = "{8013868c-1ed5-46a9-8f97-2c3a8bd86a01}"
        records = [transformer(f"{{TEMP-{i}}}", i)
                   for i in range(1, 151)]
        records += [
            transformer(duplicate_gid, 605878, Owner_Name=None),
            transformer(duplicate_gid.lower().strip("{}"), 606278),
        ]
        report, sheets, requests = self.run_fake("transformer", records)
        self.assertEqual(report["total"], 152)
        self.assertEqual(report["duplicate_globalid_groups"], 1)
        self.assertEqual(report["duplicate_feature_records"], 2)
        self.assertEqual(report["extra_records_with_reused_globalids"], 1)
        self.assertEqual(report["with_gaps"], 2)
        self.assertEqual(report["original_attribute_gap_records"], 1)
        self.assertEqual(report["original_attribute_issue_count"], 1)
        self.assertEqual(report["issue_count"], 3)
        self.assertEqual(report["no_gaps_found"], 150)
        group_rows = sheets["Duplicate GlobalIDs"]
        self.assertEqual(len(group_rows), 2)
        self.assertEqual(group_rows[1][1], "605878; 606278")
        details = sheets["Duplicate Asset Records"]
        self.assertEqual(len(details), 3)
        self.assertEqual({row[1] for row in details[1:]}, {605878, 606278})
        self.assertEqual({row[4:7] for row in details[1:]},
                         {("Burera", "Cyanika", "Gasiza")})
        self.assertIn("Owner Name missing", details[1][10])
        self.assertEqual(details[2][10], None)
        all_assets = sheets["Asset Details"]
        self.assertEqual(len(all_assets), 153)
        affected = [row for row in all_assets[1:] if row[1] in (605878, 606278)]
        self.assertEqual(len(affected), 2)
        self.assertTrue(all(row[0] == "GAP" for row in affected))
        self.assertEqual(len([q for q in requests if q.get("object_ids")]), 2)

    def test_duplicate_pole_ids_keep_no_nameplate_rule_distinct(self):
        pole_g = "{12345678-1234-1234-1234-1234567890ab}"
        records = [
            pole(pole_g, 101, "No name plate"),
            pole(pole_g, 102, ""),
        ]
        report, sheets, _ = self.run_fake("pole", records)
        self.assertEqual(report["duplicate_globalid_groups"], 1)
        self.assertEqual(report["duplicate_feature_records"], 2)
        self.assertEqual(report["original_attribute_gap_records"], 1)
        self.assertEqual(report["with_gaps"], 2)
        self.assertIn("Manufacturer missing", sheets["Duplicate Asset Records"][2][10])

    def test_schema_not_found_is_not_counted_as_clean(self):
        report, sheets, _ = self.run_fake("transformer", [transformer("{T}", 1)])
        self.assertEqual(report["no_gaps_found"], 1)


if __name__ == "__main__":
    unittest.main()

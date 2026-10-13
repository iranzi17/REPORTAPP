from __future__ import annotations
import unittest
from meter_photo_qa.asset_quality import (
    ASSETS, NO_NAMEPLATE, domain_map, evaluate_asset, missing_value,
    resolve_fields, summarize_assets,
)


class AssetQualityTests(unittest.TestCase):
    def test_asset_sources_exclude_other_device_types(self):
        self.assertEqual(ASSETS["transformer"]["layer_id"], 7)
        self.assertEqual(ASSETS["transformer"]["asset_group"], 12)
        self.assertEqual(sorted(ASSETS["transformer"]["types"]), [1,2,3,4,5,6])
        self.assertEqual(ASSETS["pole"]["layer_id"], 12)
        self.assertEqual(ASSETS["pole"]["asset_group"], 7)
        self.assertEqual(sorted(ASSETS["pole"]["types"]), [1,2,3])

    def test_branch_is_not_checked(self):
        self.assertNotIn("branch", ASSETS["transformer"]["checks"])
        mapping = resolve_fields([
            {"name":"Transfomer_name_"}, {"name":"Branch"},
            {"name":"Manufacturer"}, {"name":"Serial_No"}, {"name":"Phases"},
            {"name":"Rated_kVA"}], "transformer")
        result = evaluate_asset({
            "ASSETGROUP": 12, "ASSETTYPE": 4, "GLOBALID": "{G1}",
            "OBJECTID": 1, "Transfomer_name_": "TR-1", "Branch": None,
            "Manufacturer": "ABB", "Serial_No": "1234",
            "Phases": 3, "Rated_kVA": 100,
        }, "transformer", mapping)
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["status"], "NO_GAPS_FOUND")

    def test_live_field_name_aliases_are_not_guessed(self):
        mapping = resolve_fields([{"name":"Manufacturer"},{"name":"Notes"}], "transformer")
        self.assertIsNone(mapping["name"])
        result = evaluate_asset({
            "ASSETGROUP":12,"ASSETTYPE":4,"GLOBALID":"G1",
            "Manufacturer":"ABB","Notes":"good",
        }, "transformer", mapping)
        self.assertEqual(result["status"], "NOT_VERIFIED")
        self.assertIn("name", result["unverified_checks"])

    def test_missing_manufacturer_must_have_specific_nameplate_note(self):
        mapping = {"manufacturer":"Manufacturer", "notes":"Notes"}
        for note in ("", "N/A", "Manufacturer unknown", "Pole inspected"):
            result = evaluate_asset({
                "ASSETGROUP":7, "ASSETTYPE":1, "GLOBALID":"P1",
                "Manufacturer":None, "Notes":note,
            }, "pole", mapping)
            self.assertEqual(result["status"], "GAP", note)
            self.assertIn("Manufacturer missing: Notes must state no name plate",
                          result["issues"])
        for note in ("there is no name plate", "Nameplate missing",
                     "No nameplate found"):
            result = evaluate_asset({
                "ASSETGROUP":7, "ASSETTYPE":3, "GLOBALID":"P2",
                "Manufacturer":None, "Notes":note,
            }, "pole", mapping)
            self.assertEqual(result["status"], "NO_GAPS_FOUND")
            self.assertEqual(result["values"]["manufacturer_status"],
                             "DOCUMENTED_NO_NAMEPLATE")

    def test_absent_notes_field_blocks_complete_result(self):
        result = evaluate_asset({
            "ASSETGROUP":7, "ASSETTYPE":2, "GLOBALID":"P3",
            "Manufacturer":None,
        }, "pole", {"manufacturer":"Manufacturer", "notes":None})
        self.assertEqual(result["status"], "GAP")
        self.assertIn("notes", result["unverified_checks"])

    def test_zero_phase_code_is_valid_when_domain_label_one(self):
        self.assertFalse(missing_value(0, {0:"1 phase", 1:"3 phases"}))
        self.assertTrue(missing_value(0, {0:"Unknown", 1:"3 phases"}))
        mapping = {"name":"Transfomer_name_", "manufacturer":"Manufacturer",
                   "serial":"Serial_No", "phases":"Phases", "capacity":"Rated_kVA"}
        result = evaluate_asset({
            "ASSETGROUP":12, "ASSETTYPE":4, "GLOBALID":"T",
            "Transfomer_name_":"TR", "Manufacturer":"ABB", "Serial_No":"A3",
            "Phases":0, "Rated_kVA":100
        }, "transformer", mapping, {"Phases":{0:"1 phase", 2:"3 phases"}})
        self.assertEqual(result["status"], "NO_GAPS_FOUND")

    def test_unknown_asset_type_is_gap_not_false_coverage(self):
        result = evaluate_asset({
            "ASSETGROUP":12,"ASSETTYPE":0,"GLOBALID":"G3",
        }, "transformer", {})
        self.assertIn("Unknown or unsupported asset type", result["issues"])

    def test_cross_asset_group_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_asset({"ASSETGROUP":1}, "transformer", {})

    def test_unique_feature_summary_counts_issues_separately(self):
        row = evaluate_asset({
            "ASSETGROUP":7, "ASSETTYPE":1, "GLOBALID":"P1",
            "Manufacturer":None,"Notes":""
        },"pole", {"manufacturer":"Manufacturer", "notes":"Notes"})
        counters = summarize_assets([row, row])
        self.assertEqual(counters["total"], 2)
        self.assertEqual(counters["with_gaps"], 2)
        self.assertEqual(counters["issue_count"], 2)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from meter_photo_qa.quality_watcher import (
    assess_line_quality,
    build_quality_where,
    load_quality_rules,
)


DOMAINS = {
    9: {
        "Voltage_Level_kV": {0: "select value", 1: "400", 2: "242", 3: "230"},
        "CondustorSize": {0: "Unknown", 1: "2*16mm2"},
        "Material": {0: "Unknown", 4: "Aluminium"},
        "ConductorInsulation": {0: "No", 1: "Yes"},
        "Phases": {0: "1", 1: "2", 2: "3"},
        "SupplyingLines": {0: "Unknown", 1: "Residential"},
    }
}


def typical_attributes():
    return {
        "ASSETGROUP": 9,
        "Transformer_Name": "Transformer A",
        "LV_Feeder_Name": None,
        "Voltage_Level_kV": 1,
        "CondustorSize": 1,
        "Material": 4,
        "Rated_Current": 135.0,
        "ConductorInsulation": 0,
        "Phases": 0,
        "SupplyingLines": 0,
        "Year_construction": None,
        "Year_of_commisioning": None,
    }


class QualityWatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_quality_rules()

    def test_typical_eight_of_eleven_fields_passes(self):
        result = assess_line_quality(
            typical_attributes(), self.rules, DOMAINS, 60, current_year=2026
        )
        self.assertEqual(result["completed_fields"], 8)
        self.assertEqual(result["required_fields"], 11)
        self.assertAlmostEqual(result["completion_percent"], 72.7272727)
        self.assertEqual(result["status"], "MEETS_THRESHOLD")

    def test_transformer_name_is_mandatory_even_above_threshold(self):
        attributes = typical_attributes()
        attributes["Transformer_Name"] = None
        attributes["SupplyingLines"] = 1
        attributes["Year_construction"] = 2025
        attributes["Year_of_commisioning"] = 2026
        result = assess_line_quality(attributes, self.rules, DOMAINS, 60, current_year=2026)
        self.assertEqual(result["completed_fields"], 10)
        self.assertEqual(result["status"], "FLAG")
        self.assertEqual(result["mandatory_failures"], ["Transformer Name"])

    def test_two_more_missing_fields_drop_below_threshold(self):
        attributes = typical_attributes()
        attributes["Transformer_Name"] = None
        attributes["Rated_Current"] = None
        result = assess_line_quality(
            attributes, self.rules, DOMAINS, 60, current_year=2026
        )
        self.assertEqual(result["completed_fields"], 6)
        self.assertEqual(result["status"], "FLAG")

    def test_lv_feeder_name_is_optional(self):
        result = assess_line_quality(
            typical_attributes(), self.rules, DOMAINS, 60, current_year=2026
        )
        self.assertNotIn("lv_feeder_name", {item["key"] for item in result["checks"]})
        self.assertNotIn("LV Feeder Name", result["missing_attributes"])
        self.assertIn("lv_feeder_name", result["display_values"])

    def test_zero_is_valid_for_no_insulation_and_one_phase(self):
        result = assess_line_quality(
            typical_attributes(), self.rules, DOMAINS, 60, current_year=2026
        )
        check_by_key = {item["key"]: item for item in result["checks"]}
        self.assertTrue(check_by_key["conductor_insulation"]["valid"])
        self.assertTrue(check_by_key["phases"]["valid"])
        self.assertFalse(check_by_key["supplying_lines"]["valid"])

    def test_commissioning_before_construction_is_invalid(self):
        attributes = typical_attributes()
        attributes["LV_Feeder_Name"] = "Feeder A"
        attributes["SupplyingLines"] = 1
        attributes["Year_construction"] = 2025
        attributes["Year_of_commisioning"] = 2024
        result = assess_line_quality(
            attributes, self.rules, DOMAINS, 60, current_year=2026
        )
        self.assertTrue(any("Year of Commissioning" in text for text in result["invalid_attributes"]))

    def test_fractional_year_is_invalid(self):
        attributes = typical_attributes()
        attributes["Year_construction"] = 2025.9
        result = assess_line_quality(attributes, self.rules, DOMAINS, 60, current_year=2026)
        self.assertTrue(any("Year of Construction" in text for text in result["invalid_attributes"]))

    def test_where_uses_inclusive_end_date(self):
        where = build_quality_where("2026-07-01", "2026-07-15", ["alpha"])
        self.assertIn("created_date < TIMESTAMP '2026-07-16 00:00:00'", where)
        self.assertIn("last_edited_date < TIMESTAMP '2026-07-16 00:00:00'", where)
        self.assertIn("created_user IN ('alpha')", where)

    def test_all_user_query_does_not_hide_unattributed_lines(self):
        where = build_quality_where("2026-07-01", "2026-07-15")
        self.assertNotIn("created_user IS NOT NULL", where)


if __name__ == "__main__":
    unittest.main()

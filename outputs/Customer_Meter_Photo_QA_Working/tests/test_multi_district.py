from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meter_photo_qa.area_selection import district_filters, selected_districts
from meter_photo_qa.progress_report import _get_sector_features, build_report_title


class MultiDistrictTests(unittest.TestCase):
    def test_one_district_backward_compatible(self):
        statement = district_filters("Gasabo", ["Remera"], ["Rukiri I"])
        self.assertIn("UPPER(district) = 'GASABO'", statement)
        self.assertIn("UPPER(sector) = 'REMERA'", statement)
        self.assertIn("UPPER(cell) = 'RUKIRI I'", statement)

    def test_two_districts_without_sector_filter(self):
        statement = district_filters(["Burera", "Rulindo"])
        self.assertIn("UPPER(district) IN ('BURERA', 'RULINDO')", statement)
        self.assertNotIn("UPPER(sector)", statement)

    def test_compound_district_string(self):
        self.assertEqual(selected_districts("Burera;Rulindo;burera"), ["Burera", "Rulindo"])

    def test_duplicate_sector_names_do_not_expand_to_wrong_district(self):
        statement = district_filters(
            ["Burera", "Rulindo"],
            ["Burera :: Rugarama"],
        )
        self.assertIn("UPPER(district) = 'BURERA'", statement)
        self.assertIn("UPPER(sector) = 'RUGARAMA'", statement)
        self.assertNotIn("'RULINDO'", statement)

    def test_multi_district_plain_sector_rejected(self):
        with self.assertRaisesRegex(ValueError, "sectors must"):
            district_filters(["Burera", "Rulindo"], ["Rugarama"])

    def test_multi_district_cell_is_qualified(self):
        statement = district_filters(
            ["Burera", "Rulindo"],
            ["Burera :: Rugarama", "Rulindo :: Buyoga"],
            ["Burera :: Rugarama :: Nyagatare"],
        )
        self.assertIn("'BURERA'", statement)
        self.assertIn("'NYAGATARE'", statement)
        self.assertNotIn("'BUYOGA'", statement)

    def test_cell_outside_selected_sector_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside the selected sectors"):
            district_filters(
                ["Burera", "Rulindo"],
                ["Burera :: Rugarama"],
                ["Rulindo :: Buyoga :: Example"],
            )

    def test_injected_quote_is_safely_escaped(self):
        statement = district_filters(["O'Brien", "Burera"])
        self.assertIn("'O''BRIEN'", statement)

    def test_sector_without_district_rejected(self):
        with self.assertRaises(ValueError):
            district_filters([], ["Rugarama"])

    def test_all_districts_when_empty_selection(self):
        self.assertIsNone(district_filters(None))

    def test_multi_district_title(self):
        title = build_report_title("2026-10-01", "2026-10-13", ["Burera", "Rulindo"])
        self.assertIn("BURERA and RULINDO DISTRICTS: All Sectors", title)

    def test_actual_boundary_query_uses_union(self):
        feature_set = SimpleNamespace(features=[SimpleNamespace(geometry={"rings": []})],
                                      spatial_reference={"wkid": 4326})
        with patch("meter_photo_qa.progress_report._query_with_retry",
                   return_value=feature_set) as query:
            result = _get_sector_features(object(), ["Burera", "Rulindo"], None)
        self.assertIs(result, feature_set)
        where = query.call_args.kwargs["where"]
        self.assertIn("'BURERA'", where)
        self.assertIn("'RULINDO'", where)
        self.assertTrue(query.call_args.kwargs["return_all_records"])

    def test_qualified_sector_query_filters_single_selected_area(self):
        feature_set = SimpleNamespace(features=[SimpleNamespace(geometry={"rings": []})])
        with patch("meter_photo_qa.progress_report._query_with_retry",
                   return_value=feature_set) as query:
            _get_sector_features(object(), ["Burera", "Rulindo"], ["Burera :: Rugarama"])
        where = query.call_args.kwargs["where"]
        self.assertIn("'BURERA'", where)
        self.assertNotIn("'RULINDO'", where)


if __name__ == "__main__":
    unittest.main()

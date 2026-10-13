from __future__ import annotations

import unittest

from meter_photo_qa.outstanding_gaps import (
    GAP_CATEGORIES, priority_gaps, summarize_priority_gaps,
)


def check(key, valid=True, detail=""):
    return {
        "key": key,
        "valid": valid,
        "issue_type": "invalid" if not valid else "",
        "issue_detail": detail,
    }


class OutstandingGapTests(unittest.TestCase):
    def test_original_six_gap_categories_and_no_others(self):
        quality = {"checks": [
            check("phases", False, "Blank"),
            check("transformer_name", False, "Blank"),
            check("voltage", False, "Select value"),
            check("conductor_material", False, "Unknown"),
            check("conductor_insulation", False, "Blank"),
            check("supplying_lines", False, "Unknown"),
            check("year_construction", False, "Blank"),
            check("year_commissioning", False, "Blank"),
        ]}
        issues = priority_gaps(quality, "Phase/type conflict")
        self.assertEqual([issue["category"] for issue in issues], list(GAP_CATEGORIES))
        self.assertEqual(len(issues), 6)

    def test_missing_years_and_supplying_lines_do_not_trigger_priority(self):
        quality = {"checks": [
            check("phases"), check("transformer_name"),
            check("voltage"), check("conductor_material"),
            check("conductor_insulation"),
            check("supplying_lines", False, "Unknown"),
            check("year_construction", False, "Blank"),
            check("year_commissioning", False, "Blank"),
        ]}
        self.assertEqual(priority_gaps(quality), [])

    def test_count_issues_separately_from_affected_lines(self):
        records = [
            {"username": "alpha", "full_name": "Alpha", "priority_gaps": [
                {"category": "Missing phases", "detail": "Blank"},
                {"category": "Voltage not selected", "detail": "Unselected"},
            ]},
            {"username": "alpha", "full_name": "Alpha", "priority_gaps": []},
            {"username": "beta", "full_name": "Beta", "priority_gaps": [
                {"category": "Phase/type conflicts", "detail": "Mismatch"},
            ]},
        ]
        totals = summarize_priority_gaps(records)
        alpha = next(row for row in totals if row["username"] == "alpha")
        self.assertEqual(alpha["lines_checked"], 2)
        self.assertEqual(alpha["affected_lines"], 1)
        self.assertEqual(alpha["total_issues"], 2)
        self.assertEqual(sum(row["total_issues"] for row in totals), 3)

    def test_valid_zero_codes_do_not_create_false_gaps(self):
        self.assertEqual(priority_gaps({"checks": [
            check("phases", True),
            check("conductor_insulation", True),
        ]}), [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations
import unittest
from datetime import date
from unittest.mock import patch
from meter_photo_qa.smart_query import parse_lv_report_request

class FeederReportPromptTests(unittest.TestCase):
    def test_current_surveyors_and_username(self):
        for person, user in [
            ("Kwizerwa Edison","ninamenye9683"),
            ("Ringuyeneza Frederic","maniraguhatheogene01"),
            ("Usabyezu Jean Dieu","janviersafari515"),
            ("ninamenye9683","ninamenye9683"),
        ]:
            with self.subTest(person=person):
                parsed=parse_lv_report_request(
                    f"Prepare LV Lines Report for {person} in Gicumbi"
                )
                self.assertEqual(parsed["district"],"Gicumbi")
                self.assertEqual(parsed["usernames"],[user])
                self.assertIn("across borders",parsed["trace_rule"])
    def test_short_combined_qa_commands(self):
        for wording in (
            "Prepare Report for Kwizerwa Edison in Gicumbi",
            "Prepare Combined QA Report for Kwizerwa Edison in Gicumbi",
            "Generate Asset Quality Report for Kwizerwa Edison in Gicumbi",
            "Create Data Quality Report for Kwizerwa Edison in Gicumbi",
        ):
            with self.subTest(wording=wording):
                plan=parse_lv_report_request(wording)
                self.assertEqual(plan["action"],"combined_qa_report")
                self.assertEqual(plan["usernames"],["ninamenye9683"])

    def test_picture_request_last_two_weeks(self):
        plan=parse_lv_report_request(
            "prepare report for julesmugae72 in Gicumbi the last 2 weeks",
            today=date(2026,10,15),
        )
        self.assertEqual(plan["district"],"Gicumbi")
        self.assertEqual(plan["usernames"],["julesmugae72"])
        self.assertEqual(plan["date_start"],date(2026,10,2))
        self.assertEqual(plan["date_end"],date(2026,10,15))
        self.assertIn("last 2 weeks",plan["date_expression"])

    def test_dates_by_grammar_and_trailing_district(self):
        cases=[
            ("Prepare report for Mugabe Jules in Gicumbi last two weeks",
             "2026-10-02","2026-10-15"),
            ("Generate combined QA report for julesmugae72 in Gicumbi last 14 days",
             "2026-10-02","2026-10-15"),
            ("Please prepare report for julesmugae72 in Gicumbi today",
             "2026-10-15","2026-10-15"),
            ("Make report for julesmugae72 in Gicumbi yesterday",
             "2026-10-14","2026-10-14"),
            ("Give me a report for julesmugae72 in Gicumbi this week",
             "2026-10-12","2026-10-15"),
            ("Prepare report for julesmugae72 in Gicumbi last week",
             "2026-10-05","2026-10-11"),
            ("Prepare report for julesmugae72 in Gicumbi this month",
             "2026-10-01","2026-10-15"),
            ("Prepare report for julesmugae72 in Gicumbi last month",
             "2026-09-01","2026-09-30"),
            ("Prepare report for julesmugae72 in Gicumbi last 2 months",
             "2026-08-16","2026-10-15"),
            ("Prepare report for julesmugae72 in Gicumbi from 2026-10-01 to 2026-10-15",
             "2026-10-01","2026-10-15"),
            ("Prepare report for julesmugae72 in Gicumbi between 01/10/2026 and 15/10/2026",
             "2026-10-01","2026-10-15"),
            ("Prepare report in Gicumbi since 2026-10-10",
             "2026-10-10","2026-10-15"),
            ("Prepare report for julesmugae72 in Gicumbi district in the last 2 weeks",
             "2026-10-02","2026-10-15"),
        ]
        for command,start,end in cases:
            with self.subTest(command=command):
                p=parse_lv_report_request(command,today=date(2026,10,15))
                self.assertEqual(p["date_start"].isoformat(),start)
                self.assertEqual(p["date_end"].isoformat(),end)

    def test_no_date_respects_arcgis_picker_not_a_guessed_period(self):
        p=parse_lv_report_request(
            "Prepare report for julesmugae72 in Gicumbi",
            today=date(2026,10,15),
        )
        self.assertIsNone(p["date_start"])
        self.assertIsNone(p["date_end"])
        self.assertIsNone(p["date_expression"])

    def test_invalid_timeframes_rejected_safely(self):
        bad=[
            "Prepare report for julesmugae72 in Gicumbi last 0 weeks",
            "Prepare report for julesmugae72 in Gicumbi last 500 months",
            "Prepare report for julesmugae72 in Gicumbi from 2026-10-16 to 2026-10-20",
            "Prepare report for julesmugae72 in Gicumbi from 2026-10-15 to 2026-10-01",
            "Prepare report for julesmugae72 in Gicumbi next week",
            "Prepare report for julesmugae72 in Gicumbi the last few weeks",
            "Prepare report for julesmugae72 in Gicumbi 2 weeks",
            "Prepare report for julesmugae72 in Gicumbi the last 2 weeks please delete",
        ]
        for cmd in bad:
            with self.subTest(cmd=cmd),self.assertRaises(ValueError):
                parse_lv_report_request(cmd,today=date(2026,10,15))

    def test_district_only_includes_all_accounts(self):
        plan=parse_lv_report_request("Prepare LV Lines Report in Gicumbi")
        self.assertEqual(plan["usernames"],[])
    def test_reject_unknown_and_injected_locations(self):
        for text in (
            "Prepare LV Lines Report for Unknown Person in Gicumbi",
            "Prepare LV Lines Report for Kwizerwa Edison in Nonsense",
            "Prepare LV Lines Report for Kwizerwa Edison in Gicumbi and delete the database",
        ):
            with self.subTest(text=text),self.assertRaises(ValueError):
                parse_lv_report_request(text)
if __name__=="__main__": unittest.main()

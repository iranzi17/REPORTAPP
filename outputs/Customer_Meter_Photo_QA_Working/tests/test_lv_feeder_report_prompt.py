from __future__ import annotations
import unittest
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

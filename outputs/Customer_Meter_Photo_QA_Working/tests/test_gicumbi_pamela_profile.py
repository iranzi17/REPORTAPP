from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meter_photo_qa.gicumbi_pamela_profile import (
    _brief_asset_result,
    load_pamela_profile,
    run_gicumbi_pamela_profile,
)


class GicumbiPamelaProfileTests(unittest.TestCase):
    def test_profile_is_exactly_six_sectors_and_twelve_people(self):
        data, users, unknown = load_pamela_profile()
        self.assertEqual(data["district"], "Gicumbi")
        self.assertEqual(data["senior_supervisor"], "Pamela")
        self.assertEqual(data["field_supervisor"], "Derrick")
        self.assertEqual(
            [entry["sector"] for entry in data["sectors"]],
            ["Muko", "Mutete", "Nyamiyaga", "Nyankenke", "Rukomo", "Rushaki"],
        )
        self.assertEqual(sum(len(s["cells"]) for s in data["sectors"]), 32)
        self.assertEqual(sum(s["planned_transformers"] for s in data["sectors"]), 95)
        self.assertEqual(sum(len(s["surveyors"]) for s in data["sectors"]), 12)
        self.assertEqual(len(users), 12)
        self.assertEqual(unknown, [])
        self.assertEqual(data["staff_replacements"][0]["incoming"],"Kwizerwa Edison")
        self.assertEqual(data["staff_replacements"][0]["outgoing"],"Manzi Intime")
        edison = next(person for sector in data["sectors"]
                      for person in sector["surveyors"]
                      if person["name_in_plan"] == "Kwizerwa Edison")
        self.assertEqual(edison["replaces"], "Manzi Intime")
        self.assertEqual(edison["username"], "maniraguhatheogene01")
        self.assertEqual(edison["mapped_full_name"], "Kwizerwa Edison")
        self.assertIn("maniraguhatheogene01", users)
        self.assertIsNone(data["staff_replacements"][0]["handover_date"])
        self.assertIn("martinnzubahimana", users)
        self.assertIn("julesmugae72", users)
        self.assertIn("thomascyiza", users)
        self.assertNotIn("REGUN_Prod", users)

    def test_profile_roster_does_not_assign_people_to_individual_cells(self):
        data,_,_=load_pamela_profile()
        names={s["sector"]:len(s["surveyors"]) for s in data["sectors"]}
        self.assertEqual(names, {
            "Muko":1,"Mutete":2,"Nyamiyaga":1,
            "Nyankenke":1,"Rukomo":3,"Rushaki":4,
        })
        self.assertTrue(all("cell" not in person
                            for sector in data["sectors"]
                            for person in sector["surveyors"]))

    def test_mapping_must_match_local_portal_name_source(self):
        data, users, _ = load_pamela_profile()
        mapped_path=Path(__file__).resolve().parents[1]/"config/report_user_names.json"
        names=json.loads(mapped_path.read_text(encoding="utf-8"))
        del names["julesmugae72"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            broken=Path(folder)/"user_names.json"
            broken.write_text(json.dumps(names),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Cannot confirm portal username"):
                load_pamela_profile(user_map_path=broken)

    def test_default_runs_three_assets_with_same_sector_and_account_filters(self):
        _,users,_=load_pamela_profile()
        calls=[]
        def asset_fake(**kwargs):
            calls.append((kwargs["asset"],kwargs))
            return {
                "output_xlsx":str(kwargs["output_xlsx"]),
                "total":5,"with_gaps":2,"issue_count":3,
                "per_surveyor":[
                    {"username":users[0],"total":3,"with_gaps":1},
                    {"username":"unmapped_user","total":2,"with_gaps":1},
                ],
            }
        def line_fake(**kwargs):
            calls.append(("lv_line",kwargs))
            return {
                "output_xlsx":str(kwargs["output_xlsx"]),
                "total_lines":9,"outstanding_lv_lines":2,"outstanding_lv_issues":3,
                "user_summary":[
                    {"username":users[1],"total_lines":7,"flagged_lines":1},
                ],
            }
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, \
             patch("meter_photo_qa.gicumbi_pamela_profile.run_asset_quality",side_effect=asset_fake), \
             patch("meter_photo_qa.gicumbi_pamela_profile.run_quality_watcher",side_effect=line_fake):
            result=run_gicumbi_pamela_profile(
                folder,"2026-09-14","2026-10-13",
            )
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["completed_assets"], ["pole","transformer","lv_line"])
            self.assertEqual([a for a,_ in calls], ["pole","transformer","lv_line"])
            for asset, kwargs in calls:
                self.assertEqual(kwargs["district"], "Gicumbi")
                self.assertEqual(kwargs["sectors"],
                    ["Muko","Mutete","Nyamiyaga","Nyankenke","Rukomo","Rushaki"])
                self.assertEqual(sorted(kwargs["usernames"]),users)
                self.assertEqual(kwargs["start_date"].isoformat(),"2026-09-14")
                self.assertEqual(kwargs["end_date"].isoformat(),"2026-10-13")
                if asset=="lv_line":
                    self.assertIsNone(kwargs["output_flagged_feature_class"])
            manifest=json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"],"COMPLETE")
            self.assertEqual(manifest["planned_transformer_total"],95)
            self.assertEqual(manifest["reports"][0]["known_roster_records"],3)
            self.assertEqual(manifest["reports"][0]["other_or_unmapped_records"],2)
            self.assertEqual(manifest["reports"][0]["by_surveyor"][1]["profile_membership"],
                             "UNMAPPED_OR_OTHER_ACCOUNT_IN_AREA")
            self.assertEqual(manifest["unresolved_planned_surveyors"], [])
            self.assertEqual(manifest["verified_usernames"], users)
            self.assertEqual(manifest["transferred_accounts_need_historical_review"], ["maniraguhatheogene01"])
            self.assertEqual(manifest["account_transfers"][0]["incoming"], "Kwizerwa Edison")
            with open(result["roster_csv"],newline="",encoding="utf-8-sig") as fh:
                roster=list(csv.DictReader(fh))
            self.assertEqual(len(roster),12)
            self.assertEqual(sum(r["Mapping Status"].startswith("UNMAPPED")
                                 for r in roster),0)
            record=next(item for item in roster
                        if item["Planned Surveyor"]=="Kwizerwa Edison")
            self.assertEqual(record["Replaces"],"Manzi Intime")
            self.assertEqual(record["Portal Username"],"maniraguhatheogene01")
            self.assertIn("ACCOUNT HOLDER",record["Mapping Status"])
            self.assertIn("confirmed account transfer",record["Staffing Change Note"].casefold())

    def test_all_accounts_mode_must_not_label_outside_username_as_team(self):
        calls=[]
        def fake(**kwargs):
            calls.append(kwargs)
            return {
                "output_xlsx":"test.xlsx","total":2,"with_gaps":1,
                "per_surveyor":[{"username":"another.user","total":2,"with_gaps":1}],
            }
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, \
             patch("meter_photo_qa.gicumbi_pamela_profile.run_asset_quality",side_effect=fake):
            result=run_gicumbi_pamela_profile(
                folder,"2026-09-14","2026-10-13",
                assets="pole",scope="all_in_assigned_sectors",
            )
            self.assertIsNone(calls[0]["usernames"])
            report=result["reports"][0]
            self.assertEqual(report["other_or_unmapped_records"],2)
            self.assertEqual(report["by_surveyor"][0]["profile_membership"],
                             "UNMAPPED_OR_OTHER_ACCOUNT_IN_AREA")

    def test_transferred_username_is_team_member_but_historical_authorship_unproven(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, \\
             patch("meter_photo_qa.gicumbi_pamela_profile.run_asset_quality",
                   return_value={
                       "output_xlsx":"report.xlsx","total":1,"with_gaps":1,
                       "per_surveyor":[{
                           "username":"maniraguhatheogene01","total":1,"with_gaps":1,
                       }],
                   }):
            result=run_gicumbi_pamela_profile(
                folder,"2026-09-14","2026-10-13",assets="pole",
            )
            manifest=json.loads(Path(result["manifest_json"]).read_text())
            self.assertEqual(manifest["unresolved_planned_surveyors"],[])
            self.assertEqual(len(manifest["verified_usernames"]),12)
            self.assertEqual(
                manifest["reports"][0]["by_surveyor"][0]["profile_membership"],
                "KNOWN_PAMELA_ACCOUNT",
            )
            self.assertIn(
                "ACCOUNT_TRANSFER_DATE_UNKNOWN",
                manifest["reports"][0]["by_surveyor"][0]["historical_attribution"],
            )
            with open(result["roster_csv"],newline="",encoding="utf-8-sig") as fh:
                rows=list(csv.DictReader(fh))
            edison=next(r for r in rows if r["Planned Surveyor"]=="Kwizerwa Edison")
            self.assertEqual(edison["Portal Username"],"maniraguhatheogene01")
            self.assertEqual(edison["Replaces"],"Manzi Intime")

    def test_failure_writes_incomplete_manifest_and_preserves_roster(self):
        def fails(**kwargs):
            raise RuntimeError("ArcGIS Server 503")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, \
             patch("meter_photo_qa.gicumbi_pamela_profile.run_asset_quality",side_effect=fails):
            with self.assertRaisesRegex(RuntimeError,"INCOMPLETE|stopped at pole"):
                run_gicumbi_pamela_profile(
                    folder,"2026-09-14","2026-10-13",assets="pole",
                )
            dirs=list(Path(folder).glob("Gicumbi_Pamela_*"))
            self.assertEqual(len(dirs),1)
            manifest=json.loads((dirs[0]/"Pamela_Review_Manifest.json").read_text())
            self.assertEqual(manifest["status"],"INCOMPLETE")
            self.assertEqual(manifest["failed_asset"],"pole")
            self.assertTrue((dirs[0]/"Pamela_Team_Roster.csv").exists())


if __name__ == "__main__":
    unittest.main()

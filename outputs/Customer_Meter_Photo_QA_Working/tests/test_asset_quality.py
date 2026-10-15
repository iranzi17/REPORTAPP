from __future__ import annotations
import unittest
from meter_photo_qa.asset_quality import (
    ASSETS, NO_NAMEPLATE, domain_map, evaluate_asset as evaluate_asset_raw, missing_value,
    resolve_fields, summarize_assets,
)


# Existing tests focus on individual legacy rules and supply valid values for
# the four newly mandatory fields. Dedicated tests below invoke the raw engine.
EXTRA_POLE_FIELDS = {
    "service_pole":"Service_Pole", "structure":"PoleStructure",
    "insulator_type":"InsulatorTypes", "number_of_circuit":"Number_Circuit",
}
EXTRA_POLE_VALUES = {
    "Service_Pole":"No", "PoleStructure":1, "InsulatorTypes":1,
    "Number_Circuit":1,
}


def evaluate_asset(attributes, asset, mapping, domains=None):
    if asset == "pole":
        mapping = dict(mapping)
        for key, name in EXTRA_POLE_FIELDS.items():
            if not mapping.get(key):
                mapping[key] = name
        attributes = {**EXTRA_POLE_VALUES, **attributes}
    return evaluate_asset_raw(attributes, asset, mapping, domains)


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
        live_fields = [
            {"name":"Transfomer_name_"}, {"name":"Branch"},
            {"name":"Owner_Name"}, {"name":"Type_of_Installation"},
            {"name":"Phase_Normal"}, {"name":"Transformer_Protection_Switch"},
            {"name":"Transformer_mounting_support"},
            {"name":"Number_of_Low_Voltage_feeders"},
        ]
        mapping = resolve_fields(live_fields, "transformer")
        result = evaluate_asset({
            "ASSETGROUP": 12, "ASSETTYPE": 4, "GLOBALID": "{G1}",
            "OBJECTID": 1, "Transfomer_name_": "TR-1", "Branch": None,
            "Owner_Name": "REG", "Type_of_Installation": "Outdoor",
            "Phase_Normal": 3, "Transformer_Protection_Switch": "DropOut",
            "Transformer_mounting_support": "PH Concrete",
            "Number_of_Low_Voltage_feeders": 2,
        }, "transformer", mapping)
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["status"], "NO_GAPS_FOUND")
        self.assertNotIn("branch", result["unverified_checks"])

    def test_live_field_name_aliases_are_not_guessed(self):
        mapping = resolve_fields([{"name":"Manufacturer"},{"name":"Notes"}], "transformer")
        self.assertIsNone(mapping["name"])
        result = evaluate_asset({
            "ASSETGROUP":12,"ASSETTYPE":4,"GLOBALID":"G1",
            "Manufacturer":"ABB","Notes":"good",
        }, "transformer", mapping)
        self.assertEqual(result["status"], "NOT_VERIFIED")
        self.assertIn("name", result["unverified_checks"])

    def test_substandard_structure_exempts_manufacturer_even_without_notes(self):
        from meter_photo_qa.asset_quality import is_substandard_pole_structure
        mapping={
            "manufacturer":"Manufacturers","notes":"Notes",
            "append_cable":"Append_Cable","height":"Pole_Height",
            **EXTRA_POLE_FIELDS,
        }
        original={
            "ASSETGROUP":7,"ASSETTYPE":2,"GLOBALID":"{P77}",
            "Manufacturers":None,"Notes":"","Append_Cable":"No",
            "Pole_Height":10,**EXTRA_POLE_VALUES,
        }
        examples=(
            ("Substandard",{},True),
            (" subSTANDARD ",{},True),
            (7,{"PoleStructure":{7:"Substandard",8:"Standard"}},True),
            ("7",{"PoleStructure":{7:"Substandard",8:"Standard"}},True),
            (0,{"PoleStructure":{0:"Substandard",1:"Standard"}},True),
            (8,{"PoleStructure":{7:"Substandard",8:"Standard"}},False),
            ("Standard",{},False),
            ("Unknown",{},False),
            (None,{},False),
            (7,{},False),
            ("Not Substandard",{},False),
        )
        for raw,domain,exempt in examples:
            with self.subTest(raw=raw,domain=domain):
                self.assertEqual(is_substandard_pole_structure(
                    raw,domain.get("PoleStructure")),exempt)
                row=dict(original,PoleStructure=raw)
                result=evaluate_asset_raw(row,"pole",mapping,domain)
                flagged=any("Manufacturer missing" in issue for issue in result["issues"])
                self.assertEqual(flagged,not exempt)
                if exempt:
                    self.assertEqual(
                        result["values"]["manufacturer_status"],"SUBSTANDARD_EXEMPT"
                    )
                    self.assertEqual(result["status"],"NO_GAPS_FOUND")
        # Substandard does not excuse Append Cable or other pole deficiencies.
        row=dict(original,PoleStructure="Substandard",Append_Cable=None,
                 InsulatorTypes=None,Number_Circuit=0)
        result=evaluate_asset_raw(row,"pole",mapping)
        self.assertEqual(result["values"]["manufacturer_status"],"SUBSTANDARD_EXEMPT")
        self.assertEqual(len(result["issues"]),3)
        self.assertTrue(any("Append Cable" in issue for issue in result["issues"]))
        self.assertTrue(any("Insulator Type" in issue for issue in result["issues"]))
        self.assertTrue(any("Number of Circuit" in issue for issue in result["issues"]))

    def test_missing_manufacturer_flag_only_if_notes_empty(self):
        mapping = {"manufacturer":"Manufacturer", "notes":"Notes",
                   "append_cable":"Append_Cable", "height":"Pole_Height"}
        for note in ("", "  ", None):
            result=evaluate_asset({
                "ASSETGROUP":7, "ASSETTYPE":1, "GLOBALID":"P1",
                "Manufacturer":None, "Notes":note, "Append_Cable":"No",
                "Pole_Height":10,
            },"pole",mapping)
            self.assertEqual(result["status"],"GAP")
            self.assertIn("Manufacturer missing and Notes empty",result["issues"])
        for note in ("N/A", "Manufacturer unknown", "Pole inspected",
                     "Name plate is not clear", "No name plate"):
            result=evaluate_asset({
                "ASSETGROUP":7, "ASSETTYPE":1, "GLOBALID":"P2",
                "Manufacturer":None, "Notes":note, "Append_Cable":"No",
                "Pole_Height":10,
            },"pole",mapping)
            self.assertEqual(result["status"],"NO_GAPS_FOUND",note)
            self.assertFalse(any("Manufacturer missing" in issue
                                 for issue in result["issues"]))
            if "No name plate" in note:
                self.assertEqual(result["values"]["manufacturer_status"],
                                 "DOCUMENTED_NO_NAMEPLATE")
            else:
                self.assertEqual(result["values"]["manufacturer_status"],
                                 "NOTES_PRESENT")

    def test_live_reg_pole_schema_uses_plural_manufacturers(self):
        # Actual Structure Junction layer 12 fields verified against the
        # first 66,915-pole QA report.
        fields = [
            {"name": "Manufacturers", "alias": "Manufacturers"},
            {"name": "CountryOfManufacturer", "alias": "Country Of Manufacturer"},
            {"name": "Notes", "alias": "Notes"},
            {"name": "Append_Cable", "alias": "Append Cable"},
            {"name": "Pole_Height", "alias": "Pole Height"},
        ]
        mapping = resolve_fields(fields, "pole")
        self.assertEqual(mapping, {
            "manufacturer": "Manufacturers",
            "notes": "Notes",
            "append_cable": "Append_Cable", "height":"Pole_Height",
            "service_pole": None, "structure": None,
            "insulator_type": None, "number_of_circuit": None,
        })
        for pole_type in (1, 2, 3):
            good = evaluate_asset({
                "GLOBALID": "{POLE}", "OBJECTID": 15,
                "ASSETGROUP": 7, "ASSETTYPE": pole_type,
                "Manufacturers": "Company X", "Notes": "", "Append_Cable": "No", "Pole_Height":10,
            }, "pole", mapping)
            self.assertEqual(good["status"], "NO_GAPS_FOUND")
            self.assertEqual(good["values"]["manufacturer_status"], "RECORDED")

            wrong = evaluate_asset({
                "GLOBALID": "{POLE}", "OBJECTID": 16,
                "ASSETGROUP": 7, "ASSETTYPE": pole_type,
                "Manufacturers": None, "Notes": "Name plate not clear",
                "Append_Cable": "Yes", "Pole_Height":10,
            }, "pole", mapping)
            self.assertEqual(wrong["status"], "NO_GAPS_FOUND")
            self.assertEqual(wrong["values"]["manufacturer_status"], "NOTES_PRESENT")

    def test_kinyarwanda_explicit_absence_of_pole_nameplate(self):
        fields = {"manufacturer": "Manufacturers", "notes": "Notes",
                  "append_cable": "Append_Cable", "height":"Pole_Height"}
        for note in ("Nta name plate iriho", "Nta nameplate iriho",
                     "Nta name plate ifite", "Nta nameplate ifite"):
            with self.subTest(note=note):
                result = evaluate_asset({
                    "GLOBALID": "{POLE}", "OBJECTID": 123,
                    "ASSETGROUP": 7, "ASSETTYPE": 1,
                    "Manufacturers": None, "Notes": note, "Append_Cable":"No", "Pole_Height":10,
                }, "pole", fields)
                self.assertEqual(result["status"], "NO_GAPS_FOUND")
                self.assertEqual(
                    result["values"]["manufacturer_status"],
                    "DOCUMENTED_NO_NAMEPLATE",
                )
        for note in ("Name plate not clear", "Nameplate is not clear",
                     "I could not read the nameplate", "Nta name plate irimo?"):
            result = evaluate_asset({
                "GLOBALID": "{POLE}", "OBJECTID": 124,
                "ASSETGROUP": 7, "ASSETTYPE": 1,
                "Manufacturers": None, "Notes": note, "Append_Cable":"No", "Pole_Height":10,
            }, "pole", fields)
            self.assertEqual(result["status"], "NO_GAPS_FOUND", note)
            self.assertEqual(result["values"]["manufacturer_status"], "NOTES_PRESENT")

    def test_live_pole_mapping_and_four_additional_mandatory_values(self):
        fields=[
            {"name":"Manufacturers"},{"name":"Notes"},{"name":"AppendCable"},
            {"name":"Height"},{"name":"Service_Pole"},{"name":"PoleStructure"},
            {"name":"InsulatorTypes"},{"name":"Number_Circuit"},
        ]
        mapping=resolve_fields(fields,"pole")
        self.assertEqual({k:mapping[k] for k in EXTRA_POLE_FIELDS},EXTRA_POLE_FIELDS)
        complete={
            "GLOBALID":"{POLE}","OBJECTID":150,"ASSETGROUP":7,"ASSETTYPE":2,
            "Manufacturers":"A","Notes":"","AppendCable":"No","Height":11,
            "Service_Pole":0,"PoleStructure":2,"InsulatorTypes":3,
            "Number_Circuit":2,
        }
        good=evaluate_asset_raw(complete,"pole",mapping,{
            "Service_Pole":{0:"No",1:"Yes"}
        })
        self.assertEqual(good["status"],"NO_GAPS_FOUND")
        self.assertEqual(good["values"]["service_pole_status"],"RECORDED")
        invalid=dict(complete,Manufacturers=None,Notes="Pole inspected",
                     Service_Pole=None,PoleStructure="Unknown",
                     InsulatorTypes=None,Number_Circuit=0)
        result=evaluate_asset_raw(invalid,"pole",mapping)
        self.assertEqual(result["status"],"GAP")
        self.assertEqual(len(result["issues"]),4)
        self.assertIn("Service Pole missing/unknown (mandatory LV pole field)",result["issues"])
        self.assertIn("Structure missing/unknown (mandatory LV pole field)",result["issues"])
        self.assertIn("Insulator Type missing/unknown (mandatory LV pole field)",result["issues"])
        self.assertIn("Number of Circuit must be a positive whole number",result["issues"])
        self.assertFalse(any("Manufacturer missing" in x for x in result["issues"]))
        missing_map=resolve_fields(fields[:4],"pole")
        incomplete=evaluate_asset_raw(complete,"pole",missing_map)
        self.assertEqual(incomplete["status"],"NOT_VERIFIED")
        for key in EXTRA_POLE_FIELDS:
            self.assertIn(key,incomplete["unverified_checks"])

    def test_append_cable_is_mandatory_even_with_documented_no_nameplate(self):
        fields = resolve_fields([
            {"name":"Manufacturers"}, {"name":"Notes"}, {"name":"Append_Cable"}, {"name":"Pole_Height"}
        ],"pole")
        for raw in (None, "", "Unknown", "N/A"):
            with self.subTest(value=raw):
                pole = evaluate_asset({
                    "OBJECTID":5, "GLOBALID":"{P5}", "ASSETGROUP":7, "ASSETTYPE":1,
                    "Manufacturers":None, "Notes":"No name plate",
                    "Append_Cable":raw, "Pole_Height":10,
                },"pole",fields)
                self.assertEqual(pole["status"],"GAP")
                self.assertIn(
                    "Append Cable missing/unknown (mandatory LV pole field)",
                    pole["issues"],
                )
                self.assertEqual(pole["values"]["manufacturer_status"],
                                 "DOCUMENTED_NO_NAMEPLATE")

    def test_append_cable_yes_and_no_are_valid_answers(self):
        fields = {"manufacturer":"Manufacturers", "notes":"Notes",
                  "append_cable":"Append_Cable", "height":"Pole_Height"}
        for answer in ("Yes", "No", 0, 1):
            with self.subTest(answer=answer):
                value = evaluate_asset({
                    "GLOBALID":"{A}", "OBJECTID":1,
                    "ASSETGROUP":7,"ASSETTYPE":2,
                    "Manufacturers":"ABC", "Notes":"",
                    "Append_Cable":answer, "Pole_Height":10,
                },"pole",fields,{"Append_Cable":{0:"No",1:"Yes"}})
                self.assertEqual(value["status"],"NO_GAPS_FOUND")
                self.assertEqual(value["values"]["append_cable_status"],"RECORDED")
        coded_text = evaluate_asset({
            "GLOBALID":"{A}", "OBJECTID":1,
            "ASSETGROUP":7,"ASSETTYPE":2,
            "Manufacturers":"ABC", "Notes":"",
            "Append_Cable":"0", "Pole_Height":10,
        },"pole",fields,{"Append_Cable":{0:"No",1:"Yes"}})
        self.assertEqual(coded_text["status"],"NO_GAPS_FOUND")
        self.assertEqual(coded_text["values"]["append_cable"],"No")
        ambiguous_zero = evaluate_asset({
            "GLOBALID":"{A}", "OBJECTID":1,
            "ASSETGROUP":7,"ASSETTYPE":2,
            "Manufacturers":"ABC", "Notes":"",
            "Append_Cable":"0", "Pole_Height":10,
        },"pole",fields)
        self.assertEqual(ambiguous_zero["status"],"GAP")

    def test_append_cable_code_unknown_and_missing_schema_cannot_pass(self):
        mapping=resolve_fields([
            {"name":"Manufacturers"}, {"name":"Notes"}, {"name":"Append Cable"}
        ],"pole")
        self.assertEqual(mapping["append_cable"],"Append Cable")
        unknown=evaluate_asset({
            "GLOBALID":"{P}", "OBJECTID":1,"ASSETGROUP":7,"ASSETTYPE":1,
            "Manufacturers":"ABC","Notes":"",
            "Append Cable":0, "Pole_Height":10,
        },"pole",mapping,{"Append Cable":{0:"Unknown",1:"Yes",2:"No"}})
        self.assertEqual(unknown["status"],"GAP")
        missing_field = evaluate_asset({
            "GLOBALID":"{P}", "OBJECTID":1,
            "ASSETGROUP":7,"ASSETTYPE":1,
            "Manufacturers":"ABC","Notes":"",
        },"pole",{"manufacturer":"Manufacturers","notes":"Notes",
                  "append_cable":None,"height":"Pole_Height"})
        self.assertEqual(missing_field["status"],"NOT_VERIFIED")
        self.assertIn("append_cable", missing_field["unverified_checks"])
        self.assertEqual(missing_field["values"]["append_cable_status"],
                         "NOT_VERIFIED_FIELD")

    def test_absent_notes_field_blocks_complete_result(self):
        result = evaluate_asset({
            "ASSETGROUP":7, "ASSETTYPE":2, "GLOBALID":"P3",
            "Manufacturer":None,
        }, "pole", {"manufacturer":"Manufacturer", "notes":None})
        self.assertEqual(result["status"], "GAP")
        self.assertIn("notes", result["unverified_checks"])

    def test_pole_height_above_12_requires_mv_hv_purpose_in_notes(self):
        from meter_photo_qa.asset_quality import assess_pole_height,has_explicit_mv_hv_note
        for note in (
            "Pole for MV lines",
            "The pole supports High Voltage Lines",
            "HV tower",
            "Used for medium voltage conductors",
        ):
            with self.subTest(note=note):
                self.assertTrue(has_explicit_mv_hv_note(note))
                self.assertEqual(assess_pole_height(13.2,note)[0],
                                 "MV_HV_NOTES_DOCUMENTED")
        for note in ("", "No nameplate", "not for MV lines",
                     "No HV tower is installed", "HV tower not installed",
                     "LV only", "MV unknown"):
            with self.subTest(note=note):
                self.assertEqual(assess_pole_height(13,note)[0],
                                 "MV_HV_NOTES_REQUIRED")
        self.assertEqual(assess_pole_height(12,"")[0],"WITHIN_THRESHOLD")
        self.assertEqual(assess_pole_height(None,"")[0],"UNRECORDED")
        self.assertEqual(assess_pole_height("wrong","")[0],"INVALID_NUMERIC")

    def test_zero_phase_code_is_valid_when_domain_label_one(self):
        self.assertFalse(missing_value(0, {0:"1 phase", 1:"3 phases"}))
        self.assertTrue(missing_value(0, {0:"Unknown", 1:"3 phases"}))
        mapping = {key: None for key in ASSETS["transformer"]["checks"]}
        mapping.update({
            "name":"Transfomer_name_", "owner_name":"Owner_Name",
            "installation_type":"Type_of_Installation",
            "phase_normal":"Phase_Normal", "protection_switch":"Transformer_Protection_Switch",
            "mounting_support":"Transformer_mounting_support",
            "lv_feeder_count":"Number_of_Low_Voltage_feeders",
        })
        result = evaluate_asset({
            "ASSETGROUP":12, "ASSETTYPE":4, "GLOBALID":"T",
            "Transfomer_name_":"TR", "Owner_Name":"REG",
            "Type_of_Installation":"Outdoor", "Phase_Normal":0,
            "Transformer_Protection_Switch":"DropOut",
            "Transformer_mounting_support":"PH Concrete",
            "Number_of_Low_Voltage_feeders":1,
        }, "transformer", mapping, {"Phase_Normal":{0:"1 phase", 2:"3 phases"}})
        self.assertEqual(result["status"], "NO_GAPS_FOUND")

    def test_owner_type_phase_protection_support_and_feeders_gaps(self):
        names = ["Transfomer_name_", "Owner_Name", "Type_of_Installation",
                 "Phase_Normal", "Transformer_Protection_Switch",
                 "Transformer_mounting_support", "Number_of_Low_Voltage_feeders"]
        mapping = resolve_fields([{"name":name} for name in names], "transformer")
        attrs = {
            "GLOBALID":"T", "OBJECTID":1, "ASSETGROUP":12, "ASSETTYPE":1,
            "Transfomer_name_":"T1",
            "Owner_Name":"Unknown", "Type_of_Installation":None,
            "Phase_Normal":None, "Transformer_Protection_Switch":"Unknown",
            "Transformer_mounting_support":"Unknown",
            "Number_of_Low_Voltage_feeders":None,
        }
        result = evaluate_asset(attrs, "transformer", mapping)
        self.assertEqual(result["status"], "GAP")
        self.assertEqual(len(result["issues"]), 6)
        self.assertNotIn("Branch", "; ".join(result["issues"]))

    def test_alias_matching_only_if_unambiguous(self):
        fields = [{"name":"MakerABC", "alias":"Owner Name"}]
        mapping = resolve_fields(fields, "transformer")
        self.assertEqual(mapping["owner_name"], "MakerABC")
        fields.append({"name":"OtherOne", "alias":"Owner Name"})
        self.assertIsNone(resolve_fields(fields, "transformer")["owner_name"])

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

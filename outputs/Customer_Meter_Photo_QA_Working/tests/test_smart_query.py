from __future__ import annotations

import unittest

from meter_photo_qa.smart_query import (
    QueryPlan, AttributeCondition, boundary_where,
    compile_attribute_where, parse_request,
)


class SmartQueryParserTests(unittest.TestCase):
    def test_pole_in_district_with_missing_manufacturer(self):
        plan = parse_request("Show LV poles in Gicumbi with missing manufacturer")
        self.assertEqual(plan.asset, "pole")
        self.assertEqual(plan.district, "Gicumbi")
        self.assertEqual(plan.conditions, (AttributeCondition("manufacturer","missing"),))
        where = compile_attribute_where(plan,[
            {"name":"ASSETGROUP","type":"esriFieldTypeInteger"},
            {"name":"Manufacturers","alias":"Manufacturers","type":"esriFieldTypeString"},
        ])
        self.assertIn("ASSETGROUP IN (7)",where)
        self.assertIn("Manufacturers IS NULL",where)
        self.assertIn("Manufacturers = ''",where)
        self.assertIn("'GICUMBI'",boundary_where(plan))

    def test_transformer_switch_unknown(self):
        plan = parse_request("Find distribution transformers in Burera with protection switch is unknown")
        self.assertEqual(plan.asset,"transformer")
        self.assertEqual(plan.conditions[0].key,"protection_switch")
        where = compile_attribute_where(plan,[
            {"name":"Transformer_Protection_Switch","alias":"Transformer Protection Switch",
             "type":"esriFieldTypeInteger"},
        ],{"Transformer_Protection_Switch":{0:"Unknown",1:"DropOut"}})
        self.assertIn("ASSETGROUP IN (12)",where)
        self.assertIn("Transformer_Protection_Switch IS NULL",where)
        self.assertIn("Transformer_Protection_Switch = 0",where)

    def test_muko_sector_and_transformer_name(self):
        plan=parse_request("Count LV lines in Gicumbi sector Muko with missing transformer name")
        self.assertEqual(plan.action,"count")
        self.assertEqual(plan.sector,"Muko")
        self.assertIn("'MUKO'",boundary_where(plan))
        where=compile_attribute_where(plan,[
            {"name":"Transformer_Name","type":"esriFieldTypeString"}
        ])
        self.assertIn("Transformer_Name IS NULL",where)
        self.assertIn("ASSETGROUP IN (9,10)",where)

    def test_voltage_400_is_numeric_only_if_live_field_numeric(self):
        plan=parse_request("Filter LV lines in Gasabo with voltage = 400")
        self.assertEqual(plan.conditions,(AttributeCondition("voltage","equals","400"),))
        numeric=compile_attribute_where(plan,[
            {"name":"Voltage_Level_kV","type":"esriFieldTypeDouble"}])
        self.assertIn("Voltage_Level_kV = 400",numeric)
        string=compile_attribute_where(plan,[
            {"name":"Voltage_Level_kV","type":"esriFieldTypeString"}])
        self.assertIn("Voltage_Level_kV = '400'",string)

    def test_optional_v_unit_as_user_input(self):
        plan=parse_request("Show LV lines in Burera with voltage = 400V")
        self.assertEqual(plan.conditions[0].value,"400")

    def test_name_equals_known_value(self):
        plan=parse_request('Find transformers in Burera with transformer name = "Kisaro"')
        self.assertEqual(plan.conditions[0].value,"Kisaro")
        where=compile_attribute_where(plan,[
            {"name":"Transfomer_name_","type":"esriFieldTypeString"}])
        self.assertIn("Transfomer_name_ = 'Kisaro'",where)

    def test_named_surveryor_is_only_explicit_current_username(self):
        plan=parse_request("Show LV poles in Gicumbi by maniraguhatheogene01")
        self.assertEqual(plan.surveyors,("maniraguhatheogene01",))
        where=compile_attribute_where(plan,[
            {"name":"created_user","type":"esriFieldTypeString"}
        ])
        self.assertIn("'maniraguhatheogene01'",where)

    def test_pamela_team_has_six_sectors_and_current_12_accounts(self):
        plan=parse_request("Show LV poles in Pamela team with missing manufacturer")
        self.assertEqual(plan.district,"Gicumbi")
        self.assertTrue(plan.pamela_team)
        self.assertEqual(len(plan.surveyors),12)
        self.assertIn("maniraguhatheogene01",plan.surveyors)
        where=boundary_where(plan)
        self.assertIn("'MUKO'",where)
        self.assertIn("'RUSH AKI'".replace(" ",""),where)
        self.assertNotIn("'GAKENKE'",where)

    def test_cell_must_have_explicit_district_sector(self):
        plan=parse_request("Find LV poles in Gicumbi sector Muko cell Mwendo")
        self.assertEqual(plan.cell,"Mwendo")
        self.assertIn("'MWENDO'",boundary_where(plan))
        with self.assertRaisesRegex(ValueError,"district and sector"):
            parse_request("Find LV poles in Gicumbi cell Mwendo")

    def test_missing_numeric_does_not_mark_zero_without_domain(self):
        plan=parse_request("Show transformers in Burera with missing phase normal")
        where=compile_attribute_where(plan,[
            {"name":"Phase_Normal","type":"esriFieldTypeInteger"},
        ],{"Phase_Normal":{0:"Single Phase",1:"Three Phase"}})
        self.assertIn("Phase_Normal IS NULL",where)
        self.assertNotIn("Phase_Normal = 0",where)

    def test_unknown_live_field_fails_loudly(self):
        plan=parse_request("Show LV poles in Gicumbi with missing manufacturer")
        with self.assertRaisesRegex(ValueError,"verify live"):
            compile_attribute_where(plan,[{"name":"ManufacturerCountry"}])

    def test_non_supported_requests_rejected_not_silently_dropped(self):
        examples=[
            "Find LV poles in Gicumbi whose voltage greater than 400",
            "Find LV lines in Gicumbi connected to downstream transformers",
            "Show transformers in Gicumbi with capacity over 100",
            "Show LV lines in Burera and Gasabo",
            "Find MV lines in Burera",
            "Show LV poles near my house",
        ]
        for phrase in examples:
            with self.subTest(phrase=phrase),self.assertRaises(ValueError):
                parse_request(phrase)

    def test_commands_reject_editing_and_sql_injection(self):
        for phrase in [
            "Delete all poles in Gicumbi",
            "Show LV poles in Gicumbi; DROP TABLE users",
            "Update LV lines with voltage = 400",
            "Filter LV poles in Gicumbi with manufacturer = a' OR 1=1 --",
        ]:
            with self.subTest(phrase=phrase),self.assertRaises(ValueError):
                parse_request(phrase)

    def test_ambiguous_sector_or_unrelated_location_rejected(self):
        with self.assertRaises(ValueError):
            parse_request("Find LV poles in sector Nemba")
        with self.assertRaises(ValueError):
            parse_request("Show LV poles in Gicumbi sector Imaginary")

if __name__=="__main__":
    unittest.main()

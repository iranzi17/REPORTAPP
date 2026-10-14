from __future__ import annotations

import unittest
from meter_photo_qa.template_attribute_audit import (
    parse_surveyor_template_request,resolve_live_field,compile_template_filter,
)

class SurveyorTemplateAuditTests(unittest.TestCase):
    fields=[
        {"name":"OBJECTID","type":"esriFieldTypeOID"},
        {"name":"GLOBALID","type":"esriFieldTypeGlobalID"},
        {"name":"created_user","type":"esriFieldTypeString"},
        {"name":"ASSETGROUP","type":"esriFieldTypeInteger"},
        {"name":"Pole_Height","alias":"Pole Height","type":"esriFieldTypeDouble"},
        {"name":"Manufacturers","alias":"Manufacturer","type":"esriFieldTypeString"},
        {"name":"Append_Cable","alias":"Append Cable","type":"esriFieldTypeSmallInteger"},
    ]

    def test_height_greater_than_12_by_surveyor_accounts(self):
        for prompt in [
            "Give me surveyors who recorded pole height greater than 12 in Gicumbi",
            "Give me surveyors who are filling the height of pole with the values greater than 12 in Gicumbi",
            "Show surveyors with pole height > 12 in Gicumbi",
        ]:
            with self.subTest(prompt=prompt):
                plan=parse_surveyor_template_request(prompt)
                self.assertEqual(plan.asset,"pole")
                self.assertEqual(plan.district,"Gicumbi")
                self.assertEqual(plan.criteria[0].operator,"gt")
                self.assertEqual(plan.criteria[0].value,12.0)
                sql,columns,resolved=compile_template_filter(plan,self.fields)
                self.assertIn("Pole_Height > 12",sql)
                self.assertEqual(columns,("Pole_Height",))
                self.assertEqual(resolved[0]["alias"],"Pole Height")

    def test_multiple_mandatory_missing_fields_in_sector(self):
        plan=parse_surveyor_template_request(
            "Show surveyors missing manufacturer and append cable on LV poles in Gicumbi sector Muko"
        )
        self.assertEqual(plan.asset,"pole")
        self.assertEqual(plan.district,"Gicumbi")
        self.assertEqual(plan.sector,"Muko")
        self.assertEqual(plan.condition_mode,"all")
        sql,columns,_=compile_template_filter(plan,self.fields,{
            "Append_Cable":{0:"No",1:"Yes",9:"Unknown"}
        })
        self.assertEqual(columns,("Manufacturers","Append_Cable"))
        self.assertIn("Manufacturers IS NULL",sql)
        self.assertIn("Append_Cable IS NULL",sql)
        self.assertIn("Append_Cable = 9",sql)
        self.assertNotIn("Append_Cable = 0",sql)
        self.assertIn(" AND ",sql)

    def test_any_missing_is_or_not_all(self):
        plan=parse_surveyor_template_request(
            "Find surveyors missing any of manufacturer or append cable on LV poles in Gicumbi"
        )
        self.assertEqual(plan.condition_mode,"any")
        sql,_,_=compile_template_filter(plan,self.fields)
        self.assertIn(" OR ",sql)

    def test_only_live_numeric_field_can_be_compared(self):
        plan=parse_surveyor_template_request(
            "Show surveyors with manufacturer greater than 12 on LV poles in Gicumbi"
        )
        with self.assertRaisesRegex(ValueError,"not numeric"):
            compile_template_filter(plan,self.fields)

    def test_schema_alias_must_be_unique_and_exist(self):
        with self.assertRaisesRegex(ValueError,"Ambiguous"):
            resolve_live_field("height","pole",[
                {"name":"Pole_Height","alias":"Height"},
                {"name":"Height_Of_Pole","alias":"Height"},
            ])
        with self.assertRaisesRegex(ValueError,"not found"):
            resolve_live_field("invisible voltage","pole",self.fields)

    def test_numeric_zero_valid_unless_coded_unknown(self):
        plan=parse_surveyor_template_request(
            "Show surveyors missing append cable on LV poles in Gicumbi"
        )
        sql,_,_=compile_template_filter(plan,self.fields,{
            "Append_Cable":{0:"No",1:"Yes",9:"Unknown"}
        })
        self.assertNotIn("Append_Cable = 0",sql)
        self.assertIn("Append_Cable = 9",sql)

    def test_reject_units_without_verified_metadata(self):
        for request in (
            "Show surveyors with pole height greater than 12 m in Gicumbi",
            "Show surveyors with pole height > 12 feet in Gicumbi",
        ):
            with self.subTest(request=request),self.assertRaisesRegex(ValueError,"unit"):
                parse_surveyor_template_request(request)

    def test_read_only_rejects_unsafe_and_unrecognized_syntax(self):
        for request in [
            "Delete surveyors missing manufacturer in Gicumbi",
            "Show surveyors with pole height between 10 and 12 in Gicumbi",
            "Show surveyors with pole height greater than 12 in fakeprovince",
            "Show surveyors with pole height greater than 12 in Gicumbi district Rulindo",
        ]:
            with self.subTest(request=request),self.assertRaises(ValueError):
                parse_surveyor_template_request(request)

    def test_transformer_numeric_and_line_missing_aliases(self):
        cases=[
            ("Find surveyors with number of LV feeders > 5 on distribution transformers in Gicumbi",
             {"name":"Number_of_Low_Voltage_feeders","alias":"Number of LV feeders",
              "type":"esriFieldTypeSmallInteger"},
             "Number_of_Low_Voltage_feeders > 5"),
            ("Find surveyors missing transformer name on LV lines in Gicumbi",
             {"name":"Transformer_Name","alias":"Transformer Name",
              "type":"esriFieldTypeString"},
             "Transformer_Name IS NULL"),
        ]
        for prompt,field,expected in cases:
            with self.subTest(prompt=prompt):
                plan=parse_surveyor_template_request(prompt)
                sql,_,_=compile_template_filter(plan,[*self.fields,field])
                self.assertIn(expected,sql)

if __name__=="__main__":
    unittest.main()

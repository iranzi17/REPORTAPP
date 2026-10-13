from __future__ import annotations

import unittest

from meter_photo_qa.transformer_line_names import (
    assess_line_transformer_names, normalized_label, summary_by_surveyor,
)


def point(oid, name):
    return {
        "OBJECTID": oid, "GLOBALID": f"{{T-{oid}}}",
        "ASSETGROUP": 12, "ASSETTYPE": 4,
        "Transfomer_name_": name,
    }


def line(oid, name, user="surveyor"):
    return {
        "OBJECTID": oid, "GLOBALID": f"{{L-{oid}}}",
        "Transformer_Name": name, "created_user": user,
    }


def traced(source, lines, sources=None):
    return {
        "line_objectids": set(lines),
        "connected_transformer_objectids": set(sources or [source]),
    }


class TransformerLineNameTests(unittest.TestCase):
    def test_all_connected_lines_should_have_same_unique_source_name(self):
        rows = assess_line_transformer_names(
            [line(1,"Kisaro"), line(2,"Kisaro"), line(3,"Gatovu")],
            [point(101,"Kisaro")],
            {101: traced(101,[1,2,3])},
        )
        self.assertEqual(
            [row["status"] for row in rows],
            ["MATCH", "MATCH", "NAME_MISMATCH_REVIEW"],
        )
        self.assertEqual(rows[2]["transformer_globalid"], "{T-101}")
        self.assertEqual(rows[2]["globalid"], "{L-3}")
        self.assertEqual(rows[2]["connected_transformer_name"], "Kisaro")

    def test_case_and_whitespace_are_not_name_errors(self):
        rows = assess_line_transformer_names(
            [line(1,"  KISARO  2  ")], [point(101,"Kisaro 2")],
            {101: traced(101,[1])},
        )
        self.assertEqual(rows[0]["status"],"MATCH")
        self.assertNotEqual(normalized_label("Kisaro 2"), normalized_label("Kisaro-2"))

    def test_missing_line_name_with_unique_connected_source(self):
        rows = assess_line_transformer_names(
            [line(1,None)], [point(101,"Kisaro")],
            {101: traced(101,[1])},
        )
        self.assertEqual(rows[0]["status"], "MISSING_LINE_TRANSFORMER_NAME")

    def test_ambiguous_connected_transformers_cannot_assert_supply(self):
        rows = assess_line_transformer_names(
            [line(1,"Kisaro")], [point(101,"Kisaro")],
            {101: traced(101,[1], [101,202])},
        )
        self.assertEqual(rows[0]["status"],"AMBIGUOUS_CONNECTED_SOURCES")
        self.assertFalse(rows[0]["connected_transformer_name"])

    def test_overlapping_local_transformer_traces_are_ambiguous(self):
        rows = assess_line_transformer_names(
            [line(1,"Gatovu")], [point(101,"Kisaro"),point(202,"Gatovu")],
            {101: traced(101,[1]), 202: traced(202,[1])},
        )
        self.assertEqual(rows[0]["status"],"AMBIGUOUS_CONNECTED_SOURCES")

    def test_transfomer_without_valid_name_not_used_as_reference(self):
        rows = assess_line_transformer_names(
            [line(1,"Kisaro")], [point(101,None)],
            {101: traced(101,[1])},
        )
        self.assertEqual(rows[0]["status"],"TRANSFORMER_NAME_UNVERIFIED")

    def test_trace_warning_is_unverified_not_mismatch(self):
        trace = traced(101, [1])
        trace["warnings"] = ["A topology warning"]
        rows = assess_line_transformer_names(
            [line(1, "Wrong")], [point(101, "Kisaro")],
            {101: trace},
        )
        self.assertEqual(rows[0]["status"], "TRACE_WARNING_UNVERIFIED")
        self.assertFalse(rows[0]["connected_transformer_name"])

    def test_source_outside_selected_area_is_not_called_mismatch(self):
        rows = assess_line_transformer_names(
            [line(1,"Wrong?")], [point(101,"Kisaro")],
            {101: traced(101,[2])},
        )
        self.assertEqual(rows[0]["status"],"SOURCE_UNVERIFIED")

    def test_globalids_and_surveyors_are_preserved(self):
        rows = assess_line_transformer_names(
            [line(1,"Kisaro","mary"), line(2,"Wrong","mary"),
             line(3,"Unknown","joe")],
            [point(101,"Kisaro")], {101: traced(101,[1,2])},
        )
        totals=summary_by_surveyor(rows)
        self.assertEqual(totals["mary"]["checked"],2)
        self.assertEqual(totals["mary"]["NAME_MISMATCH_REVIEW"],1)
        self.assertEqual(totals["joe"]["SOURCE_UNVERIFIED"],1)

    def test_duplicate_line_global_objectid_rejected(self):
        with self.assertRaisesRegex(ValueError,"Duplicate LV line OBJECTID"):
            assess_line_transformer_names(
                [line(1,"Kisaro"),line(1,"Kisaro")],
                [point(101,"Kisaro")],{101:traced(101,[1])}
            )

    def test_partial_trace_does_not_assume_a_single_source(self):
        with self.assertRaisesRegex(RuntimeError,"Missing connectivity result"):
            assess_line_transformer_names(
                [line(1,"Wrong")], [point(101,"Kisaro")], {}
            )

    def test_non_distribution_device_is_rejected(self):
        bad=point(101,"Kisaro")
        bad["ASSETGROUP"]=8
        with self.assertRaisesRegex(ValueError,"distribution transformer"):
            assess_line_transformer_names(
                [line(1,"Wrong")],[bad],{101:traced(101,[1])}
            )

    def test_unnamed_or_invalid_source_does_not_generate_name_error(self):
        for name in ("Unknown","N/A","-"):
            with self.subTest(name=name):
                rows=assess_line_transformer_names(
                    [line(1,"Something")],[point(101,name)],
                    {101:traced(101,[1])}
                )
                self.assertEqual(rows[0]["status"], "TRANSFORMER_NAME_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()

"""Regression tests for staged read-only ArcGIS exact feature resolver."""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from meter_photo_qa.exact_feature_lookup import ExactFeatureMismatch, resolve_exact_feature

GID = "142a4dba-f393-4597-90a9-3878a86827b9"
EVENT = 1792161960000


def record(**changes):
    attrs = {
        "OBJECTID": 891705, "GLOBALID": "{" + GID.upper() + "}",
        "created_date": EVENT - 5000, "created_user": "original",
        "last_edited_date": EVENT, "last_edited_user": "ninamenye9683",
    }
    attrs.update(changes)
    return SimpleNamespace(attributes=attrs)


class FakeLayer:
    def __init__(self, features):
        self.features = features
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(features=self.features)


class ExactFeatureLookupTests(unittest.TestCase):
    def test_exact_globalid_objectid_timestamp_editor_and_version(self):
        layer = FakeLayer([record()])
        result = resolve_exact_feature(layer, globalid="{" + GID.upper() + "}",
            objectid=891705, event_time_utc_ms=EVENT, actor="NINAMENYE9683")
        self.assertEqual(result.attributes["OBJECTID"], 891705)
        self.assertEqual(layer.calls[0]["where"], "GlobalID='{" + GID + "}'")
        self.assertEqual(layer.calls[0]["gdb_version"], "sde.DEFAULT")
        self.assertEqual(layer.calls[0]["result_record_count"], 2)
        self.assertFalse(layer.calls[0]["return_geometry"])
        self.assertEqual(len(layer.calls), 1)

    def test_ambiguous_or_missing_globalid_query_must_fail(self):
        for found in ([], [record(), record()]):
            with self.subTest(count=len(found)), self.assertRaises(ExactFeatureMismatch):
                resolve_exact_feature(FakeLayer(found), globalid=GID, objectid=891705)

    def test_wrong_pole_by_same_creator_never_accepted(self):
        for attrs in (
            {"OBJECTID": 891706},
            {"GLOBALID": "{4511a86a-a389-4b93-9e67-e2ae97933d3f}"},
        ):
            with self.subTest(attrs=attrs), self.assertRaises(ExactFeatureMismatch):
                resolve_exact_feature(FakeLayer([record(**attrs)]),
                                      globalid=GID, objectid=891705)

    def test_newer_edit_or_other_editor_must_fail(self):
        for attrs in ({"last_edited_date": EVENT + 60000},
                      {"last_edited_user": "different_surveyor"}):
            with self.subTest(attrs=attrs), self.assertRaises(ExactFeatureMismatch):
                resolve_exact_feature(FakeLayer([record(**attrs)]),
                    globalid=GID, objectid=891705,
                    event_time_utc_ms=EVENT, actor="ninamenye9683")

    def test_created_event_uses_creator_not_editor_on_timestamp_tie(self):
        one = record(created_date=EVENT, last_edited_date=EVENT,
                     created_user="original")
        result = resolve_exact_feature(FakeLayer([one]), globalid=GID,
            objectid=891705, event_time_utc_ms=EVENT, actor="original")
        self.assertIs(result, one)

    def test_invalid_input_rejected_before_query(self):
        for kwargs in (
            {"globalid": "nonsense", "objectid": 891705},
            {"globalid": GID, "objectid": True},
            {"globalid": GID, "objectid": 0},
            {"globalid": GID, "objectid": 891705, "gdb_version": "other"},
            {"globalid": GID, "objectid": 891705, "actor": "other"},
        ):
            layer = FakeLayer([record()])
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                resolve_exact_feature(layer, **kwargs)
            self.assertEqual(layer.calls, [])


if __name__ == "__main__":
    unittest.main()

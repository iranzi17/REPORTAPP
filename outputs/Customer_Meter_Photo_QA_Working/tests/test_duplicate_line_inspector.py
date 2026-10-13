from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import load_workbook

from meter_photo_qa.duplicate_line_inspector import (
    canonical_globalid, _canonical_paths, inspect_duplicate_line_globalid,
)

GUID = "{9FD1C5F4-AF23-43A3-90E3-CB1E7D8CA08C}"


def feature(oid, path):
    return SimpleNamespace(
        attributes={
            "OBJECTID": oid, "GLOBALID": GUID, "ASSETGROUP": 9,
            "ASSETTYPE": 1, "SHAPE_Length": 19.028842,
            "last_edited_user": "jeandamourngurinzira22",
            "Material": "Aluminium", "ConductorInsulation": 1,
        },
        geometry={"paths": [path]},
    )


class DuplicateLineInspectorTests(unittest.TestCase):
    def test_guid_validation_prevents_sql_input(self):
        self.assertEqual(canonical_globalid(GUID.lower().strip("{}")), GUID)
        with self.assertRaises(ValueError):
            canonical_globalid("x' OR 1=1 --")

    def test_reversed_vertices_are_same_exact_polyline(self):
        a = {"paths": [[[100, 0], [101, 0], [102, 1]]]}
        b = {"paths": [[[102, 1], [101, 0], [100, 0]]]}
        self.assertEqual(_canonical_paths(a), _canonical_paths(b))

    def test_same_length_does_not_mean_same_geometry(self):
        a = {"paths": [[[100, 0], [101, 0]]]}
        b = {"paths": [[[200, 0], [201, 0]]]}
        self.assertNotEqual(_canonical_paths(a), _canonical_paths(b))

    def inspect(self, features):
        reqs = []
        layer = SimpleNamespace(query=lambda **kwargs: (
            reqs.append(kwargs) or SimpleNamespace(features=features)
        ))
        arcgis = types.ModuleType("arcgis")
        arcgis_features = types.ModuleType("arcgis.features")
        arcgis_features.FeatureLayer = lambda url, gis: layer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, patch.dict(
            sys.modules, {"arcgis":arcgis, "arcgis.features":arcgis_features},
        ):
            result = inspect_duplicate_line_globalid(
                GUID, Path(folder)/"diagnosis.xlsx", gis=object(),
            )
            workbook = load_workbook(result["output_xlsx"], read_only=True)
            report = list(workbook["Electric Line Records"].values)
            workbook.close()
        return result, report, reqs

    def test_two_objectids_and_exact_geometry_confirmed(self):
        data = [
            feature(122510, [[0, 0], [19, 0]]),
            feature(122944, [[19, 0], [0, 0]]),
        ]
        result, report, requests = self.inspect(data)
        self.assertEqual(result["objectids"], [122510,122944])
        self.assertTrue(result["duplicate_globalid"])
        self.assertTrue(result["same_exact_geometry"])
        self.assertEqual(len(report), 3)
        self.assertEqual(requests[0]["where"], f"GLOBALID = '{GUID}'")
        self.assertTrue(requests[0]["return_geometry"])
        self.assertEqual(requests[0]["gdb_version"], "sde.DEFAULT")

    def test_same_length_but_different_coordinates_not_called_same(self):
        data = [
            feature(122510, [[0, 0], [19, 0]]),
            feature(122944, [[100, 0], [119, 0]]),
        ]
        result, _, _ = self.inspect(data)
        self.assertTrue(result["duplicate_globalid"])
        self.assertFalse(result["same_exact_geometry"])

    def test_service_returns_one_feature_display_may_be_duplicated(self):
        result, _, _ = self.inspect([feature(122510, [[0, 0], [19, 0]])])
        self.assertFalse(result["duplicate_globalid"])

    def test_no_records_never_called_duplicate(self):
        result, report, _ = self.inspect([])
        self.assertEqual(result["matched_source_objects"],0)
        self.assertEqual(len(report),1)

    def test_repeat_objectid_causes_incomplete_source_error(self):
        with self.assertRaisesRegex(RuntimeError,"repeated the same OBJECTID"):
            self.inspect([
                feature(122510, [[0, 0], [19, 0]]),
                feature(122510, [[0, 0], [19, 0]]),
            ])


if __name__ == "__main__":
    unittest.main()

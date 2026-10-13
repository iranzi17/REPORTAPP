from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meter_photo_qa.connectivity_trace import (
    TopologyDirtyAreaError, _trace_dirty_error, trace_connected_lv_lines,
)


GUID = "{9FD1C5F4-AF23-43A3-90E3-CB1E7D8CA08C}"
POINT = {
    "OBJECTID": 74507, "GLOBALID": "{11111111-2222-3333-4444-555555555555}",
    "ASSETGROUP": 12, "ASSETTYPE": 4,
}
SCHEMA = {"domainNetworks": []}


class DirtyAreaTraceTests(unittest.TestCase):
    def test_arcgis_dirty_area_message_identifies_affected_features(self):
        error = Exception(f"One or more dirty areas were discovered. [ElectricLine: {GUID}] (Error Code: 0)")
        wrapped = _trace_dirty_error(error, POINT, "sde.DEFAULT", 2, 48)
        self.assertIsInstance(wrapped, TopologyDirtyAreaError)
        self.assertEqual(wrapped.transformer_objectid, 74507)
        self.assertEqual(wrapped.trace_position, 2)
        self.assertEqual(wrapped.trace_total, 48)
        self.assertEqual(wrapped.dirty_line_globalids, (GUID,))
        self.assertIn("NOT a transformer-name mismatch", str(wrapped))
        self.assertIn("No name-consistency", str(wrapped))
        self.assertIn(GUID, str(wrapped))

    def test_non_dirty_errors_are_not_mislabeled(self):
        self.assertIsNone(_trace_dirty_error(
            Exception("HTTP 503 timeout"), POINT, "sde.DEFAULT", 1, 1
        ))

    def test_dirty_trace_preserves_validate_consistency_and_fails_closed(self):
        captured = {}
        def failing_post(url, params):
            captured["config"] = json.loads(params["traceConfiguration"])
            raise Exception(f"One or more dirty areas were discovered. [ElectricLine: {GUID}]")
        fake_gis = SimpleNamespace(_con=SimpleNamespace(post=failing_post))
        with patch("meter_photo_qa.connectivity_trace._network_schema", return_value=SCHEMA), \
             patch("meter_photo_qa.connectivity_trace._source", return_value={"sourceId": 3}), \
             patch("meter_photo_qa.connectivity_trace._terminal_id", return_value=2):
            with self.assertRaises(TopologyDirtyAreaError) as cm:
                trace_connected_lv_lines(
                    fake_gis, "https://example.org/FeatureServer",
                    [POINT], "sde.DEFAULT",
                )
        self.assertTrue(captured["config"]["validateConsistency"])
        self.assertEqual(cm.exception.dirty_line_globalids, (GUID,))

    def test_returned_service_error_dictionary_is_converted_to_actionable_error(self):
        fake_gis = SimpleNamespace(_con=SimpleNamespace(
            post=lambda url, params: {
                "error": {"message": f"One or more dirty areas were discovered. [ElectricLine: {GUID}]"}
            }
        ))
        with patch("meter_photo_qa.connectivity_trace._network_schema", return_value=SCHEMA), \
             patch("meter_photo_qa.connectivity_trace._source", return_value={"sourceId": 3}), \
             patch("meter_photo_qa.connectivity_trace._terminal_id", return_value=2):
            with self.assertRaises(TopologyDirtyAreaError):
                trace_connected_lv_lines(
                    fake_gis, "https://example.org/FeatureServer",
                    [POINT], "sde.DEFAULT",
                )


if __name__ == "__main__":
    unittest.main()

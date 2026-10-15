"""REPORTAPP notification deep-link identity, validation and queue tests."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meter_photo_qa.alert_navigation import (
    zoom_uri,parse_uri,enqueue,is_registered,ASSET_LAYER_IDS,
)

class NavigationTests(unittest.TestCase):
    def test_correct_reg_layer_for_each_alert_type(self):
        for asset,lid in (("pole",12),("line",10),("transformer",7)):
            with self.subTest(asset=asset):
                uri=zoom_uri(asset,4422434)
                self.assertEqual(parse_uri(uri),(asset,4422434,uri))
                with tempfile.TemporaryDirectory() as folder:
                    queued=enqueue(uri,folder=folder,now=1000000)
                    saved=json.loads(Path(queued["queue_file"]).read_text())
                    self.assertEqual(saved["layer_id"],lid)
                    self.assertEqual(saved["objectid"],4422434)
                    self.assertEqual(saved["asset"],asset)
                    self.assertEqual(saved["origin"],"REPORTAPP_NOTIFICATION")
    def test_untrusted_or_invalid_links_are_not_accepted(self):
        bad=[
            "https://evil.example/?asset=pole&objectid=22",
            "reportapp://zoom/generator/10",
            "reportapp://zoom/line/0",
            "reportapp://zoom/line/-1",
            "reportapp://zoom/line/1;DROP",
            "reportapp://zoom/pole/1?asset=line",
            "reportapp://zoom/pole",
            "reportapp://zoom/pole/1?extra=2",
            "reportapp://other/pole/1",
            "reportapp://zoom/pole/9223372036854775808",
        ]
        for uri in bad:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                parse_uri(uri)
    def test_requests_are_distinct_and_atomically_written(self):
        with tempfile.TemporaryDirectory() as folder:
            uri=zoom_uri("pole",125)
            first=enqueue(uri,folder=folder,now=1000000)
            second=enqueue(uri,folder=folder,now=1000010)
            self.assertNotEqual(first["queue_file"],second["queue_file"])
            self.assertEqual(len(list(Path(folder).glob("*.json"))),2)
            self.assertEqual(len(list(Path(folder).glob("*.tmp"))),0)
    def test_missing_registry_means_no_clickable_toast_claim(self):
        class NoRegistry:
            HKEY_CURRENT_USER=1
            def OpenKey(self,*args):
                raise FileNotFoundError
        self.assertFalse(is_registered(NoRegistry()))

if __name__=="__main__":
    unittest.main()

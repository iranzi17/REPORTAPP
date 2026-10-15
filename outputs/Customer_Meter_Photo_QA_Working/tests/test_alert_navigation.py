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

    def test_no_fractional_or_boolean_objectids(self):
        for value in (True,False,1.2,"1.0","1;calc",None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                zoom_uri("pole",value)

    def test_click_cli_only_queues_validated_request(self):
        from meter_photo_qa.alert_navigation import main
        with tempfile.TemporaryDirectory() as folder, \
             patch("meter_photo_qa.alert_navigation.queue_folder",return_value=Path(folder)), \
             patch("builtins.print"):
            self.assertEqual(main(["--uri","reportapp://zoom/pole/4422434"]),0)
            self.assertEqual(len(list(Path(folder).glob("*.json"))),1)
            with self.assertRaises(ValueError):
                main(["--uri","reportapp://zoom/pole/1?command=calc"])
            self.assertEqual(len(list(Path(folder).glob("*.json"))),1)

    def test_toast_body_and_action_use_identical_validated_uri(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from meter_photo_qa.surveyor_notifications import deliver
        popup=Mock()
        notification=Mock(return_value=popup)
        alert=dict(asset="pole",objectid=4422434,username="tester",event_type="created",
                   globalid="duplicate-globalid",issues=["missing"],created_user="tester",
                   last_edited_user="tester")
        with patch.dict("sys.modules",{"winotify":SimpleNamespace(Notification=notification)}), \
             patch("meter_photo_qa.alert_navigation.is_registered",return_value=True):
            deliver(alert,{"channel":"desktop"})
        self.assertEqual(notification.call_args.kwargs["launch"],"reportapp://zoom/pole/4422434")
        popup.add_actions.assert_called_once_with(label="Zoom in ArcGIS Pro",
                                                 launch="reportapp://zoom/pole/4422434")
        popup.show.assert_called_once()

if __name__=="__main__":
    unittest.main()

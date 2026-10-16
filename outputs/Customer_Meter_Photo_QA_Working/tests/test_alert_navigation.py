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
    def test_pause_preserves_pending_and_blocks_new_navigation(self):
        from meter_photo_qa.alert_navigation import (
            pause_navigation,resume_navigation,is_navigation_paused,
        )
        with tempfile.TemporaryDirectory() as location:
            folder=Path(location)/"Navigation"/"Requests"
            first=enqueue("reportapp://zoom/pole/563892",folder=folder,now=1000000)
            self.assertFalse(is_navigation_paused(folder))
            stopped=pause_navigation(folder)
            self.assertTrue(stopped["paused"])
            self.assertEqual(stopped["pending_requests_paused"],1)
            self.assertTrue(Path(first["queue_file"]+".paused").exists())
            self.assertFalse(list(folder.glob("*.json")))
            with self.assertRaisesRegex(RuntimeError,"paused"):
                enqueue("reportapp://zoom/line/3510143",folder=folder)
            resumed=resume_navigation(folder)
            self.assertFalse(resumed["paused"])
            self.assertFalse(list(folder.glob("*.json")))
            self.assertEqual(resumed["previous_requests_replayed"],0)
            second=enqueue("reportapp://zoom/line/3510143",folder=folder)
            self.assertTrue(Path(second["queue_file"]).is_file())

    def test_bridge_must_not_retry_or_replay_old_clicks(self):
        source=(Path(__file__).resolve().parents[1]/
                "addins"/"ReportappNavigationBridge"/"BridgeModule.cs").read_text(
                    encoding="utf-8")
        self.assertIn("MaxNavigationAgeMs = 15000",source)
        self.assertIn('Finish(file, ".failed", issue)',source)
        self.assertIn('Finish(previous, ".superseded"',source)
        self.assertIn("FreshAndCurrent(req,view)",source)
        self.assertIn("navigation-paused.flag",source)
        self.assertNotIn("DateTime.UtcNow.AddMinutes(1)",source)
        self.assertNotIn("FromHours(24)",source)

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

    def test_bridge_guards_manual_selection_before_failed_retries(self):
        """Source-level regression guard; live behavior still needs SDK testing."""
        source=(Path(__file__).resolve().parents[1]/
                "addins"/"ReportappNavigationBridge"/"BridgeModule.cs").read_text(
                    encoding="utf-8")
        before=source.index("layer.Search(filter)")
        staged=source.index("layer.Select(filter, SelectionCombinationMethod.Add)")
        clear=source.index("view.Map.ClearSelection()")
        final=source.index("layer.Select(filter, SelectionCombinationMethod.New)")
        self.assertLess(before,staged)
        self.assertLess(staged,clear)
        self.assertLess(clear,final)
        self.assertIn("if (!rows.MoveNext())",source)
        self.assertIn("if (!staged.GetObjectIDs().Contains(req.ObjectId))",source)

    def test_source_edit_uri_retains_identity_and_version(self):
        args=dict(globalid="{142A4DBA-F393-4597-90A9-3878A86827B9}",
                  event_time_utc_ms=1792161960000,
                  actor="ninamenye9683",gdb_version="sde.DEFAULT")
        uri=zoom_uri("pole",891705,**args)
        self.assertEqual(parse_uri(uri),("pole",891705,uri))
        with tempfile.TemporaryDirectory() as folder:
            r=enqueue(uri,folder=folder,now=1792162500000)
            req=r["request"]
            self.assertEqual(req["expected_globalid"],
                             "142a4dba-f393-4597-90a9-3878a86827b9")
            self.assertEqual(req["expected_event_utc_ms"],1792161960000)
            self.assertEqual(req["expected_actor"],"ninamenye9683")
            self.assertEqual(req["source_gdb_version"],"sde.DEFAULT")

    def test_event_uri_rejects_incomplete_or_untrusted_source_identity(self):
        uri=zoom_uri("pole",891705)
        for bad in (
            uri+"?gid=broken&event_ms=1792161960000&actor=nina&ver=sde.DEFAULT",
            uri+"?gid=142a4dba-f393-4597-90a9-3878a86827b9&event_ms=1792161960000&actor=nina&ver=other",
            uri+"?gid=142a4dba-f393-4597-90a9-3878a86827b9&event_ms=1792161960000&actor=nina&ver=sde.DEFAULT&other=1",
            uri+"?gid=142a4dba-f393-4597-90a9-3878a86827b9&event_ms=1792161960000&actor=nina&actor=another&ver=sde.DEFAULT",
        ):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                parse_uri(bad)
        with self.assertRaises(ValueError):
            zoom_uri("pole",891705,globalid="{142A4DBA-F393-4597-90A9-3878A86827B9}")

    def test_bridge_rejects_different_version_and_event_before_selection(self):
        bridge=(Path(__file__).resolve().parents[1]/"addins"/
                "ReportappNavigationBridge"/"BridgeModule.cs").read_text(
                    encoding="utf-8")
        self.assertIn("CheckSurveyorEdit(found,req)",bridge)
        self.assertIn("MatchesDataset(layer,url)",bridge)
        self.assertIn("siblings.Any(layer=>!MatchesSource(layer,url))",bridge)
        self.assertIn("source_gdb_version",bridge)
        self.assertLess(bridge.index("CheckSurveyorEdit(found,req)"),
                        bridge.index("view.Map.ClearSelection()"))

    def test_toast_body_and_action_use_identical_validated_uri(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from meter_photo_qa.surveyor_notifications import deliver
        popup=Mock()
        notification=Mock(return_value=popup)
        alert=dict(asset="pole",objectid=891705,username="ninamenye9683",
                   event_type="EDIT",
                   globalid="{142A4DBA-F393-4597-90A9-3878A86827B9}",
                   event_time_utc_ms=1792161960000,
                   issues=["Append Cable missing"],created_user="ninamenye9683",
                   last_edited_user="ninamenye9683")
        with patch.dict("sys.modules",{"winotify":SimpleNamespace(Notification=notification)}), \
             patch("meter_photo_qa.alert_navigation.is_registered",return_value=True):
            deliver(alert,{"channel":"desktop","version":"sde.DEFAULT"})
        launch=notification.call_args.kwargs["launch"]
        self.assertIn("event_ms=1792161960000",launch)
        self.assertIn("gid=142a4dba-f393-4597-90a9-3878a86827b9",launch)
        popup.add_actions.assert_called_once_with(label="Zoom in ArcGIS Pro",launch=launch)
        popup.show.assert_called_once()
        self.assertIn("GIS version: sde.DEFAULT",notification.call_args.kwargs["msg"])


if __name__=="__main__":
    unittest.main()

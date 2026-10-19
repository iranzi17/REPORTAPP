"""Live gap popup must contain safe, actionable zoom using the completed scan.

No production ArcGIS requests or UI clicks occur in these regressions.
"""
from __future__ import annotations
import datetime
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meter_photo_qa.source_event_navigation import (
    verified_scanned_event_uri, safe_scanned_event_uri,
)
from meter_photo_qa.alert_navigation import enqueue
from meter_photo_qa.surveyor_notifications import run_once

GID="{142A4DBA-F393-4597-90A9-3878A86827B9}"
ACTOR="julesmugae72"
OID=4573130
NOW=int(datetime.datetime(2026,10,19,12,0,
    tzinfo=datetime.timezone.utc).timestamp()*1000)
EVENT=NOW-305000

def record(*,id=OID,gid=GID,actor=ACTOR,event=EVENT):
    return {
        "OBJECTID":id,"GLOBALID":gid,"ASSETGROUP":7,"ASSETTYPE":1,
        "created_user":actor,"created_date":event,
        "last_edited_user":actor,"last_edited_date":event,
        "Manufacturers":None,"Notes":"","Append_Cable":None,
        "Pole_Height":10,"Service_Pole":"No","PoleStructure":1,
        "InsulatorTypes":1,"Number_Circuit":1,
    }

FIELDS=[{"name":v} for v in (
    "OBJECTID","GLOBALID","ASSETGROUP","ASSETTYPE",
    "created_user","created_date","last_edited_user","last_edited_date",
    "Manufacturers","Notes","Append_Cable","Pole_Height",
    "Service_Pole","PoleStructure","InsulatorTypes","Number_Circuit",
)]
CONFIG={
    "enabled":True,"usernames":[ACTOR],"assets":["pole"],"channel":"desktop",
    "version":"sde.DEFAULT","enabled_at_utc_ms":NOW-2*86400000,
    "pole_manufacturer_gap_enabled":False,
}

def alert():
    return {
        "asset":"pole","objectid":OID,"globalid":GID,
        "username":ACTOR,"event_type":"CREATE",
        "event_time_utc_ms":EVENT,"source_scan_at_utc_ms":NOW,
        "source_scan_evidence":{
            key:record()[key] for key in
            ("OBJECTID","GLOBALID","created_date","created_user",
             "last_edited_date","last_edited_user")
        },
    }


class LiveZoomEvidenceTests(unittest.TestCase):
    def test_verified_scanned_event_link_never_needs_second_network_query(self):
        with patch("meter_photo_qa.source_event_navigation.verified_source_uri",
                   wraps=__import__("meter_photo_qa.source_event_navigation",
                                    fromlist=["verified_source_uri"]).verified_source_uri) as verified:
            uri=verified_scanned_event_uri(alert(),CONFIG,now_ms=NOW)
        self.assertEqual(verified.call_count,1)
        self.assertIn("event_ms="+str(EVENT),uri)
        self.assertIn("actor="+ACTOR,uri)
        self.assertIn("/pole/"+str(OID),uri)
        self.assertIn("gid=142a4dba-f393-4597-90a9-3878a86827b9",uri)
        with tempfile.TemporaryDirectory() as tmp:
            request=enqueue(uri,folder=tmp)["request"]
        self.assertEqual(request["origin"],"REPORTAPP_VERIFIED_ALERT")
        self.assertEqual(request["expected_globalid"],
            "142a4dba-f393-4597-90a9-3878a86827b9")
        self.assertEqual(request["expected_event_utc_ms"],EVENT)
        self.assertEqual(request["expected_actor"],ACTOR)

    def test_stale_wrong_version_wrong_feature_or_editor_all_refuse_click_link(self):
        for update in (
            {"objectid":OID+1},
            {"globalid":"{4511a86a-a389-4b93-9e67-e2ae97933d3f}"},
            {"event_time_utc_ms":EVENT+60000},
            {"username":"different_surveyor"},
            {"source_scan_at_utc_ms":NOW-11*60*1000},
            {"deferred_historical":True},
        ):
            with self.subTest(update=update):
                target=dict(alert(),**update)
                self.assertEqual(
                    safe_scanned_event_uri(target,CONFIG,now_ms=NOW),""
                )
        bad=dict(CONFIG,version="other.VERSION")
        self.assertEqual(safe_scanned_event_uri(alert(),bad,now_ms=NOW),"")
        tampered=alert()
        tampered["source_scan_evidence"]["GLOBALID"]="{4511a86a-a389-4b93-9e67-e2ae97933d3f}"
        self.assertEqual(safe_scanned_event_uri(tampered,CONFIG,now_ms=NOW),"")

    def test_real_watcher_scan_delivers_clickable_toast_and_logs_zoom_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Path(tmp)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG),encoding="utf-8")
            notice=Mock()
            constructor=Mock(return_value=notice)
            one=record()
            def collector(config,now_ms=None):
                return {"pole":([one],FIELDS,{},None,None)}
            with patch.dict("sys.modules",{
                    "winotify":SimpleNamespace(Notification=constructor),
                }), patch(
                    "meter_photo_qa.alert_navigation.is_registered",
                    return_value=True,
                ), patch(
                    "meter_photo_qa.source_event_navigation.safe_verified_source_uri",
                    side_effect=AssertionError("No extra unstable REG query allowed"),
                ):
                result=run_once(cfg,now_ms=NOW,collector=collector)
            self.assertEqual(result["alerts_sent"],1)
            self.assertEqual(result["alerts_delivery_failed"],0)
            toast=constructor.call_args.kwargs
            self.assertEqual(toast["app_id"],"REPORTAPP Surveyor Activity")
            self.assertIn("REG QA: pole gaps",toast["title"])
            self.assertIn("Append Cable",toast["msg"])
            self.assertNotIn("Manufacturer missing",toast["msg"])
            self.assertTrue(toast["launch"].startswith(
                "reportapp://zoom/pole/"+str(OID)+"?"))
            notice.add_actions.assert_called_once_with(
                label="Zoom in ArcGIS Pro",launch=toast["launch"]
            )
            notice.show.assert_called_once()
            rows=[json.loads(row) for row in cfg.with_suffix(
                ".events.jsonl").read_text().splitlines()]
            self.assertEqual(rows[-1]["status"],"SENT")
            self.assertEqual(rows[-1]["objectid"],OID)
            self.assertIs(rows[-1]["zoom_action_included"],True)
            self.assertEqual(rows[-1]["zoom_status"],"SCANNED_EVENT_VALIDATED")
            self.assertTrue(cfg.with_suffix(".sqlite3").exists())


if __name__=="__main__":
    unittest.main()

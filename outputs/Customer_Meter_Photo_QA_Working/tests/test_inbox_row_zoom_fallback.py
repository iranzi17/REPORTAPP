"""Visible per-row ArcGIS Pro navigation and missed-Windows-toast Inbox fallback.

Pure no-network tests: exercise actual queue payloads and durable Inbox feed;
no ArcGIS Pro UI, REG query, Scheduler changes, or popup appears in CI.
"""
from __future__ import annotations
import ast
import json
from pathlib import Path
import tempfile
import unittest

from meter_photo_qa.notification_inbox import (
    connect_inbox, record_alert, mark_delivery, import_legacy_events,
    get_alert, queue_inbox_row_zoom, row_zoom_action, fresh_sent_alerts,
)

EVENT_MS=1792404000000
VALID_GID="{142A4DBA-F393-4597-90A9-3878A86827B9}"

def item(oid, *, event=EVENT_MS, gid=VALID_GID):
    return {
        "asset":"pole", "objectid":oid, "globalid":gid,
        "username":"julesmugae72", "event_type":"CREATE",
        "created_user":"julesmugae72", "last_edited_user":"julesmugae72",
        "event_time_utc_ms":event, "issues":["Append Cable missing"],
        "issue_digest":"some-specific-issues",
    }


class PerRowZoomAndPopupFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg=Path(self.temp.name)/"monitor_config.json"
        self.cfg.write_text(json.dumps({
            "enabled":True,"assets":["pole"],"usernames":["julesmugae72"],
            "version":"sde.DEFAULT","channel":"desktop",
        }),encoding="utf-8")
        self.queue=Path(self.temp.name)/"navigation"
        self.queue.mkdir()

    def test_live_inbox_row_queues_exact_event_not_latest_surveyor_pole(self):
        db=connect_inbox(self.cfg)
        try:
            first=record_alert(db,item(4572332),EVENT_MS+1000)
            second=record_alert(db,item(4582349),EVENT_MS+2000)
            mark_delivery(db,first,"SENT")
            mark_delivery(db,second,"SENT")
            before=[dict(x) for x in db.execute(
                "SELECT * FROM alert_inbox ORDER BY id"
            )]
            self.assertEqual(row_zoom_action(get_alert(db,first)),
                             "Zoom in ArcGIS Pro")
        finally:db.close()
        zoom=queue_inbox_row_zoom(self.cfg,first,folder=self.queue)
        self.assertEqual(zoom["mode"],"VERIFIED_SOURCE_EVENT")
        self.assertEqual(zoom["objectid"],4572332)
        self.assertEqual(zoom["bridge_result"],"QUEUED_NOT_YET_VERIFIED")
        request=json.loads(Path(zoom["request_file"]).read_text(encoding="utf-8"))
        self.assertEqual(request["origin"],"REPORTAPP_VERIFIED_ALERT")
        self.assertEqual(request["objectid"],4572332)
        self.assertEqual(request["expected_globalid"],
                         "142a4dba-f393-4597-90a9-3878a86827b9")
        self.assertEqual(request["expected_event_utc_ms"],EVENT_MS)
        self.assertEqual(request["expected_actor"],"julesmugae72")
        self.assertEqual(request["source_gdb_version"],"sde.DEFAULT")
        db=connect_inbox(self.cfg)
        try:
            after=[dict(x) for x in db.execute(
                "SELECT * FROM alert_inbox ORDER BY id"
            )]
        finally:db.close()
        self.assertEqual(before,after)
        self.assertEqual(len(list(self.queue.glob("*.json"))),1)

    def test_historical_row_clearly_finds_current_asset_only(self):
        old={
            "at_utc_ms":EVENT_MS+3000,"status":"SENT",
            "asset":"pole","objectid":4550150,
            "globalid":VALID_GID,"username":"julesmugae72",
            "issues":["Service Pole missing"],
        }
        self.cfg.with_suffix(".events.jsonl").write_text(
            json.dumps(old)+"\n",encoding="utf-8"
        )
        db=connect_inbox(self.cfg)
        try:
            self.assertEqual(import_legacy_events(self.cfg,db)["imported"],1)
            row=db.execute("SELECT * FROM alert_inbox").fetchone()
            self.assertEqual(row_zoom_action(dict(row)),"Find current asset")
            id=row["id"]
        finally:db.close()
        result=queue_inbox_row_zoom(self.cfg,id,folder=self.queue)
        self.assertEqual(result["mode"],"FIND_CURRENT_ASSET_NOT_HISTORICAL_EVENT")
        req=json.loads(Path(result["request_file"]).read_text(encoding="utf-8"))
        self.assertEqual(req["origin"],"REPORTAPP_MANUAL_FIND")
        self.assertEqual(req["objectid"],4550150)
        self.assertEqual(req["expected_event_utc_ms"],0)

    def test_bad_event_or_unknown_id_queues_nothing(self):
        db=connect_inbox(self.cfg)
        try:
            rowid=record_alert(db,item(4787210,event=1),EVENT_MS+1000)
        finally:db.close()
        with self.assertRaises(ValueError):
            queue_inbox_row_zoom(self.cfg,rowid,folder=self.queue)
        with self.assertRaises(ValueError):
            queue_inbox_row_zoom(self.cfg,9999,folder=self.queue)
        self.assertFalse(list(self.queue.iterdir()))

    def test_inbox_fallback_only_reads_new_sent_live_alerts(self):
        db=connect_inbox(self.cfg)
        try:
            baseline=record_alert(db,item(400001),EVENT_MS)
            mark_delivery(db,baseline,"SENT")
            pending=record_alert(db,item(400002),EVENT_MS+1000)
            delivered=record_alert(db,item(400003),EVENT_MS+2000)
            mark_delivery(db,delivered,"SENT")
            record_alert(db,item(400004),EVENT_MS+3000)
            got=fresh_sent_alerts(db,baseline)
            self.assertEqual([v["id"] for v in got],[delivered])
            self.assertEqual(fresh_sent_alerts(db,delivered),[])
            mark_delivery(db,pending,"SENT")
            # If pending was processed after delivered, it is still in Inbox
            # and zoomable by row. No automatic old-event replay.
            self.assertEqual(fresh_sent_alerts(db,baseline)[-1]["id"],pending)
            with self.assertRaises(ValueError):
                fresh_sent_alerts(db,0,limit=0)
        finally:db.close()

    def test_inbox_popups_never_automatically_zoom_or_replay_old_history(self):
        path=Path(__file__).resolve().parents[1]/(
            "src/meter_photo_qa/notification_inbox.py")
        source=path.read_text(encoding="utf-8")
        self.assertIn('names=("ID","Received","Surveyor","Asset"',source)
        self.assertIn('"Delivery","Zoom")',source)
        self.assertIn('tree.identify_column(event.x)!="#9"',source)
        self.assertIn('text="In-app gap popups"',source)
        self.assertIn('root.after(10000,poll_new_gap_alerts)',source)
        self.assertIn('COALESCE(MAX(id),0)',source)
        self.assertIn('def zoom_from_gap_popup():',source)
        self.assertIn('def dismiss_gap_popup():',source)
        # The scheduled watcher must never open Tkinter or issue a UI zoom.
        self.assertNotIn('auto_zoom',source)
        self.assertIn('No REG',source)


if __name__=="__main__":
    unittest.main()

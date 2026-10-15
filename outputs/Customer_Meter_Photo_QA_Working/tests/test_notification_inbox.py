"""Persistent REPORTAPP inbox: migrated alerts, live delivery and review state."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from meter_photo_qa.notification_inbox import (
    connect_inbox,record_alert,mark_delivery,import_legacy_events,
    list_alerts,set_review,get_alert,format_details,
)
from meter_photo_qa.surveyor_notifications import run_once

CONFIG={"enabled":True,"usernames":["julesmugae72"],
        "assets":["pole"],"channel":"desktop","enabled_at_utc_ms":1000000}

class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.config=Path(self.temp.name)/"monitor_config.json"
        self.config.write_text(json.dumps(CONFIG),encoding="utf-8")
    def tearDown(self):
        self.temp.cleanup()

    def sample(self,oid=4422434,event_ms=1100000):
        return {
            "asset":"pole","objectid":oid,"globalid":"{72C269BF-3E52-4AA7-8A38-47B5BA8C1839}",
            "username":"julesmugae72","event_type":"CREATE",
            "created_user":"julesmugae72","last_edited_user":"julesmugae72",
            "event_time_utc_ms":event_ms,
            "issues":["Append Cable missing/unknown (mandatory LV pole field)",
                      "Manufacturer missing: Notes must state no name plate"],
            "issue_digest":"example-digest",
        }

    def test_inbox_persists_review_and_reopen_without_source_writes(self):
        conn=connect_inbox(self.config)
        try:
            alert=self.sample()
            rowid=record_alert(conn,alert,1400000)
            self.assertEqual(record_alert(conn,alert,1500000),rowid)
            mark_delivery(conn,rowid,"SENT")
            self.assertEqual(len(list_alerts(conn)),1)
            reviewed=set_review(conn,rowid,"REVIEWED",
                                note="Contact Jules to verify pole",reviewer="supervisor",now_ms=1600000)
            self.assertEqual(reviewed["review_status"],"REVIEWED")
            self.assertEqual(len(list_alerts(conn)),0)
        finally:
            conn.close()
        conn=connect_inbox(self.config)
        try:
            row=get_alert(conn,rowid)
            self.assertEqual(row["review_notes"],"Contact Jules to verify pole")
            self.assertEqual(row["reviewed_by"],"supervisor")
            self.assertIn("Append Cable",format_details(row))
            self.assertIn("no REG asset is modified",format_details(row))
            new=set_review(conn,rowid,"OPEN",reviewer="supervisor")
            self.assertEqual(new["review_status"],"OPEN")
            self.assertIsNone(new["reviewed_at_utc_ms"])
            self.assertEqual(len(list_alerts(conn,status="OPEN")),1)
            with self.assertRaises(ValueError):
                mark_delivery(conn,9999,"SENT")
        finally:
            conn.close()

    def test_legacy_event_migrated_idempotently_from_existing_jsonl(self):
        entry={"at_utc_ms":1792068551297,"status":"SENT",
               "asset":"pole","objectid":4422434,
               "globalid":"{72C269BF-3E52-4AA7-8A38-47B5BA8C1839}",
               "username":"julesmugae72",
               "issues":["Append Cable missing/unknown (mandatory LV pole field)",
                         "Manufacturer missing: Notes must state no name plate"]}
        eventlog=self.config.with_suffix(".events.jsonl")
        eventlog.write_text(json.dumps(entry)+"\n"+json.dumps({
            "at_utc_ms":1792068550000,"status":"SEND_FAILED",
            "asset":"pole","objectid":9999,"reason":"toast unavailable"
        })+"\n")
        conn=connect_inbox(self.config)
        try:
            self.assertEqual(import_legacy_events(self.config,conn)["imported"],1)
            self.assertEqual(import_legacy_events(self.config,conn)["imported"],0)
            found=list_alerts(conn,status="ALL")
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]["objectid"],4422434)
            self.assertEqual(found[0]["delivery_status"],"SENT")
            self.assertEqual(found[0]["origin"],"HISTORICAL_JSONL")
            self.assertIsNone(found[0]["event_time_utc_ms"])
        finally:
            conn.close()

    def test_live_monitor_persists_new_delivery_and_retries_failed(self):
        from test_surveyor_notifications import FIELDS,pole
        rec=pole(1100000,append=None,height=13.5)
        rec["created_user"]="julesmugae72"
        rec["last_edited_user"]="julesmugae72"
        def collector(conf,now_ms=None):
            return {"pole":([rec],FIELDS,{},None,None)}
        def fail(alert,conf):
            raise RuntimeError("toast blocked")
        result=run_once(self.config,now_ms=1400000,
                        collector=collector,sender=fail)
        self.assertEqual(result["alerts_delivery_failed"],1)
        conn=connect_inbox(self.config)
        try:
            found=list_alerts(conn)
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]["delivery_status"],"SEND_FAILED")
            self.assertEqual(found[0]["review_status"],"OPEN")
        finally:
            conn.close()
        delivered=[]
        result=run_once(self.config,now_ms=1460000,collector=collector,
                        sender=lambda alert,conf:delivered.append(alert))
        self.assertEqual(result["alerts_sent"],1)
        self.assertEqual(len(delivered),1)
        conn=connect_inbox(self.config)
        try:
            found=list_alerts(conn)
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]["delivery_status"],"SENT")
            self.assertEqual(get_alert(conn,found[0]["id"])["issues_json"],
                             json.dumps(delivered[0]["issues"],ensure_ascii=False))
        finally:
            conn.close()
        result=run_once(self.config,now_ms=1520000,collector=collector,
                        sender=lambda *_:self.fail("duplicate toast"))
        self.assertEqual(result["alerts_sent"],0)

    def test_live_sent_jsonl_is_not_double_imported(self):
        alert=self.sample()
        conn=connect_inbox(self.config)
        try:
            row_id=record_alert(conn,alert,1400000)
            mark_delivery(conn,row_id,"SENT")
            entry={
                "at_utc_ms":1400000,"status":"SENT",
                "asset":alert["asset"],"objectid":alert["objectid"],
                "globalid":alert["globalid"],"username":alert["username"],
                "issues":alert["issues"],
            }
            self.config.with_suffix(".events.jsonl").write_text(
                json.dumps(entry,ensure_ascii=False)+"\n",encoding="utf-8"
            )
            self.assertEqual(import_legacy_events(self.config,conn)["imported"],0)
            self.assertEqual(len(list_alerts(conn,"ALL")),1)
        finally:
            conn.close()

    def test_distinct_issue_or_edit_creates_separate_inbox_entries(self):
        conn=connect_inbox(self.config)
        try:
            first=self.sample()
            a=record_alert(conn,first,1400000)
            modified=dict(first,event_time_utc_ms=1200000)
            b=record_alert(conn,modified,1500000)
            self.assertNotEqual(a,b)
            self.assertEqual(len(list_alerts(conn,"ALL")),2)
        finally:
            conn.close()

if __name__=="__main__":
    unittest.main()

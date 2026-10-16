"""Clean-surveyor-activity notification safeguards (no live REG writes)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meter_photo_qa.surveyor_notifications import run_once,State
from meter_photo_qa.surveyor_activity import (
    change_activity_mode,clean_activity_candidates,process_activity,
    heartbeat_due,list_recent_activity,
)

CONFIG={
    "enabled":True,"enabled_at_utc_ms":1_000_000,
    "activity_notifications_enabled":True,
    "activity_notifications_enabled_at_utc_ms":1_200_000,
    "activity_heartbeat_minutes":60,
    "usernames":["watched.surveyor"],"assets":["pole"],
    "channel":"desktop",
}
FIELDS=[{"name":"OBJECTID"},{"name":"GLOBALID"}]


def pole(event_ms,*,oid=12,who="watched.surveyor",event="CREATE"):
    return {
        "OBJECTID":oid,"GLOBALID":f"{{G-{oid}}}",
        "ASSETGROUP":7,"ASSETTYPE":2,
        "created_user":who,"created_date":event_ms if event=="CREATE" else 1_100_000,
        "last_edited_user":who,"last_edited_date":event_ms,
    }


def snapshots(*records):
    return {"pole":(list(records),FIELDS,{},None,None)}


class CleanSurveyorActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.dir=Path(self.temp.name)
        self.config=self.dir/"monitor_config.json"
        self.config.write_text(json.dumps(CONFIG),encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_opt_in_is_atomic_and_keeps_existing_surveyors_and_history(self):
        original={
            "enabled":True,"enabled_at_utc_ms":42_000,
            "enabled_at_by_username_utc_ms":{"watched.surveyor":43_000},
            "enabled_at_by_asset_utc_ms":{"pole":44_000},
            "usernames":["watched.surveyor"],"assets":["pole"],
            "feature_service_url":"https://example.invalid/FeatureServer",
            "version":"sde.DEFAULT","channel":"desktop",
        }
        self.config.write_text(json.dumps(original),encoding="utf-8")
        sqlite=self.config.with_suffix(".sqlite3")
        sqlite.write_bytes(b"KEEP-ALERT-HISTORY")
        result=change_activity_mode(self.config,True,now_ms=100_000)
        self.assertEqual(result["status"],"UPDATED")
        saved=json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(saved["activity_notifications_enabled_at_utc_ms"],100_000)
        for key,value in original.items():
            self.assertEqual(saved[key],value)
        self.assertEqual(sqlite.read_bytes(),b"KEEP-ALERT-HISTORY")
        self.assertEqual(len(list(self.dir.glob("*backup_activity*"))),1)
        again=change_activity_mode(self.config,True,now_ms=110_000)
        self.assertEqual(again["status"],"UNCHANGED")
        self.assertEqual(json.loads(self.config.read_text())["activity_notifications_enabled_at_utc_ms"],100_000)
        disabled=change_activity_mode(self.config,False,now_ms=120_000)
        self.assertFalse(disabled["enabled"])
        self.assertEqual(json.loads(self.config.read_text())["usernames"],original["usernames"])

    def test_clean_notification_after_five_min_and_exactly_once(self):
        sent=[]
        record=pole(1_300_000)
        with patch("meter_photo_qa.surveyor_notifications.record_findings",return_value=([],[])):
            before=run_once(self.config,now_ms=1_599_000,
                            collector=lambda *_args,**_kwargs:snapshots(record),
                            activity_sender=lambda item,conf:sent.append(item),
                            heartbeat_sender=lambda *_:self.fail("early heartbeat"))
            self.assertEqual(before["clean_notifications_sent"],0)
            passed=run_once(self.config,now_ms=1_600_000,
                            collector=lambda *_args,**_kwargs:snapshots(record),
                            activity_sender=lambda item,conf:sent.append(item),
                            heartbeat_sender=lambda *_:self.fail("early heartbeat"))
            self.assertEqual(passed["clean_notifications_sent"],1)
            self.assertEqual(passed["alerts_sent"],0)
            self.assertEqual(sent[0]["notification_kind"],"CLEAN_ACTIVITY")
            self.assertEqual(sent[0]["event_type"],"CREATE")
            duplicate=run_once(self.config,now_ms=1_660_000,
                               collector=lambda *_args,**_kwargs:snapshots(record),
                               activity_sender=lambda *_:self.fail("duplicate clean notification"))
        self.assertEqual(duplicate["clean_notifications_sent"],0)

    def test_new_edit_produces_new_event_without_repeating_create(self):
        messages=[]
        rec=pole(1_300_000)
        def send(entry,config):
            messages.append(entry["event_type"])
        with patch("meter_photo_qa.surveyor_notifications.record_findings",return_value=([],[])):
            run_once(self.config,now_ms=1_600_000,collector=lambda *_a,**_k:snapshots(rec),
                     activity_sender=send)
            rec.update({"created_date":1_300_000,"last_edited_date":1_620_000})
            run_once(self.config,now_ms=1_920_000,collector=lambda *_a,**_k:snapshots(rec),
                     activity_sender=send)
        self.assertEqual(messages,["CREATE","EDIT"])

    def test_flagged_record_never_generates_clean_popup(self):
        alerts=[]
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=(["Append Cable missing"],[])):
            counts=run_once(
                self.config,now_ms=1_600_000,
                collector=lambda *_a,**_k:snapshots(pole(1_300_000)),
                sender=lambda item,conf:alerts.append(item),
                activity_sender=lambda *_:self.fail("clean popup on flagged pole"),
            )
        self.assertEqual(counts["alerts_sent"],1)
        self.assertEqual(counts["clean_notifications_sent"],0)
        self.assertEqual(len(alerts),1)

    def test_old_unwatched_and_recent_immature_not_notified(self):
        old=pole(1_199_999)
        unwatched=pole(1_300_000,oid=13,who="another")
        immature=pole(1_301_000,oid=14)
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=([],[])):
            state=State(self.config.with_suffix(".sqlite3"))
            try:
                candidates=clean_activity_candidates(
                    snapshots(old,unwatched,immature),CONFIG,1_600_000,state.db
                )
                self.assertEqual(candidates,[])
            finally:
                state.close()

    def test_delivery_error_retried_without_fake_success(self):
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=([],[])):
            record=pole(1_300_000)
            result=run_once(self.config,now_ms=1_600_000,
                collector=lambda *_a,**_k:snapshots(record),
                activity_sender=lambda *_:(_ for _ in ()).throw(RuntimeError("Toast unavailable")))
            self.assertEqual(result["clean_notifications_sent"],0)
            self.assertEqual(result["clean_notifications_failed"],1)
            self.assertEqual(result["alerts_delivery_failed"],1)
            success=run_once(self.config,now_ms=1_660_000,
                collector=lambda *_a,**_k:snapshots(record),
                activity_sender=lambda *_:None)
        self.assertEqual(success["clean_notifications_sent"],1)

    def test_status_heartbeat_even_when_no_new_data(self):
        # 60 minutes have elapsed since enable; the watcher is still active.
        summary=[]
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=([],[])):
            first=run_once(self.config,now_ms=4_800_000,
                collector=lambda *_a,**_k:snapshots(),
                heartbeat_sender=lambda data,_conf:summary.append(data))
            self.assertEqual(first["heartbeat_sent"],1)
            self.assertEqual(summary[0]["recent_events"],0)
            self.assertEqual(summary[0]["period_minutes"],60)
            second=run_once(self.config,now_ms=4_820_000,
                collector=lambda *_a,**_k:snapshots(),
                heartbeat_sender=lambda *_:self.fail("repeated heartbeat"))
        self.assertEqual(second["heartbeat_sent"],0)

    def test_no_activity_when_not_opted_in(self):
        config=dict(CONFIG)
        config.pop("activity_notifications_enabled")
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=([],[])):
            self.config.write_text(json.dumps(config),encoding="utf-8")
            result=run_once(self.config,now_ms=1_600_000,
                collector=lambda *_a,**_k:snapshots(pole(1_300_000)),
                activity_sender=lambda *_:self.fail("not enabled"))
        self.assertNotIn("clean_notifications_sent",result)

    def test_activity_history_separate_from_flagged_inbox(self):
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=([],[])):
            run_once(self.config,now_ms=1_600_000,
                collector=lambda *_a,**_k:snapshots(pole(1_300_000)),
                activity_sender=lambda *_:None)
        state=State(self.config.with_suffix(".sqlite3"))
        try:
            logs=list_recent_activity(state.db)
            self.assertEqual(len(logs),1)
            self.assertEqual(logs[0]["objectid"],12)
            self.assertEqual(state.db.execute("SELECT COUNT(*) FROM alert_inbox").fetchone()[0],0)
        finally:
            state.close()


if __name__=="__main__":
    unittest.main()

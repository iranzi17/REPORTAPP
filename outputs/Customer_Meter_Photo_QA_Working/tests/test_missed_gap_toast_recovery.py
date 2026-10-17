"""Recover missed QA banners without changing REG data or watcher state."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meter_photo_qa.notification_inbox import (
    connect_inbox, record_alert, mark_delivery, get_alert, resend_saved_alert,
)
from meter_photo_qa.surveyor_notifications import deliver
from meter_photo_qa.surveyor_activity import deliver_clean_digest
from meter_photo_qa.desktop_toast_channel import DESKTOP_APP_ID

EXACT_ID="{142A4DBA-F393-4597-90A9-3878A86827B9}"
EVENT_MS=1792258755000


class MissedGapToastTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config=Path(self.temp.name)/"monitor_config.json"
        self.config.write_text(json.dumps({"enabled":True, "channel":"desktop",
                          "version":"sde.DEFAULT","usernames":["julesmugae72"]}),
                          encoding="utf-8")
        self.record={
            "asset":"pole","objectid":4448691,"globalid":EXACT_ID,
            "username":"julesmugae72","event_type":"CREATE",
            "created_user":"julesmugae72","last_edited_user":"julesmugae72",
            "event_time_utc_ms":EVENT_MS,
            "issues":["Append Cable missing","Pole height missing"],
            "issue_digest":"unchanged-digest",
        }
        db=connect_inbox(self.config)
        try:
            self.id=record_alert(db,self.record,EVENT_MS+365000)
            mark_delivery(db,self.id,"SENT")
        finally:
            db.close()

    def test_reissue_preserves_alert_state_and_does_not_query_implicitly(self):
        calls=[]
        def verify(alert, config):
            calls.append(("verify", alert.copy()))
            self.assertEqual(alert["globalid"],EXACT_ID)
            self.assertEqual(alert["event_time_utc_ms"],EVENT_MS)
            self.assertEqual(config["version"],"sde.DEFAULT")
            return "reportapp://zoom/pole/4448691?verified"
        def send(alert,config):
            self.assertEqual(calls[0][0],"verify")
            calls.append(("send", alert.copy()))
        before=connect_inbox(self.config)
        try:
            saved_before=get_alert(before,self.id)
        finally:
            before.close()
        result=resend_saved_alert(
            self.config,self.id,source_verifier=verify,sender=send)
        self.assertEqual(result["status"],"REISSUED_TO_WINDOWS_NOT_VIEW_CONFIRMED")
        self.assertEqual([v[0] for v in calls],["verify","send"])
        after=connect_inbox(self.config)
        try:
            saved_after=get_alert(after,self.id)
            sent_state=after.execute("SELECT COUNT(*) FROM sent").fetchone() if any(
                x[0]=="sent" for x in after.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")) else None
        finally:
            after.close()
        self.assertEqual(saved_before,saved_after)
        self.assertIsNone(sent_state)
        self.assertFalse(result["database_changed"])

    def test_stale_source_refuses_popup(self):
        sent=Mock()
        with self.assertRaisesRegex(ValueError,"source edit changed"):
            resend_saved_alert(
                self.config,self.id,
                source_verifier=lambda *_: (_ for _ in ()).throw(
                    ValueError("source edit changed")),
                sender=sent,
            )
        sent.assert_not_called()

    def test_legacy_inbox_row_cannot_be_replayed_as_verified(self):
        db=connect_inbox(self.config)
        try:
            db.execute("UPDATE alert_inbox SET origin='LEGACY' WHERE id=?",(self.id,))
            db.commit()
        finally: db.close()
        with self.assertRaisesRegex(ValueError,"LIVE"):
            resend_saved_alert(self.config,self.id,
                               source_verifier=Mock(),sender=Mock())

    def test_failed_delivery_not_misrepresented_as_dispatched(self):
        db=connect_inbox(self.config)
        try:
            mark_delivery(db,self.id,"SEND_FAILED","Windows denied toast")
        finally: db.close()
        with self.assertRaisesRegex(ValueError,"LIVE"):
            resend_saved_alert(self.config,self.id,
                               source_verifier=Mock(),sender=Mock())

    def test_windows_gap_and_clean_digest_share_working_identity(self):
        assert DESKTOP_APP_ID=="REPORTAPP Surveyor Activity"
        toast=Mock()
        notification=Mock(return_value=toast)
        with patch.dict("sys.modules",{
                "winotify":SimpleNamespace(Notification=notification),
            }), patch("meter_photo_qa.alert_navigation.is_registered",
                      return_value=False):
            deliver(self.record,{"channel":"desktop","version":"sde.DEFAULT"})
            self.assertEqual(notification.call_args.kwargs["app_id"],DESKTOP_APP_ID)
            self.assertIn("gaps",notification.call_args.kwargs["title"])
            toast.show.assert_called_once()
            notification.reset_mock()
            toast.reset_mock()
            deliver_clean_digest({
                "total":2,"by_asset":{"pole":2,"line":0,"transformer":0},
                "surveyor_count":1,"created":2,"edited":0,"historical":0,
            },{"channel":"desktop"})
            self.assertEqual(notification.call_args.kwargs["app_id"],DESKTOP_APP_ID)
            self.assertIn("no-gap records",notification.call_args.kwargs["title"])
            toast.show.assert_called_once()


if __name__=="__main__":
    unittest.main()

from __future__ import annotations

from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meter_photo_qa.deferred_notifications import (
    RWANDA_TZ,is_historical,site_active,ensure_schema,plan_delivery,
    mark_delivered,change_site_mode,MAX_LATE_PER_CYCLE
)
from meter_photo_qa.surveyor_notifications import State,run_once

def local_ms(year,month,day,hour,minute=0):
    return int(datetime(year,month,day,hour,minute,tzinfo=RWANDA_TZ).timestamp()*1000)

def alert(objectid,event_ms):
    return dict(
        asset="pole",objectid=objectid,globalid="{G"+str(objectid)+"}",
        event_time_utc_ms=event_ms,username="survey",
        event_type="EDIT",created_user="survey",
        last_edited_user="survey",issues=["Append Cable missing"],
        issue_digest="digest-"+str(objectid),
    )

def snapshot(*items):
    return {"pole":(items,[],{},None,None)}

def source_record(item):
    return dict(OBJECTID=item["objectid"],GLOBALID=item["globalid"])


class DeferredNotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=Path(self.tmp.name)
        self.state=State(self.folder/"monitor.sqlite3")
        self.now=local_ms(2026,10,16,11)
        self.yesterday=local_ms(2026,10,15,16)
        self.today=local_ms(2026,10,16,10)
        self.conf={
            "enabled":True,"enabled_at_utc_ms":local_ms(2026,10,1,10),
            "usernames":["survey"],"assets":["pole"],
            "surveyor_site_mode":"on_site","channel":"desktop",
        }

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def test_old_clean_activity_waits_for_offsite_and_survives_24h(self):
        from meter_photo_qa.surveyor_activity import process_activity
        item={
            "OBJECTID":51,"GLOBALID":"{G51}","ASSETGROUP":7,
            "ASSETTYPE":2,"created_user":"survey",
            "last_edited_user":"survey","created_date":self.yesterday,
            "last_edited_date":self.yesterday,
        }
        conf=dict(self.conf,activity_notifications_enabled=True,
                  activity_notifications_enabled_at_utc_ms=local_ms(2026,10,15,10),
                  activity_heartbeat_minutes=60)
        notices=[]
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=([],[])):
            first=process_activity(
                snapshot(item),conf,self.now,self.state.db,
                {"records_scanned":{"pole":1},"qa_alerts_sent":0},
                clean_sender=lambda entry,_:notices.append(entry),
                heartbeat_sender=lambda *_:None,
            )
            self.assertEqual(first["clean_notifications_sent"],0)
            self.assertEqual(first["clean_historical_queued"],1)
            self.assertEqual(notices,[])
            conf["surveyor_site_mode"]="off_site"
            after=local_ms(2026,10,17,18)
            second=process_activity(
                snapshot(),conf,after,self.state.db,
                {"records_scanned":{"pole":0},"qa_alerts_sent":0},
                clean_sender=lambda entry,_:notices.append(entry),
                heartbeat_sender=lambda *_:None,
            )
            self.assertEqual(second["clean_notifications_sent"],1)
            self.assertEqual(second["clean_historical_queued"],0)
            self.assertEqual(notices[0]["historical"],1)
            self.assertEqual(notices[0]["total"],1)
            third=process_activity(
                snapshot(),conf,after+60000,self.state.db,
                {"records_scanned":{"pole":0},"qa_alerts_sent":0},
                clean_sender=lambda *_:self.fail("old clean event repeated"),
                heartbeat_sender=lambda *_:None,
            )
            self.assertEqual(third["clean_notifications_sent"],0)

    def test_queued_clean_record_not_delivered_after_later_faulty_edit(self):
        from meter_photo_qa.surveyor_activity import process_activity
        conf=dict(self.conf,activity_notifications_enabled=True,
                  activity_notifications_enabled_at_utc_ms=local_ms(2026,10,15,10),
                  activity_heartbeat_minutes=60)
        item={
            "OBJECTID":55,"GLOBALID":"{G55}","ASSETGROUP":7,
            "ASSETTYPE":2,"created_user":"survey",
            "last_edited_user":"survey","created_date":self.yesterday,
            "last_edited_date":self.yesterday,
        }
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=([],[])):
            process_activity(
                snapshot(item),conf,self.now,self.state.db,
                {"records_scanned":{"pole":1},"qa_alerts_sent":0},
                clean_sender=lambda *_:self.fail("premature clean"),
                heartbeat_sender=lambda *_:None,
            )
        item["last_edited_date"]=self.today
        with patch("meter_photo_qa.surveyor_notifications.record_findings",
                   return_value=(["Append Cable missing"],[])):
            outcome=process_activity(
                snapshot(item),conf,self.now+60000,self.state.db,
                {"records_scanned":{"pole":1},"qa_alerts_sent":1},
                clean_sender=lambda *_:self.fail("not QA-clean"),
                heartbeat_sender=lambda *_:None,
            )
        self.assertEqual(outcome["clean_historical_queued"],0)

    def test_historical_is_rwanda_date_not_utc(self):
        local_just_after_midnight=local_ms(2026,10,16,0,20)
        local_previous=local_ms(2026,10,15,23,59)
        self.assertTrue(is_historical(local_previous,local_just_after_midnight))
        self.assertFalse(is_historical(local_just_after_midnight,local_just_after_midnight))

    def test_today_immediate_and_yesterday_queued(self):
        old,new=alert(11,self.yesterday),alert(12,self.today)
        snaps=snapshot(source_record(old),source_record(new))
        deliveries,queued=plan_delivery([old,new],snaps,self.conf,self.now,self.state.db)
        self.assertEqual([x["objectid"] for x in deliveries],[12])
        self.assertEqual(queued,1)
        self.assertEqual(self.state.db.execute(
            "SELECT COUNT(*) FROM delayed_qa_notifications").fetchone()[0],1)

    def test_pending_stays_after_24h_scan_window_then_released_offsite(self):
        old=alert(11,self.yesterday)
        plan_delivery([old],snapshot(source_record(old)),self.conf,self.now,self.state.db)
        after=local_ms(2026,10,17,18)
        self.conf["surveyor_site_mode"]="off_site"
        deliveries,_=plan_delivery([],snapshot(),self.conf,after,self.state.db)
        self.assertEqual([x["objectid"] for x in deliveries],[11])
        self.assertTrue(deliveries[0]["deferred_historical"])
        mark_delivered(self.state.db,deliveries[0])
        again,_=plan_delivery([],snapshot(),self.conf,after+60000,self.state.db)
        self.assertEqual(again,[])

    def test_fixed_records_remove_pending_without_alert(self):
        old=alert(21,self.yesterday)
        plan_delivery([old],snapshot(source_record(old)),self.conf,self.now,self.state.db)
        # The changed record is now present but no longer flagged.
        deliveries,count=plan_delivery(
            [],snapshot(source_record(old)),self.conf,self.now+60000,self.state.db
        )
        self.assertEqual(deliveries,[])
        self.assertEqual(count,0)

    def test_offsite_caps_delayed_notifications(self):
        notices=[alert(100+i,self.yesterday) for i in range(12)]
        plan_delivery(notices,snapshot(*(source_record(x) for x in notices)),
                      self.conf,self.now,self.state.db)
        self.conf["surveyor_site_mode"]="off_site"
        deliveries,count=plan_delivery([],snapshot(),self.conf,self.now+60000,self.state.db)
        self.assertEqual(len(deliveries),MAX_LATE_PER_CYCLE)
        self.assertEqual(count,12)

    def test_no_schedule_defaults_on_site_and_schedule_is_configurable(self):
        self.assertTrue(site_active({},self.now))
        self.assertTrue(site_active({"surveyor_site_mode":"schedule"},self.now))
        cfg={"surveyor_site_mode":"schedule","surveyor_site_schedule":{
            "start":"08:00","end":"17:00","weekdays":[0,1,2,3,4]
        }}
        self.assertTrue(site_active(cfg,local_ms(2026,10,16,11)))
        self.assertFalse(site_active(cfg,local_ms(2026,10,16,18)))
        self.assertFalse(site_active(cfg,local_ms(2026,10,17,11)))

    def test_changing_mode_preserves_all_config_and_alert_history(self):
        file=self.folder/"monitor_config.json"
        file.write_text(json.dumps(self.conf),encoding="utf-8")
        saved=self.state.path.read_bytes()
        result=change_site_mode(file,"off_site")
        self.assertEqual(result["status"],"UPDATED")
        after=json.loads(file.read_text())
        for key,value in self.conf.items():
            self.assertEqual(after[key],value if key!="surveyor_site_mode" else "off_site")
        self.assertEqual(self.state.path.read_bytes(),saved)
        self.assertEqual(len(list(self.folder.glob("*_backup_site_*.json"))),1)

    def test_bad_site_schedule_rejected_without_mutation(self):
        file=self.folder/"monitor_config.json"
        content=json.dumps(self.conf)
        file.write_text(content)
        with self.assertRaises(ValueError):
            change_site_mode(file,"schedule",schedule={
                "start":"17:00","end":"08:00","weekdays":[0,1,2,3,4]
            })
        self.assertEqual(file.read_text(),content)

    def test_actual_run_queues_old_without_email_or_toast(self):
        file=self.folder/"monitor_config.json"
        file.write_text(json.dumps(self.conf))
        old,new=alert(11,self.yesterday),alert(12,self.today)
        scanned=[
            dict(source_record(x),
                 created_user="survey",last_edited_user="survey",
                 created_date=x["event_time_utc_ms"],
                 last_edited_date=x["event_time_utc_ms"])
            for x in (old,new)
        ]
        notices=[old,new]
        sent=[]
        with patch("meter_photo_qa.surveyor_notifications.ready_alerts",
                   return_value=notices):
            response=run_once(
                file,now_ms=self.now,
                collector=lambda conf,now_ms=None:snapshot(*scanned),
                sender=lambda event,_:sent.append(event),
            )
        self.assertEqual([x["objectid"] for x in sent],[12])
        self.assertEqual(response["historical_alerts_queued"],1)
        self.assertEqual(response["alerts_sent"],1)


if __name__=="__main__":
    unittest.main()

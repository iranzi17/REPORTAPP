from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meter_photo_qa.surveyor_notifications import (
    State,ready_alerts,run_once,event_timestamp,preflight,_monitor_gis,
)
from meter_photo_qa.notification_setup import (
    configure_monitoring,chosen_usernames,_powershell,_standalone_python,
)


def pole(edited,notes="",append="No",height=13.5,manufacturer="Good Company"):
    return {
        "OBJECTID":201,"GLOBALID":"{G201}","ASSETGROUP":7,"ASSETTYPE":2,
        "created_user":"ninamenye9683",
        "created_date":edited,
        "last_edited_date":edited,
        "last_edited_user":"ninamenye9683",
        "Manufacturers":manufacturer,
        "Append_Cable":append,
        "Pole_Height":height,"Notes":notes,
    }

FIELDS=[
    {"name":"Manufacturers"},{"name":"Append_Cable"},
    {"name":"Pole_Height"},{"name":"Notes"},
]
CONFIG={"enabled":True,"usernames":["ninamenye9683"],"assets":["pole"],
        "channel":"desktop","enabled_at_utc_ms":1000*1000}


class NotificationTests(unittest.TestCase):
    def test_preflight_queries_all_selected_assets_without_issuing_alerts(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG),encoding="utf-8")
            result=preflight(
                cfg,check_delivery=False,now_ms=1400*1000,
                collector=lambda conf,now_ms=None:{
                    "pole":([pole(1100*1000)],FIELDS,{},None,None)
                },
            )
            self.assertEqual(result["status"],"PREFLIGHT_OK")
            self.assertEqual(result["notifications_sent"],0)
            self.assertEqual(result["asset_record_counts"],{"pole":1})
            self.assertFalse(cfg.with_suffix(".sqlite3").exists())
            self.assertEqual(list(Path(folder).iterdir()),[cfg])

    def test_preflight_fails_closed_on_missing_asset_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG),encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"Incomplete monitoring scan"):
                preflight(
                    cfg,check_delivery=False,
                    collector=lambda conf,now_ms=None:{},
                )

    def test_gis_profile_only_when_explicitly_configured(self):
        sentinel=object()
        self.assertIs(_monitor_gis({"arcgis_profile":""},sentinel),sentinel)
        with patch("meter_photo_qa.surveyor_notifications._get_gis",
                   return_value=sentinel) as default_gis, \
             patch.dict("os.environ",{"REPORTAPP_ARCGIS_PROFILE":""}):
            self.assertIs(_monitor_gis({}),sentinel)
            default_gis.assert_called_once_with(None)
        with patch("meter_photo_qa.surveyor_notifications._get_gis",
                   side_effect=RuntimeError("No Pro session")), \
             patch.dict("os.environ",{"REPORTAPP_ARCGIS_PROFILE":""}):
            with self.assertRaisesRegex(RuntimeError,"--preflight"):
                _monitor_gis({})

    def test_run_once_reports_scanned_records_and_delivery_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG),encoding="utf-8")
            response=run_once(
                cfg,now_ms=1400*1000,
                collector=lambda conf,now_ms=None:{
                    "pole":([pole(1100*1000)],FIELDS,{},None,None)
                },
                sender=lambda alert,conf:(_ for _ in ()).throw(
                    RuntimeError("Toast denied")
                ),
            )
            self.assertEqual(response["records_scanned"],{"pole":1})
            self.assertEqual(response["alerts_delivery_failed"],1)
            self.assertEqual(response["alerts_sent"],0)

    def test_matures_after_five_minutes_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG),encoding="utf-8")
            edited=1100*1000
            record=pole(edited)
            sent=[]
            def sender(alert,config):
                sent.append(alert)
            def collector(config,now_ms=None):
                return {"pole":([record],FIELDS,{},None,None)}
            response=run_once(cfg,now_ms=1399*1000,collector=collector,
                              sender=sender)
            self.assertEqual(response["alerts_sent"],0)
            self.assertEqual(run_once(
                cfg,now_ms=1400*1000,collector=collector,sender=sender
            )["alerts_sent"],1)
            self.assertEqual(len(sent),1)
            self.assertIn("Pole height > 12",sent[0]["issues"][0])
            self.assertEqual(run_once(
                cfg,now_ms=1461*1000,collector=collector,sender=sender
            )["alerts_sent"],0)
            self.assertIn('"status": "SENT"',cfg.with_suffix(".events.jsonl").read_text())

    def test_latest_editor_is_not_confused_with_record_creator(self):
        from meter_photo_qa.surveyor_notifications import submission_actor
        record=pole(1100*1000)
        record["created_date"]=1050*1000
        record["last_edited_date"]=1100*1000
        record["created_user"]="someone_else"
        record["last_edited_user"]="ninamenye9683"
        self.assertEqual(submission_actor(record),("ninamenye9683","EDIT"))
        with tempfile.TemporaryDirectory() as folder:
            state=State(Path(folder)/"s.sqlite")
            try:
                alerts=ready_alerts(
                    [record],"pole",FIELDS,{},CONFIG,1400*1000,state
                )
                self.assertEqual(len(alerts),1)
                self.assertEqual(alerts[0]["event_type"],"EDIT")
                self.assertEqual(alerts[0]["created_user"],"someone_else")
                record["created_user"]="ninamenye9683"
                record["last_edited_user"]="different"
                alerts=ready_alerts(
                    [record],"pole",FIELDS,{},CONFIG,1400*1000,state
                )
                self.assertEqual(alerts,[])
            finally:state.close()

    def test_nameplate_note_does_not_exempt_large_pole(self):
        with tempfile.TemporaryDirectory() as folder:
            state=State(Path(folder)/"s.sqlite")
            try:
                edited=1100*1000
                issues=ready_alerts(
                    [pole(edited,notes="No name plate")],
                    "pole",FIELDS,{},CONFIG,1500*1000,state
                )[0]["issues"]
                self.assertTrue(any("height > 12" in issue.lower() for issue in issues))
                self.assertFalse(any("Manufacturer missing" in issue for issue in issues))
            finally:state.close()

    def test_mv_note_allows_large_pole_but_mandatory_append_still_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            state=State(Path(folder)/"s.sqlite")
            try:
                record=pole(1100*1000,"Pole for MV lines",append=None)
                alerts=ready_alerts([record],"pole",FIELDS,{},CONFIG,1500*1000,state)
                self.assertEqual(len(alerts),1)
                self.assertEqual(
                    alerts[0]["issues"],
                    ["Append Cable missing/unknown (mandatory LV pole field)"]
                )
            finally:state.close()

    def test_unwatched_and_existing_before_monitor_enable_never_alerted(self):
        with tempfile.TemporaryDirectory() as folder:
            state=State(Path(folder)/"s.sqlite")
            try:
                old=pole(990*1000)
                watched=pole(1100*1000)
                watched["created_user"]="different_login"
                self.assertEqual(ready_alerts(
                    [old,watched],"pole",FIELDS,{},CONFIG,1800*1000,state
                ),[])
            finally:state.close()

    def test_alert_fails_retry_and_corrected_state_clears(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG))
            current=pole(1100*1000)
            sent=[]
            def collector(config,now_ms=None):
                return {"pole":([current],FIELDS,{},None,None)}
            def fail(alert,config):raise RuntimeError("notifications blocked")
            self.assertEqual(run_once(
                cfg,now_ms=1400*1000,collector=collector,sender=fail
            )["alerts_sent"],0)
            self.assertEqual(run_once(
                cfg,now_ms=1460*1000,collector=collector,
                sender=lambda alert,config:sent.append(alert)
            )["alerts_sent"],1)
            # Surveyor fixes Notes, and the record is updated later.
            current=pole(1500*1000,notes="HV tower")
            self.assertEqual(run_once(
                cfg,now_ms=1810*1000,collector=collector,
                sender=lambda alert,config:sent.append(alert)
            )["alerts_sent"],0)
            current=pole(1900*1000,notes="No mention")
            self.assertEqual(run_once(
                cfg,now_ms=2200*1000,collector=collector,
                sender=lambda alert,config:sent.append(alert)
            )["alerts_sent"],1)
            self.assertEqual(len(sent),2)

    def test_embedded_arcgispro_process_is_not_scheduled_as_python(self):
        import sys
        with tempfile.TemporaryDirectory() as folder:
            prog=Path(folder)/"ArcGISPro.exe"
            prog.touch()
            env=Path(folder)/"arcgispro-py3"
            env.mkdir()
            standalone=env/"python.exe"
            standalone.touch()
            with patch.object(sys,"prefix",str(env)), \
                 patch.object(sys,"exec_prefix",str(env)):
                self.assertEqual(_standalone_python(prog),standalone)
                script=_powershell("C:/test/config.json",prog,folder)
                self.assertIn(str(standalone),script)
                self.assertNotIn(str(prog),script)
            with patch.object(sys,"prefix",str(Path(folder)/"missing")), \
                 patch.object(sys,"exec_prefix",str(Path(folder)/"missing")):
                with self.assertRaisesRegex(RuntimeError,"standalone Python"):
                    _standalone_python(prog)

    def test_setup_selects_explicit_accounts_and_does_not_start_task(self):
        with tempfile.TemporaryDirectory() as folder:
            py=Path(folder)/"python.exe";py.touch()
            source=Path(folder)/"src";source.mkdir()
            result=configure_monitoring(
                ["ninamenye9683 — Kwizerwa Edison",
                 "maniraguhatheogene01 — Ringuyeneza Frederic"],
                folder,src_path=source,python_path=py,now_ms=1950000,
            )
            self.assertEqual(result["watching_usernames"],
                             ["ninamenye9683","maniraguhatheogene01"])
            self.assertFalse(result["actively_running"])
            config=json.loads(Path(result["configuration"]).read_text())
            self.assertEqual(config["enabled_at_utc_ms"],1950000)
            script=Path(result["installation_script"]).read_text(encoding="utf-8-sig")
            self.assertIn("New-ScheduledTaskTrigger",script)
            self.assertIn("RepetitionInterval",script)
            self.assertIn("Interactive",script)
            self.assertIn(str(source),script)
            with self.assertRaises(FileExistsError):
                configure_monitoring(["ninamenye9683"],folder,
                    src_path=source,python_path=py)
            updated=configure_monitoring(["janviersafari515"],folder,
                replace_existing=True,src_path=source,python_path=py,
                now_ms=2200000)
            self.assertEqual(updated["watching_usernames"],["janviersafari515"])

    def test_selected_accounts_required(self):
        with self.assertRaises(ValueError):
            chosen_usernames([])
        with self.assertRaises(ValueError):
            chosen_usernames(["Nonexisting Surveyor Name"])


if __name__=="__main__":
    unittest.main()

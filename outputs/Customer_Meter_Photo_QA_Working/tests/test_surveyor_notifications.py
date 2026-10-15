from __future__ import annotations

import datetime as std_datetime
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stderr

from meter_photo_qa.surveyor_notifications import (
    State,ready_alerts,run_once,event_timestamp,preflight,_monitor_gis,
)
from meter_photo_qa.notification_setup import (
    configure_monitoring,chosen_usernames,_powershell,_standalone_python,
    update_monitored_surveyors,update_monitored_assets,
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
        "Service_Pole":"No","PoleStructure":1,"InsulatorTypes":1,
        "Number_Circuit":1,
    }

FIELDS=[
    {"name":"Manufacturers"},{"name":"Append_Cable"},
    {"name":"Pole_Height"},{"name":"Notes"},
    {"name":"Service_Pole"},{"name":"PoleStructure"},
    {"name":"InsulatorTypes"},{"name":"Number_Circuit"},
]
CONFIG={"enabled":True,"usernames":["ninamenye9683"],"assets":["pole"],
        "channel":"desktop","enabled_at_utc_ms":1000*1000}


class NotificationTests(unittest.TestCase):
    def test_preflight_datetime_module_shadow_does_not_break_runtime(self):
        # The actual ArcGIS Pro traceback exposed 'datetime' as a module,
        # which caused the preflight and its exception logger to fail.
        import meter_photo_qa.surveyor_notifications as monitor
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG),encoding="utf-8")
            with patch.object(monitor,"datetime",std_datetime,create=True):
                info=preflight(
                    cfg, check_delivery=False,
                    collector=lambda config,now_ms=None:{
                        "pole":([pole(1100*1000)],FIELDS,{},None,None)
                    },
                )
            self.assertEqual(info["status"],"PREFLIGHT_OK")

    def test_command_line_error_cannot_be_hidden_by_logger(self):
        import meter_photo_qa.surveyor_notifications as monitor
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"monitor_config.json"
            cfg.write_text(json.dumps(CONFIG),encoding="utf-8")
            error_output=io.StringIO()
            with patch.object(monitor,"datetime",std_datetime,create=True), \
                 patch.object(monitor,"preflight",side_effect=RuntimeError("GIS offline")), \
                 redirect_stderr(error_output):
                result=monitor.main(["--config",str(cfg),"--preflight"])
            self.assertEqual(result,1)
            self.assertIn("GIS offline",error_output.getvalue())
            self.assertIn("GIS offline",cfg.with_suffix(".monitor.log").read_text())

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

    def test_new_pole_attributes_and_manufacturer_notes_reach_live_alerts(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            state=State(Path(folder)/"monitor.sqlite3")
            try:
                entry=pole(1100000,notes="Pole inspected",manufacturer=None,
                           height=10)
                entry.update({
                    "Service_Pole":None,"PoleStructure":None,
                    "InsulatorTypes":"Unknown","Number_Circuit":0,
                })
                issues=ready_alerts(
                    [entry],"pole",FIELDS,{},CONFIG,1400000,state
                )[0]["issues"]
                self.assertEqual(len(issues),4)
                self.assertTrue(any("Service Pole missing" in x for x in issues))
                self.assertTrue(any("Structure missing" in x for x in issues))
                self.assertTrue(any("Insulator Type missing" in x for x in issues))
                self.assertTrue(any("positive whole number" in x for x in issues))
                self.assertFalse(any("Manufacturer missing" in x for x in issues))
                entry["Notes"]=""
                issues=ready_alerts(
                    [entry],"pole",FIELDS,{},CONFIG,1400000,state
                )[0]["issues"]
                self.assertEqual(len(issues),5)
                self.assertIn("Manufacturer missing and Notes empty",issues)
            finally:
                state.close()

    def test_substandard_structure_does_not_alert_missing_manufacturer(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            state=State(Path(folder)/"state.sqlite")
            try:
                sample=pole(1100000,notes="",manufacturer=None,height=10)
                sample["PoleStructure"]=4
                issues=ready_alerts(
                    [sample],"pole",FIELDS,{"PoleStructure":{4:"Substandard"}},
                    CONFIG,1400000,state,
                )
                self.assertEqual(issues,[])
                sample["Append_Cable"]=None
                issues=ready_alerts(
                    [sample],"pole",FIELDS,{"PoleStructure":{4:"Substandard"}},
                    CONFIG,1400000,state,
                )
                self.assertEqual(len(issues),1)
                self.assertIn("Append Cable",issues[0]["issues"][0])
                sample["PoleStructure"]=5
                issues=ready_alerts(
                    [sample],"pole",FIELDS,{"PoleStructure":{4:"Substandard",5:"Standard"}},
                    CONFIG,1400000,state,
                )
                self.assertEqual(len(issues),1)
                self.assertTrue(any("Manufacturer missing" in issue
                                    for issue in issues[0]["issues"]))
            finally:
                state.close()

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
            self.assertIn("-RunLevel Limited",script)
            self.assertNotIn("-RunLevel LeastPrivilege",script)
            self.assertIn(str(source),script)
            with self.assertRaises(FileExistsError):
                configure_monitoring(["ninamenye9683"],folder,
                    src_path=source,python_path=py)
            updated=configure_monitoring(["janviersafari515"],folder,
                replace_existing=True,src_path=source,python_path=py,
                now_ms=2200000)
            self.assertEqual(updated["watching_usernames"],["janviersafari515"])

    def test_incremental_surveyor_management_preserves_start_and_inbox(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path=Path(folder)/"monitor_config.json"
            config={"enabled":True,"enabled_at_utc_ms":1000000,
                    "usernames":["ninamenye9683"],"assets":["pole"],
                    "channel":"desktop"}
            path.write_text(json.dumps(config),encoding="utf-8")
            archive=path.with_suffix(".sqlite3")
            archive.write_text("sentinel",encoding="utf-8")
            result=update_monitored_surveyors(
                path,add=["janviersafari515"],now_ms=2000000
            )
            self.assertEqual(result["status"],"UPDATED")
            conf=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(conf["usernames"],["ninamenye9683","janviersafari515"])
            self.assertEqual(conf["enabled_at_utc_ms"],1000000)
            self.assertEqual(conf["enabled_at_by_username_utc_ms"],
                             {"ninamenye9683":1000000,"janviersafari515":2000000})
            self.assertEqual(archive.read_text(),"sentinel")
            self.assertEqual(len(list(Path(folder).glob("*backup_*.json"))),1)
            again=update_monitored_surveyors(
                path,add=["janviersafari515"],now_ms=2100000
            )
            self.assertEqual(again["status"],"UNCHANGED")
            still=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(still["enabled_at_by_username_utc_ms"]["janviersafari515"],2000000)
            removed=update_monitored_surveyors(
                path,remove=["ninamenye9683"],now_ms=2200000
            )
            self.assertEqual(removed["removed"],["ninamenye9683"])
            self.assertEqual(json.loads(path.read_text())["usernames"],["janviersafari515"])
            with self.assertRaisesRegex(ValueError,"last monitored"):
                update_monitored_surveyors(path,remove=["janviersafari515"],now_ms=2300000)

    def test_newly_added_surveyor_has_no_retroactive_alerts(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            config=dict(CONFIG)
            config["enabled_at_by_username_utc_ms"]={
                "ninamenye9683":1000000,"janviersafari515":2000000
            }
            config["usernames"]=["ninamenye9683","janviersafari515"]
            state=State(Path(folder)/"monitor.sqlite3")
            try:
                old=pole(1500000)
                old["created_user"]="janviersafari515"
                old["last_edited_user"]="janviersafari515"
                self.assertEqual(ready_alerts(
                    [old],"pole",FIELDS,{},config,2400000,state
                ),[])
                old["created_date"]=2100000
                old["last_edited_date"]=2100000
                self.assertEqual(len(ready_alerts(
                    [old],"pole",FIELDS,{},config,2400000,state
                )),1)
            finally:
                state.close()

    def test_add_line_transformer_preserves_existing_pole_and_user_clocks(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path=Path(directory)/"monitor_config.json"
            original={
                "enabled":True,"enabled_at_utc_ms":1000000,
                "enabled_at_by_username_utc_ms":{
                    "ninamenye9683":1000000,
                    "janviersafari515":1700000,
                },
                "usernames":["ninamenye9683","janviersafari515"],
                "assets":["pole"],"channel":"desktop",
            }
            path.write_text(json.dumps(original),encoding="utf-8")
            state=State(path.with_suffix(".sqlite3"))
            state.close()
            watched=[]
            def validator(candidate,now_ms):
                watched.append((candidate,now_ms))
                return {"pole":9,"line":0,"transformer":1}
            result=update_monitored_assets(
                path,["pole","line","transformer"],
                now_ms=2100000,validator=validator,
            )
            self.assertEqual(result["status"],"UPDATED")
            self.assertEqual(result["added"],["line","transformer"])
            self.assertEqual(result["asset_record_counts"]["transformer"],1)
            saved=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["enabled_at_utc_ms"],1000000)
            self.assertEqual(saved["enabled_at_by_username_utc_ms"],
                             original["enabled_at_by_username_utc_ms"])
            self.assertEqual(saved["enabled_at_by_asset_utc_ms"],
                             {"pole":1000000,"line":2100000,"transformer":2100000})
            self.assertEqual(saved["usernames"],original["usernames"])
            self.assertTrue(path.with_suffix(".sqlite3").is_file())
            self.assertEqual(len(watched),1)
            unchanged=update_monitored_assets(
                path,["transformer","pole","line"],now_ms=2200000,
                validator=lambda *_:self.fail("Unexpected preflight"),
            )
            self.assertEqual(unchanged["status"],"UNCHANGED")

    def test_asset_preflight_error_leaves_config_and_db_unchanged(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path=Path(directory)/"monitor_config.json"
            initial=json.dumps(dict(CONFIG))
            path.write_text(initial,encoding="utf-8")
            sqlite=path.with_suffix(".sqlite3")
            sqlite.write_bytes(b"EXISTING-DATA")
            def error(candidate,stamp):
                self.assertEqual(set(candidate["assets"]),{"pole","line"})
                raise RuntimeError("Line schema validation failed")
            with self.assertRaisesRegex(RuntimeError,"Line schema validation failed"):
                update_monitored_assets(
                    path,["pole","line"],now_ms=2000000,validator=error
                )
            self.assertEqual(path.read_text(encoding="utf-8"),initial)
            self.assertEqual(sqlite.read_bytes(),b"EXISTING-DATA")
            self.assertEqual(len(list(Path(directory).glob("*backup_*.json"))),0)

    def test_asset_cutoff_ignores_old_records_for_new_asset(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            state=State(Path(directory)/"state.db")
            try:
                conf=dict(CONFIG)
                conf["assets"]=["pole","line"]
                conf["enabled_at_by_asset_utc_ms"]={
                    "pole":1000000,"line":2000000
                }
                record={
                    "OBJECTID":800,"GLOBALID":"{LINE-800}",
                    "created_user":"ninamenye9683",
                    "last_edited_user":"ninamenye9683",
                    "created_date":1500000,"last_edited_date":1500000,
                }
                with patch(
                    "meter_photo_qa.surveyor_notifications.record_findings",
                    return_value=(["Missing conductor attribute"],[]),
                ):
                    self.assertEqual(ready_alerts(
                        [record],"line",[],{},conf,2400000,state,
                    ),[])
                    record["created_date"]=2100000
                    record["last_edited_date"]=2100000
                    self.assertEqual(len(ready_alerts(
                        [record],"line",[],{},conf,2400000,state,
                    )),1)
            finally:
                state.close()

    def test_selected_accounts_required(self):
        with self.assertRaises(ValueError):
            chosen_usernames([])
        with self.assertRaises(ValueError):
            chosen_usernames(["Nonexisting Surveyor Name"])


if __name__=="__main__":
    unittest.main()

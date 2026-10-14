from __future__ import annotations

import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class FakeParameter:
    def __init__(self,**kwargs):
        self.name=kwargs.get("name")
        self.filter=SimpleNamespace(type=None,list=[])
        self.value=None
        self.category=None
        self.error=None

    @property
    def valueAsText(self):
        if self.value is None:
            return None
        return str(self.value)

    def setErrorMessage(self, text):
        self.error=text


class ProfileToolUiTests(unittest.TestCase):
    def test_profile_has_all_twelve_confirmed_users_without_override(self):
        fake=SimpleNamespace(
            Parameter=FakeParameter,
            AddMessage=lambda *_args: None,
            AddWarning=lambda *_args: None,
            env=SimpleNamespace(scratchGDB="/tmp/test.gdb"),
            mp=SimpleNamespace(ArcGISProject=lambda _:None),
        )
        with patch.dict(sys.modules,{"arcpy":fake}):
            qa=runpy.run_path(str(ROOT/"CustomerMeterPhotoQA.pyt"))
            tool=qa["ReviewGicumbiPamelaTeam"]()
            params=tool.getParameterInfo()
            self.assertEqual(len(params),8)
            self.assertEqual(params[3].valueAsText,
                "All: LV Lines, Distribution Transformers and LV Poles")
            self.assertEqual(params[4].valueAsText,
                "Mapped Pamela team accounts only (12 confirmed)")
            self.assertEqual(params[5].name,"service_url")
            self.assertEqual(params[1].value.year,2026)
            self.assertEqual(params[1].value.month,9)
            self.assertEqual(params[1].value.day,14)

    def test_execute_propagates_scope_and_warns_of_historical_shared_account(self):
        messages=[]
        fake=SimpleNamespace(
            Parameter=FakeParameter,
            AddMessage=lambda text:messages.append(("message",text)),
            AddWarning=lambda text:messages.append(("warning",text)),
            env=SimpleNamespace(scratchGDB="/tmp/test.gdb"),
        )
        with patch.dict(sys.modules,{"arcpy":fake}):
            qa=runpy.run_path(str(ROOT/"CustomerMeterPhotoQA.pyt"))
            tool=qa["ReviewGicumbiPamelaTeam"]()
            params=tool.getParameterInfo()
            params[0].value="/tmp"
            params[3].value="Distribution Transformers only"
            params[4].value="All accounts in the six sectors (find missing usernames)"
            with patch.dict(qa,{}):
                # The execute method resolves its top-level globals, so
                # replace the function's global runner (not the runpy dict).
                run_fn=tool.execute.__globals__
                original=run_fn["run_gicumbi_pamela_profile"]
                observed={}
                def fake_run(**kwargs):
                    observed.update(kwargs)
                    return {
                        "status":"COMPLETE",
                        "reports":[{"asset":"transformer","checked":0,
                                    "outstanding_features":0,"file":"test.xlsx"}],
                        "manifest_json":"manifest.json","roster_csv":"roster.csv",
                    }
                run_fn["run_gicumbi_pamela_profile"]=fake_run
                try:
                    tool.execute(params,None)
                finally:
                    run_fn["run_gicumbi_pamela_profile"]=original
            self.assertEqual(observed["assets"],"transformer")
            self.assertEqual(observed["scope"],"all_in_assigned_sectors")
            self.assertNotIn("kwizerwa_username",observed)
            self.assertTrue(any("Kwizerwa Edison" in text and "handover date" in text
                                for category,text in messages if category=="warning"))


if __name__=="__main__":
    unittest.main()

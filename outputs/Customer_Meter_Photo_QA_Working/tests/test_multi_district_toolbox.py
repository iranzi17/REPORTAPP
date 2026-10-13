from __future__ import annotations

import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class FakeParameter:
    def __init__(self, **kwargs):
        self.name = kwargs.get("name")
        self.multiValue = kwargs.get("multiValue", False)
        self.filter = SimpleNamespace(type=None, list=[])
        self.value = None
        self.category = None

    @property
    def valueAsText(self):
        return None if self.value is None else str(self.value)


class MultiDistrictToolboxTests(unittest.TestCase):
    def test_multi_picker_and_sector_cell_scope_in_real_toolbox_definition(self):
        fake_arcpy = SimpleNamespace(
            Parameter=FakeParameter,
            env=SimpleNamespace(scratchGDB="/tmp/test.gdb"),
            mp=SimpleNamespace(ArcGISProject=lambda _arg: (_ for _ in ()).throw(
                RuntimeError("No ArcGIS project inside unit test")
            )),
        )
        with patch.dict(sys.modules, {"arcpy": fake_arcpy}):
            toolbox = runpy.run_path(str(ROOT / "CustomerMeterPhotoQA.pyt"))
            for class_name, district_idx, sector_idx, cell_idx in (
                ("WatchLVLineDataQuality", 4, 5, 6),
                ("GenerateSurveyProgressReport", 3, 4, 5),
            ):
                tool = toolbox[class_name]()
                params = tool.getParameterInfo()
                self.assertTrue(params[district_idx].multiValue)
                params[district_idx].value = "Burera;Rulindo;Gakenke"
                tool.updateParameters(params)
                self.assertEqual(len(params[district_idx].valueAsText.split(";")), 3)
                available_sectors = params[sector_idx].filter.list
                self.assertTrue(any(x.startswith("Burera :: ") for x in available_sectors))
                self.assertTrue(any(x.startswith("Rulindo :: ") for x in available_sectors))
                selected_sector = available_sectors[0]
                params[sector_idx].value = selected_sector
                tool.updateParameters(params)
                self.assertEqual(params[sector_idx].valueAsText, selected_sector)
                cells = params[cell_idx].filter.list
                self.assertTrue(cells)
                self.assertTrue(all(x.count(" :: ") == 2 for x in cells))

    def test_unknown_or_ambiguous_sector_is_not_silently_assigned(self):
        fake_arcpy = SimpleNamespace(
            Parameter=FakeParameter,
            env=SimpleNamespace(scratchGDB="/tmp/test.gdb"),
            mp=SimpleNamespace(ArcGISProject=lambda _arg: (_ for _ in ()).throw(
                RuntimeError("No ArcGIS project inside unit test")
            )),
        )
        with patch.dict(sys.modules, {"arcpy": fake_arcpy}):
            toolbox = runpy.run_path(str(ROOT / "CustomerMeterPhotoQA.pyt"))
            watcher = toolbox["WatchLVLineDataQuality"]()
            params = watcher.getParameterInfo()
            params[4].value = "Burera;Rulindo"
            params[5].value = "Completely Unknown Sector"
            watcher.updateParameters(params)
            self.assertIsNone(params[5].valueAsText)


if __name__ == "__main__":
    unittest.main()

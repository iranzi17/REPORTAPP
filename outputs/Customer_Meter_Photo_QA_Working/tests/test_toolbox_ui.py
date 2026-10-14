from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ToolboxUiTests(unittest.TestCase):
    def test_all_country_default_and_separate_network_tools(self):
        qa = runpy.run_path(str(ROOT / "CustomerMeterPhotoQA.pyt"))
        operations = runpy.run_path(str(ROOT / "CustomerMeterPhotoQA_Operations.pyt"))
        self.assertEqual(len(qa["Toolbox"]().tools), 10)
        self.assertIn(qa["WatchDistributionTransformerQuality"], qa["Toolbox"]().tools)
        self.assertIn(qa["WatchLVPoleQuality"], qa["Toolbox"]().tools)
        self.assertIn(qa["ScanAllElectricLineDuplicates"], qa["Toolbox"]().tools)
        self.assertIn(qa["ReviewGicumbiPamelaTeam"], qa["Toolbox"]().tools)
        self.assertIn(qa["AskReportApp"], qa["Toolbox"]().tools)
        self.assertEqual(len(operations["Toolbox"]().tools), 2)
        watcher = qa["WatchLVLineDataQuality"]()
        parameters = watcher.getParameterInfo()
        self.assertEqual(len(parameters[4].filter.list), 30)
        self.assertIsNone(parameters[4].valueAsText)
        self.assertIsNone(parameters[5].valueAsText)
        parameters[4].value = "Gasabo"
        watcher.updateParameters(parameters)
        self.assertEqual(len(parameters[5].filter.list), 15)
        self.assertIsNone(parameters[5].valueAsText)

    def test_rules_file_changes_default_without_replacing_custom_threshold(self):
        qa = runpy.run_path(str(ROOT / "CustomerMeterPhotoQA.pyt"))
        watcher = qa["WatchLVLineDataQuality"]()
        parameters = watcher.getParameterInfo()
        source_rules = json.loads((ROOT / "config" / "lv_line_quality_rules.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            rules_path = Path(folder) / "rules.json"
            source_rules["minimum_completion_percent"] = 80
            rules_path.write_text(json.dumps(source_rules), encoding="utf-8")
            parameters[14].value = str(rules_path)
            watcher.updateParameters(parameters)
            self.assertEqual(float(parameters[9].value), 80)
            parameters[9].value = 72
            source_rules["minimum_completion_percent"] = 90
            rules_path.write_text(json.dumps(source_rules), encoding="utf-8")
            watcher.updateParameters(parameters)
            self.assertEqual(float(parameters[9].value), 72)


if __name__ == "__main__":
    unittest.main()

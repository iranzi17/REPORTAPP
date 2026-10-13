"""Separate ArcGIS Pro toolbox for utility-network preview and apply tools."""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path


CORE_PATH = Path(__file__).resolve().parent / "CustomerMeterPhotoQA.pyt"
MODULE_NAME = "customer_meter_photo_qa_toolbox_core"
loader = SourceFileLoader(MODULE_NAME, str(CORE_PATH))
if MODULE_NAME not in sys.modules:
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader)
    core = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = core
else:
    core = sys.modules[MODULE_NAME]
loader.exec_module(core)


class Toolbox:
    def __init__(self):
        self.label = "Customer Meter Photo QA - Network Operations"
        self.alias = "customer_meter_photo_qa_operations"
        self.tools = [core.BuildSubstationContainment, core.BuildRelayAssociations]

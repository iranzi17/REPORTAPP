"""Conservative meter-number normalization and comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass


OCR_CONFUSIONS = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


@dataclass(frozen=True)
class MeterComparison:
    entered_normalized: str
    detected_normalized: str
    exact_match: bool
    possible_ocr_confusion: bool


def normalize_meter_number(value: object) -> str:
    """Uppercase and remove separators without changing letters into digits."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def compare_meter_numbers(entered: object, detected: object) -> MeterComparison:
    entered_value = normalize_meter_number(entered)
    detected_value = normalize_meter_number(detected)
    exact = bool(entered_value and detected_value and entered_value == detected_value)
    possible_confusion = bool(
        not exact
        and entered_value
        and detected_value
        and entered_value.translate(OCR_CONFUSIONS) == detected_value.translate(OCR_CONFUSIONS)
    )
    return MeterComparison(
        entered_normalized=entered_value,
        detected_normalized=detected_value,
        exact_match=exact,
        possible_ocr_confusion=possible_confusion,
    )


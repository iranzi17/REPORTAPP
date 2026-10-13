"""Deterministic quality decisions around an OCR result."""

from __future__ import annotations

from dataclasses import dataclass

from .normalization import compare_meter_numbers, normalize_meter_number


@dataclass(frozen=True)
class QualityResult:
    status: str
    reason: str
    entered_normalized: str = ""
    detected_normalized: str = ""
    ocr_confidence: float | None = None


def evaluate_record(
    entered_meter_number: object,
    image_count: int,
    detected_meter_number: object | None = None,
    ocr_confidence: float | None = None,
    pass_threshold: float = 0.90,
    review_threshold: float = 0.65,
) -> QualityResult:
    entered = normalize_meter_number(entered_meter_number)
    if not entered:
        return QualityResult("MISSING_METER_NUMBER", "MeterNumber is empty")
    if image_count < 1:
        return QualityResult("MISSING_PHOTO", "No image attachment is available", entered_normalized=entered)
    if detected_meter_number is None:
        return QualityResult("READY_FOR_OCR", "Record has a meter number and image attachment", entered_normalized=entered)

    comparison = compare_meter_numbers(entered, detected_meter_number)
    confidence = float(ocr_confidence or 0.0)
    if comparison.exact_match and confidence >= pass_threshold:
        status, reason = "PASS", "Photo meter number matches MeterNumber"
    elif comparison.exact_match:
        status, reason = "REVIEW_LOW_CONFIDENCE", "Numbers match but OCR confidence is below the pass threshold"
    elif comparison.possible_ocr_confusion and confidence >= review_threshold:
        status, reason = "REVIEW_POSSIBLE_OCR_CONFUSION", "Difference may be caused by similar characters such as O/0 or I/1"
    elif confidence < review_threshold:
        status, reason = "REVIEW_UNREADABLE_PHOTO", "OCR confidence is too low for a reliable comparison"
    else:
        status, reason = "FAIL_METER_MISMATCH", "Photo meter number differs from MeterNumber"
    return QualityResult(
        status=status,
        reason=reason,
        entered_normalized=comparison.entered_normalized,
        detected_normalized=comparison.detected_normalized,
        ocr_confidence=confidence,
    )


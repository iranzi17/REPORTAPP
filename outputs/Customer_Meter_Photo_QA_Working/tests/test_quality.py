from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from meter_photo_qa.normalization import compare_meter_numbers, normalize_meter_number
from meter_photo_qa.quality import evaluate_record


class QualityTests(unittest.TestCase):
    def test_normalization_preserves_letters(self):
        self.assertEqual(normalize_meter_number(" 04-ab/91 "), "04AB91")

    def test_exact_match(self):
        result = evaluate_record("04-AB-91", 1, "04AB91", 0.96)
        self.assertEqual(result.status, "PASS")

    def test_missing_photo(self):
        self.assertEqual(evaluate_record("12345", 0).status, "MISSING_PHOTO")

    def test_missing_meter_number(self):
        self.assertEqual(evaluate_record(None, 1).status, "MISSING_METER_NUMBER")

    def test_possible_ocr_confusion_is_review_not_pass(self):
        comparison = compare_meter_numbers("A10S", "AI05")
        self.assertTrue(comparison.possible_ocr_confusion)
        result = evaluate_record("A10S", 1, "AI05", 0.88)
        self.assertEqual(result.status, "REVIEW_POSSIBLE_OCR_CONFUSION")


if __name__ == "__main__":
    unittest.main()


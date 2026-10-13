import unittest

from meter_photo_qa.phase_consistency import phase_type_conflict


class PhaseConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.expectations = {"9:11": 1, "9:12": 3}
        self.domain = {0: "1", 1: "2", 2: "3"}

    def check(self, asset_type, phases):
        return phase_type_conflict(
            {"ASSETGROUP": 9, "ASSETTYPE": asset_type, "Phases": phases},
            self.domain, self.expectations)

    def test_single_phase_conflict(self):
        self.assertIn("conflict", self.check(11, 2))

    def test_three_phase_conflict(self):
        self.assertIn("conflict", self.check(12, 0))

    def test_consistent(self):
        self.assertIsNone(self.check(11, 0))
        self.assertIsNone(self.check(12, 2))

    def test_unmapped_type_is_not_assumed(self):
        self.assertIsNone(self.check(99, 2))

    def test_missing_and_unknown_phases_are_not_double_counted(self):
        self.assertIsNone(self.check(11, None))
        self.assertIsNone(self.check(11, 15))

    def test_two_phase_label_not_inferred(self):
        self.assertIsNone(self.check(11, 1))


if __name__ == "__main__":
    unittest.main()

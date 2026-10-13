from __future__ import annotations

import unittest

from meter_photo_qa.feeder_engineering import _phase_set, audit_lv_feeder


def segment(gid, phases=3, voltage=400, basis="LL", **kwargs):
    return {"globalid": gid, "phase_count": phases,
            "nominal_voltage_v": voltage, "voltage_basis": basis, **kwargs}


def link(up, down, verified=True, **kwargs):
    return {"upstream_globalid": up, "downstream_globalid": down,
            "topology_verified": verified, **kwargs}


def codes(result, status=None):
    return [row["code"] for row in result["findings"]
            if status is None or row["status"] == status]


class FeederEngineeringTests(unittest.TestCase):
    def test_400_ll_230_ln_tap_and_separate_400_continuation_are_valid(self):
        data = [
            segment("T"),
            segment("S", phases=1, voltage=230, basis="LN"),
            segment("C"),
        ]
        result = audit_lv_feeder(data, [link("T", "S"), link("T", "C")])
        self.assertEqual(result["review_findings"], 0)
        self.assertEqual(result["links_evaluated"], 2)

    def test_400_to_230_to_400_on_one_verified_path_needs_review(self):
        data = [
            segment("T"),
            segment("S", phases=1, voltage=230, basis="LN"),
            segment("C"),
        ]
        result = audit_lv_feeder(data, [link("T", "S"), link("S", "C")])
        self.assertIn("PHASES_REAPPEAR_DOWNSTREAM", codes(result, "REVIEW"))

    def test_nominal_ll_400_to_ll_230_without_conversion_needs_review(self):
        data = [segment("T"), segment("C", voltage=230)]
        result = audit_lv_feeder(data, [link("T", "C")])
        self.assertIn("NOMINAL_VOLTAGE_TRANSITION", codes(result, "REVIEW"))

    def test_unknown_voltage_reference_basis_never_assumed(self):
        data = [segment("T"), segment("C", voltage=230, basis=None)]
        result = audit_lv_feeder(data, [link("T", "C")])
        self.assertEqual(result["review_findings"], 0)

    def test_equipment_or_verified_alternative_supply_prevents_false_alert(self):
        data = [segment("T", phases=1, voltage=230, basis="LN"), segment("C")]
        result = audit_lv_feeder(data, [link("T", "C", conversion_device_verified=True)])
        self.assertEqual(result["review_findings"], 0)
        self.assertIn("SOURCE_OR_CONVERSION_BOUNDARY", codes(result, "INFO"))

    def test_unverified_direction_not_called_error(self):
        data = [segment("T", phases=1, voltage=230, basis="LN"), segment("C")]
        result = audit_lv_feeder(data, [link("T", "C", verified=False)])
        self.assertEqual(result["links_evaluated"], 0)
        self.assertEqual(result["links_not_verified_or_incomplete"], 1)
        self.assertEqual(result["review_findings"], 0)

    def test_multiple_verified_parents_cannot_prove_flow_direction(self):
        data = [segment("A", phases=1, voltage=230, basis="LN"),
                segment("B"), segment("C")]
        result = audit_lv_feeder(data, [link("A", "C"), link("B", "C")])
        self.assertEqual(result["review_findings"], 0)
        self.assertEqual(result["links_not_verified_or_incomplete"], 2)

    def test_rated_current_change_is_information_not_violation(self):
        data = [segment("T", rated_current_a=200), segment("C", rated_current_a=80)]
        result = audit_lv_feeder(data, [link("T", "C")])
        self.assertEqual(result["review_findings"], 0)
        self.assertIn("RATED_CURRENT_CHANGED", codes(result, "INFO"))

    def test_cable_size_change_not_automatically_incorrect(self):
        data = [
            segment("T", conductor_size="4*70mm2"),
            segment("C", conductor_size="4*25mm2"),
        ]
        result = audit_lv_feeder(data, [link("T", "C")])
        self.assertEqual(result["review_findings"], 0)
        self.assertIn("CONDUCTOR_SIZE_CHANGED", codes(result, "INFO"))

    def test_protection_check_requires_explicit_design_ampacity(self):
        data = [segment("A", rated_current_a=200)]
        self.assertEqual(audit_lv_feeder(data, [])["review_findings"], 0)
        data = [segment("A", design_current_a=125, protective_setting_a=100,
                        adjusted_ampacity_a=80)]
        result = audit_lv_feeder(data, [])
        self.assertIn("LOAD_EXCEEDS_PROTECTION_SETTING", codes(result, "REVIEW"))
        self.assertIn("PROTECTION_EXCEEDS_DERATED_AMPACITY", codes(result, "REVIEW"))

    def test_phase_identity_mismatch(self):
        data = [
            segment("T", phases=2, phase_set="AB", phase_notation="ABC"),
            segment("C", phases=2, phase_set="BC", phase_notation="ABC"),
        ]
        result = audit_lv_feeder(data, [link("T", "C")])
        self.assertIn("PHASE_IDENTITY_MISMATCH", codes(result, "REVIEW"))

    def test_phase_b_notation_not_guessed(self):
        self.assertIsNone(_phase_set("B"))
        self.assertEqual(_phase_set("B", "ABC"), frozenset(["B"]))
        self.assertEqual(_phase_set("B", "RYB"), frozenset(["C"]))
        self.assertEqual(_phase_set("RYB"), frozenset(["A", "B", "C"]))

    def test_duplicate_globalids_rejected(self):
        with self.assertRaises(ValueError):
            audit_lv_feeder([segment("{G}"), segment("g")], [])

    def test_only_partially_exported_path_not_flagged(self):
        result = audit_lv_feeder([segment("A")], [link("A", "B")])
        self.assertEqual(result["review_findings"], 0)
        self.assertEqual(result["links_not_verified_or_incomplete"], 1)

    def test_no_conflation_of_current_rating_with_measured_load(self):
        data = [
            segment("A", rated_current_a=50),
            segment("B", rated_current_a=200),
        ]
        result = audit_lv_feeder(data, [link("A", "B")])
        self.assertEqual(result["review_findings"], 0)


if __name__ == "__main__":
    unittest.main()

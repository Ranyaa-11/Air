import unittest

from services.policy_service import PolicyService


class PolicyEffectivenessTests(unittest.TestCase):
    def test_classify_effectiveness_uses_reduction_fraction(self):
        rows = [
            {"change_pct": -10.0},
            {"change_pct": -15.0},
            {"change_pct": 5.0},
            {"change_pct": None},
        ]
        self.assertEqual(PolicyService.classify_effectiveness(rows), "Moderately Effective")

        rows = [
            {"change_pct": -10.0},
            {"change_pct": -15.0},
            {"change_pct": -20.0},
        ]
        self.assertEqual(PolicyService.classify_effectiveness(rows), "Highly Effective")

    def test_window_bounds_are_equal_duration_and_cover_policy_boundary(self):
        bounds = PolicyService._window_bounds("2024-04-01", 3)
        self.assertEqual(bounds["before_end"].strftime("%Y-%m-%d"), "2024-03-31")
        self.assertEqual(bounds["after_start"].strftime("%Y-%m-%d"), "2024-04-01")
        self.assertEqual((bounds["after_end"] - bounds["after_start"]).days,
                         (bounds["before_end"] - bounds["before_start"]).days)


if __name__ == "__main__":
    unittest.main()

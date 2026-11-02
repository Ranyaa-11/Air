import unittest

from services.aqi_service import calculate_aqi, subindex


class SubindexTests(unittest.TestCase):
    def test_gap_values_clamp_to_next_bracket(self):
        self.assertEqual(subindex(30.5, "PM2.5"), 51.0)
        self.assertEqual(subindex(1.05, "CO"), 51.0)

    def test_exact_bracket_boundaries(self):
        self.assertEqual(subindex(30, "PM2.5"), 50.0)
        self.assertEqual(subindex(31, "PM2.5"), 51.0)
        self.assertEqual(subindex(1, "CO"), 50.0)
        self.assertEqual(subindex(1.1, "CO"), 51.0)

    def test_negative_values_are_invalid(self):
        self.assertIsNone(subindex(-0.01, "PM2.5"))
        self.assertIsNone(subindex(-1, "CO"))

    def test_values_above_top_breakpoint_return_500(self):
        self.assertEqual(subindex(500, "PM2.5"), 500.0)
        self.assertEqual(subindex(500.1, "PM2.5"), 500.0)

    def test_notebook_breakpoints_match_reference_values(self):
        self.assertAlmostEqual(subindex(30.5, "PM2.5"), 51.0)
        self.assertAlmostEqual(subindex(55, "PM10"), 55.0)
        self.assertAlmostEqual(subindex(66, "NO2"), 82.41)
        self.assertAlmostEqual(subindex(66, "SO2"), 82.41)
        self.assertAlmostEqual(subindex(1.3, "CO"), 61.89)
        self.assertAlmostEqual(subindex(75, "OZONE"), 75.0)


class AqiEligibilityTests(unittest.TestCase):
    def test_requires_at_least_three_valid_pollutants(self):
        result = calculate_aqi({"PM2.5": 10, "NO2": 10})
        self.assertIsNone(result["aqi"])
        self.assertEqual(result["valid_count"], 2)

    def test_requires_pm25_or_pm10(self):
        result = calculate_aqi({"NO2": 10, "SO2": 10, "CO": 0.5})
        self.assertIsNone(result["aqi"])

    def test_calculates_aqi_with_pm_and_three_valid_pollutants(self):
        result = calculate_aqi({"PM2.5": 30.5, "NO2": 10, "SO2": 10})
        self.assertEqual(result["aqi"], 51)
        self.assertEqual(result["dominant"], "PM2.5")


if __name__ == "__main__":
    unittest.main()

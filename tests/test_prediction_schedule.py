import unittest

import pandas as pd

from services.prediction_service import build_outlook_schedule


class OutlookScheduleTests(unittest.TestCase):
    def test_forecast_starts_from_today_when_data_is_stale(self):
        past_date = pd.Timestamp("2026-10-03")
        schedule, gap_days, outlook_start = build_outlook_schedule(
            past_date,
            5,
            anchor_date="2026-11-02",
        )

        self.assertEqual(gap_days, 0)
        self.assertEqual(outlook_start, pd.Timestamp("2026-11-02"))
        self.assertEqual(
            [date.strftime("%Y-%m-%d") for date, _, _ in schedule],
            [
                "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
                "2026-11-06",
            ],
        )
        self.assertEqual([is_gap for _, is_gap, _ in schedule], [False] * 5)
        self.assertEqual([ahead for _, _, ahead in schedule], [1, 2, 3, 4, 5])

    def test_forecast_date_is_always_after_last_measured_date(self):
        schedule, gap_days, outlook_start = build_outlook_schedule(
            pd.Timestamp("2026-10-08"),
            2,
            anchor_date="2026-10-09",
        )

        self.assertEqual(gap_days, 0)
        self.assertEqual(outlook_start, pd.Timestamp("2026-10-09"))
        self.assertEqual(
            [date.strftime("%Y-%m-%d") for date, _, _ in schedule],
            ["2026-10-09", "2026-10-10"],
        )

if __name__ == "__main__":
    unittest.main()

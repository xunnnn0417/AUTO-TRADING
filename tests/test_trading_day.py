import unittest
from datetime import datetime

from trading_helper.trading_day import is_us_dst, trading_day_key


class TradingDayTests(unittest.TestCase):
    def test_summer_reset_uses_six_oclock(self):
        before = datetime(2026, 6, 20, 5, 59)
        after = datetime(2026, 6, 20, 6, 0)

        self.assertTrue(is_us_dst(before))
        self.assertEqual(trading_day_key(before)[0], "2026-06-19")
        self.assertEqual(trading_day_key(after)[0], "2026-06-20")
        self.assertEqual(trading_day_key(after)[2], 6)

    def test_winter_reset_uses_seven_oclock(self):
        before = datetime(2026, 12, 20, 6, 59)
        after = datetime(2026, 12, 20, 7, 0)

        self.assertFalse(is_us_dst(before))
        self.assertEqual(trading_day_key(before)[0], "2026-12-19")
        self.assertEqual(trading_day_key(after)[0], "2026-12-20")
        self.assertEqual(trading_day_key(after)[2], 7)


if __name__ == "__main__":
    unittest.main()


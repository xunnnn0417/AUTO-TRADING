"""Entry receipt shows the 場內外點差 from both confirmed fill prices."""
import unittest

from trading_helper.entry_status_report import build_entry_status_report, entry_spread_line


def entry(internal, external, direction):
    other = "SELL" if direction == "BUY" else "BUY"
    return {"confirmed_legs": {"internal": "1", "external": "2"}, "confirmed_both": "1",
            "leg_fills": {"internal": {"price": internal, "direction": direction},
                          "external": {"price": external, "direction": other}}}


class EntrySpreadTests(unittest.TestCase):
    def test_internal_long_uses_internal_minus_external(self):
        self.assertEqual(entry_spread_line(entry("2650.50", "2650.20", "BUY")),
                         "場內外點差：0.3，可能會有些許磨損")
        self.assertIn("點差為負", entry_spread_line(entry("2650.10", "2650.20", "BUY")))

    def test_internal_short_uses_external_minus_internal(self):
        self.assertEqual(entry_spread_line(entry("2650.20", "2650.50", "SELL")),
                         "場內外點差：0.3，可能會有些許磨損")
        self.assertIn("-0.2", entry_spread_line(entry("2650.40", "2650.20", "SELL")))

    def test_shown_first_in_receipt_and_absent_without_prices(self):
        report = build_entry_status_report(entry("10", "9", "BUY"), success=True,
                                           sync_requested=False, tv_requested=False)
        self.assertTrue(report["message"].startswith("場內外點差：1"))
        plain = build_entry_status_report({"confirmed_legs": {"internal": "1", "external": "2"}},
                                          success=True, sync_requested=False, tv_requested=False)
        self.assertNotIn("點差", plain["message"])


if __name__ == "__main__":
    unittest.main()

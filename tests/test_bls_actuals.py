"""公布值 from BLS: headline figures, waiting release reminders, no guessing."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from trading_helper.bls_actuals import headline_value, series_for

UTC = timezone.utc
RELEASE = datetime(2026, 11, 13, 13, 30, tzinfo=UTC)  # reports October
CPI = [(2026, 10, Decimal("337.476")), (2026, 9, Decimal("336.298")), (2025, 10, Decimal("327.000"))]


class HeadlineValueTests(unittest.TestCase):
    def test_figures_match_how_the_release_is_quoted(self):
        self.assertEqual(headline_value("mom", CPI, RELEASE), "0.4%")
        self.assertEqual(headline_value("yoy", CPI, RELEASE), "3.2%")
        jobs = [(2026, 10, Decimal("159293")), (2026, 9, Decimal("159128"))]
        self.assertEqual(headline_value("change_k", jobs, RELEASE), "165K")
        self.assertEqual(headline_value("level", [(2026, 10, Decimal("4.1"))], RELEASE), "4.1%")

    def test_nothing_until_bls_has_the_reported_month(self):
        self.assertIsNone(headline_value("mom", CPI[1:], RELEASE))  # only September yet

    def test_forex_factory_titles_map_to_series(self):
        self.assertEqual(series_for("CPI m/m"), ("CUSR0000SA0", "mom"))
        self.assertEqual(series_for("Non-Farm Employment Change")[0], "CES0000000001")
        self.assertIsNone(series_for("Prelim GDP q/q"))  # BEA, not BLS


class CalendarActualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        from trading_helper.calendar_events import CalendarEvent, EconomicCalendar
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calendar = EconomicCalendar(Path(self.tmp.name) / "calendar.json")
        self.addCleanup(self.calendar.close)
        self.event = CalendarEvent(RELEASE, "USD", "CPI m/m", details="預期：0.3% 前值：0.4%")
        self.calendar._events_by_source["ff"] = [self.event]
        self.calendar._combine()

    def test_value_is_added_to_the_event_details(self):
        from trading_helper.calendar_events import publication_values
        self.calendar._apply_actuals(([self.event], {"CUSR0000SA0": CPI}))
        values = publication_values(self.calendar.events[0].details)
        self.assertEqual(values, {"actual": "0.4%", "forecast": "0.3%", "previous": "0.4%"})

    def test_reads_only_at_the_planned_moments_and_only_when_running(self):
        calls = []
        with patch("trading_helper.bls_actuals.fetch", side_effect=lambda *a, **k: calls.append(1) or {}):
            self.calendar._check_actuals(RELEASE + timedelta(seconds=30))
            self.assertEqual(calls, [])                      # not started: never online
            self.calendar._polling_enabled = True
            self.calendar._check_actuals(RELEASE + timedelta(seconds=5))
            self.assertFalse(self.calendar._actual_busy)     # too early
            self.calendar._check_actuals(RELEASE + timedelta(seconds=25))
            self.assertTrue(self.calendar._actual_busy)
        self.assertEqual(self.calendar._actual_tries, {(RELEASE.isoformat(), "CPI m/m"): 1})

    def test_release_reminder_waits_for_the_value(self):
        from trading_helper.calendar_events import scheduled_reminders
        calendar = self.calendar
        calendar.source_times = {"ff": RELEASE}
        kinds = lambda now: [kind for kind, *_ in scheduled_reminders(calendar, now) if kind == "release"]
        with patch("trading_helper.calendar_events.reminder_wanted", return_value=True):
            self.assertEqual(kinds(RELEASE + timedelta(seconds=10)), [])   # no value yet
            calendar._apply_actuals(([self.event], {"CUSR0000SA0": CPI}))
            calendar.source_times = {"ff": RELEASE}
            self.assertEqual(kinds(RELEASE + timedelta(seconds=40)), ["release"])
            self.assertIn("公布值", next(item for kind, item, *_ in scheduled_reminders(
                calendar, RELEASE + timedelta(seconds=40)) if kind == "release").details)


if __name__ == "__main__":
    unittest.main()

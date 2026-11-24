"""Local rest schedules, desktop clock and phone queue; no broker/source calls."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication

from trading_helper.calendar_events import EconomicCalendar, TAIPEI, scheduled_reminders, events_for_display
from trading_helper.rest_reminders import normalize_settings, rest_occurrences


class RestReminderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def settings(self, **changes):
        return dict(enabled=True, time='06:00', minutes=[60, 30], days=[1, 2, 3, 4, 5], **changes)

    def test_default_is_disabled_and_invalid_settings_are_rejected(self):
        self.assertFalse(normalize_settings({})['enabled'])
        for change in (dict(minutes=[0]), dict(minutes=[1441]),
                       dict(minutes=['30']), dict(minutes=list(range(1, 10))), dict(enabled='yes')):
            value = self.settings()
            value.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_settings(value)

    def test_automatic_winter_summer_and_weekend_schedule(self):
        value = dict(enabled=True, minutes=[30, 60, 30])
        self.assertEqual(normalize_settings(value)['minutes'], [60, 30])
        for now, expected in ((datetime(2026, 11, 20, 1, tzinfo=TAIPEI), (20, 6)),
                              (datetime(2026, 6, 19, 1, tzinfo=TAIPEI), (19, 5)),
                              (datetime(2026, 11, 22, 1, tzinfo=TAIPEI), (24, 6)),
                              (datetime(2026, 3, 9, 1, tzinfo=TAIPEI), (10, 5)),
                              (datetime(2026, 11, 2, 1, tzinfo=TAIPEI), (3, 6))):
            with self.subTest(now=now):
                next_close = min(t for t in rest_occurrences(value, now) if t > now)
                self.assertEqual((next_close.day, next_close.hour), expected)
                self.assertNotIn(next_close.weekday(), (0, 6))

    def test_legacy_time_and_days_no_longer_override_automatic_schedule(self):
        now = datetime(2026, 11, 22, 23, tzinfo=TAIPEI)
        value = self.settings()
        value.update(time='00:15', days=[0])
        normalized = normalize_settings(value)
        self.assertNotIn('time', normalized)
        self.assertNotIn('days', normalized)
        next_close = min(t for t in rest_occurrences(value, now) if t > now)
        self.assertEqual((next_close.day, next_close.hour), (24, 6))

    def test_offset_window_no_late_catchup_and_no_after_close_alert(self):
        now = datetime(2026, 11, 20, 5, tzinfo=TAIPEI)
        with tempfile.TemporaryDirectory() as folder:
            service = EconomicCalendar(Path(folder)/'events.json', rest_settings=self.settings)
            self.addCleanup(service.close)
            self.assertEqual([row[0] for row in scheduled_reminders(service, now)], ['rest:60'])
            self.assertEqual(list(scheduled_reminders(service, now-timedelta(seconds=1))), [])
            self.assertEqual(list(scheduled_reminders(service, now+timedelta(seconds=61))), [])
            self.assertEqual([row[0] for row in scheduled_reminders(service, now+timedelta(minutes=30))], ['rest:30'])
            self.assertEqual(list(scheduled_reminders(service, now+timedelta(hours=1))), [])

    def test_local_schedule_visible_without_sources_and_deduplicated_after_restart(self):
        now = datetime(2026, 11, 20, 5, tzinfo=TAIPEI)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'events.json'
            seen = []
            for index in range(2):
                service = EconomicCalendar(path, rest_settings=self.settings)
                service.announcements.connect(seen.extend)
                service._check_reminders(now+timedelta(seconds=index*5))
                shown = events_for_display(service, now)
                self.assertTrue(any(e.source == '休市提醒' and e.when.hour == 6 for e in shown))
                service.close()
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].reminder_kind, 'rest:60')
            self.assertEqual(service.events, [])  # Local schedules never become fetched source data.

    def test_disabled_or_corrupt_saved_values_never_schedule(self):
        now = datetime(2026, 11, 20, 5, tzinfo=TAIPEI)
        for value in ({}, dict(enabled=True, minutes=[0]), dict(enabled=False)):
            with self.subTest(value=value):
                self.assertEqual(rest_occurrences(value, now), [])

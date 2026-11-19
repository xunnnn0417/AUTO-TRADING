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
        for change in (dict(time='25:00'), dict(minutes=[0]), dict(minutes=[1441]),
                       dict(minutes=['30']), dict(days=[]), dict(days=[7]), dict(enabled='yes')):
            value = self.settings()
            value.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_settings(value)

    def test_custom_time_weekdays_and_midnight_offsets(self):
        now = datetime(2026, 11, 22, 23, 45, tzinfo=TAIPEI)  # Sunday
        value = dict(enabled=True, time='00:15', minutes=[30, 60, 30], days=[0])
        self.assertEqual(normalize_settings(value)['minutes'], [60, 30])
        occurrences = rest_occurrences(value, now)
        self.assertEqual(min(t for t in occurrences if t > now), now.replace(day=23, hour=0, minute=15))
        with tempfile.TemporaryDirectory() as folder:
            service = EconomicCalendar(Path(folder)/'events.json', rest_settings=lambda: value)
            self.addCleanup(service.close)
            due = list(scheduled_reminders(service, now))
            self.assertEqual([row[0] for row in due], ['rest:30'])
            self.assertIn('30 分鐘後休市', due[0][3])
            self.assertIn('12:15 AM', due[0][3])

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
        for value in ({}, dict(enabled=True, time='bad'), dict(enabled=False)):
            with self.subTest(value=value):
                self.assertEqual(rest_occurrences(value, now), [])

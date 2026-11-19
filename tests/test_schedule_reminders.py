"""Schedule clock and restart deduplication; no source or broker requests."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtWidgets import QApplication
from trading_helper.calendar_events import CalendarEvent, EconomicCalendar


class ScheduleReminderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_before_and_release_are_deduplicated_after_restart(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'calendar.json'
            service = EconomicCalendar(path)
            self.addCleanup(service.close)
            service.events = [CalendarEvent(now + timedelta(minutes=10), 'USD', 'CPI')]
            service.source_times['ff'] = service.fetched_at = now
            seen = []
            service.announcements.connect(seen.extend)
            service._check_reminders(now)
            service._check_reminders(now + timedelta(seconds=5))
            self.assertEqual(len(seen), 1)
            self.assertIn('10 分鐘後公布', seen[0].title)
            restored = EconomicCalendar(path)
            self.addCleanup(restored.close)
            restored.announcements.connect(seen.extend)
            restored._check_reminders(now + timedelta(seconds=10))
            self.assertEqual(len(seen), 1)
            restored._check_reminders(now + timedelta(minutes=10))
            restored._check_reminders(now + timedelta(minutes=10, seconds=5))
            self.assertEqual(len(seen), 2)
            self.assertIn('公布時間已到', seen[-1].title)
            self.assertNotIn('請查看消息確認公布結果', seen[-1].title)

    def test_missing_stale_error_or_old_schedule_never_notifies(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            service = EconomicCalendar(Path(folder) / 'calendar.json')
            self.addCleanup(service.close)
            service.events = [CalendarEvent(now + timedelta(minutes=5), 'USD', 'CPI')]
            seen = []
            service.announcements.connect(seen.extend)
            service._check_reminders(now)
            service.source_times['ff'] = now - timedelta(hours=1)
            service._check_reminders(now)
            service.source_times['ff'] = now
            service.source_errors['ff'] = 'offline'
            service._check_reminders(now)
            service.source_errors.clear()
            service.events = [CalendarEvent(now - timedelta(minutes=2), 'USD', 'CPI')]
            service._check_reminders(now)
            self.assertEqual(seen, [])
            service.close()
            service.events = [CalendarEvent(now + timedelta(minutes=5), 'USD', 'CPI')]
            service._check_reminders(now)
            self.assertEqual(seen, [])

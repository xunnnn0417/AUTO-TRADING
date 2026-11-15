"""Public calendar data only: no broker or account connections."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from trading_helper.calendar_events import CalendarEvent, EconomicCalendar, parse_events, countdown, MAX_BYTES

UTC = timezone.utc
NOW = datetime(2026, 11, 15, 0, 0, tzinfo=UTC)


class CalendarTests(unittest.TestCase):
    def test_high_impact_all_currencies_sorted_deduplicated_and_timezone_aware(self):
        rows = [
            dict(title='CPI y/y', country='USD', date='2026-11-16T08:30:00-05:00', impact='High'),
            dict(title='Cash Rate', country='AUD', date='2026-11-16T14:30:00+11:00', impact='High'),
            dict(title='Retail Sales', country='EUR', date='2026-11-16T10:00:00+01:00', impact='Low'),
        ]
        events = parse_events(rows + rows[:1])
        self.assertEqual([e.currency for e in events], ['AUD', 'USD'])
        self.assertEqual(events[1].when.hour, 13)
        self.assertEqual(events[1].when.tzinfo, UTC)

    def test_bad_dates_naive_times_and_html_are_not_executable_content(self):
        rows = [dict(title='<b>Talk</b>', country='USD', impact='High', date=d)
                for d in ('Tentative', '2026-11-16T12:00:00', '2026-11-16T12:00:00Z')]
        events = parse_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, '<b>Talk</b>')
        with self.assertRaises(ValueError):
            parse_events({'unexpected': 'object'})

    def test_countdown_never_claims_a_past_event_is_upcoming(self):
        self.assertEqual(countdown(NOW + timedelta(hours=2, minutes=15), NOW), '2 小時 15 分後')
        self.assertEqual(countdown(NOW + timedelta(days=1, hours=2), NOW), '1 天 2 小時後')
        self.assertEqual(countdown(NOW + timedelta(seconds=15), NOW), '1 分鐘內')
        self.assertEqual(countdown(NOW - timedelta(seconds=1), NOW), '已發布')

    def test_cache_is_rate_limited_and_error_never_becomes_no_events(self):
        with tempfile.TemporaryDirectory() as folder:
            service = EconomicCalendar(Path(folder) / 'calendar.json')
            rows = [dict(title='CPI y/y', country='USD', date='2026-11-16T13:30:00Z', impact='High')]
            service.events = parse_events(rows)
            service.fetched_at = NOW
            service.source_times = {key: NOW for key in ('ff', 'bea', 'fed', 'ecb')}
            self.assertTrue(service.is_fresh(NOW + timedelta(minutes=14)))
            self.assertFalse(service.is_fresh(NOW + timedelta(hours=2)))
            service._save_cache()
            restored = EconomicCalendar(Path(folder) / 'calendar.json')
            self.assertEqual(restored.events, service.events)
            self.assertEqual(restored.fetched_at, NOW)
            with patch('trading_helper.calendar_events.datetime') as clock, \
                 patch('trading_helper.calendar_events.threading.Thread') as thread:
                clock.now.return_value = NOW + timedelta(minutes=1)
                restored.refresh()
                thread.assert_not_called()

    def test_fetch_has_size_limit_and_keeps_old_events_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            service = EconomicCalendar(Path(folder) / 'calendar.json')
            existing = CalendarEvent(NOW + timedelta(days=1), 'USD', 'CPI')
            service.events = [existing]
            with patch('trading_helper.calendar_events.urlopen', side_effect=OSError('offline')):
                service._fetch()
            self.assertEqual(service.events, [existing])
            self.assertTrue(service.error)
            self.assertIsNone(service.fetched_at)
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'x' * (MAX_BYTES + 1)
            with patch('trading_helper.calendar_events.urlopen', return_value=response):
                service._fetch()
            self.assertEqual(service.events, [existing])
            self.assertIn('ValueError', service.error)

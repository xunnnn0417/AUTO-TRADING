"""Trading-day event summaries, with no network or platform operations."""
import unittest
from datetime import datetime, timedelta

from trading_helper.calendar_events import CalendarEvent, countdown
from trading_helper.event_summary import TAIPEI, event_summary, relevant_announcement, trading_session


class EventSummaryTests(unittest.TestCase):
    def test_routine_central_bank_administration_is_not_marked_market_news(self):
        self.assertTrue(relevant_announcement('FOMC statement'))
        self.assertTrue(relevant_announcement('Monetary policy and inflation'))
        self.assertFalse(relevant_announcement('Revised tentative schedule of FOMC meetings in 2027'))
        self.assertFalse(relevant_announcement('Digital euro discussion'))

    def test_after_midnight_still_belongs_to_previous_trading_day(self):
        now = datetime(2026, 11, 17, 2, tzinfo=TAIPEI)
        start, end = trading_session(now, {})
        self.assertEqual(start, datetime(2026, 11, 16, 7, tzinfo=TAIPEI))
        self.assertEqual(end, datetime(2026, 11, 17, 6, tzinfo=TAIPEI))
        event = CalendarEvent(now+timedelta(hours=1, minutes=12), 'USD', 'CPI')
        result = event_summary([event], now, {}, True)
        self.assertIn('1 小時 12 分', result)
        self.assertIn('CPI', result)
        self.assertNotIn('\n', result)

    def test_summer_and_configured_session_hours_are_reused(self):
        start, end = trading_session(datetime(2026, 6, 17, 10, tzinfo=TAIPEI), {})
        self.assertEqual((start.hour, end.hour), (6, 5))
        start, end = trading_session(datetime(2026, 11, 17, 10, tzinfo=TAIPEI), {'winter_reset_hour': 6})
        self.assertEqual((start.hour, end.hour), (6, 5))

    def test_empty_today_names_tomorrow_and_never_calls_missing_data_empty(self):
        now = datetime(2026, 11, 16, 12, tzinfo=TAIPEI)
        event = CalendarEvent(datetime(2026, 11, 17, 21, 30, tzinfo=TAIPEI), 'USD', 'CPI')
        result = event_summary([event], now, {}, True)
        self.assertIn('今日無已知重大排程', result)
        self.assertIn('明日 21:30', result)
        self.assertNotIn('\n', result)
        unknown = event_summary([event], now, {}, False)
        self.assertIn('尚未完整更新', unknown)
        self.assertNotIn('無已知', unknown)

    def test_finished_today_and_far_future_are_explicit(self):
        now = datetime(2026, 11, 16, 22, tzinfo=TAIPEI)
        events = [CalendarEvent(now-timedelta(hours=1), 'USD', 'PPI'),
                  CalendarEvent(datetime(2026, 11, 25, 21, 30, tzinfo=TAIPEI), 'USD', 'GDP')]
        result = event_summary(events, now, {}, True)
        self.assertIn('今日重大事件已公布', result)
        self.assertIn('11/25 21:30', result)
        self.assertIn('下一場', result)

    def test_session_break_does_not_hide_next_known_release(self):
        now = datetime(2026, 11, 17, 6, 30, tzinfo=TAIPEI)
        event = CalendarEvent(now+timedelta(minutes=10), 'USD', 'CPI')
        self.assertIn('今日 06:40', event_summary([event], now, {}, True))

    def test_long_countdown_retains_minutes(self):
        now = datetime(2026, 11, 16, 12, tzinfo=TAIPEI)
        self.assertEqual(countdown(now+timedelta(days=2, hours=3, minutes=17), now), '2 天 3 小時 17 分後')

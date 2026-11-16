"""Public event sources: scheduled releases and dated official announcements."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from trading_helper import calendar_events as calendar

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


class EventSourceTests(unittest.TestCase):
    def test_loaded_week_is_preserved_but_stale_wrong_week_or_failed_source_cannot_claim_no_events(self):
        from datetime import timedelta
        from trading_helper.event_summary import trading_session
        now = datetime(2026, 11, 16, 4, tzinfo=timezone.utc)
        rows = [dict(title='Low event', impact='Low', country='JPY', date='2026-11-16T02:00:00Z')]
        coverage = calendar.calendar_week(rows)
        self.assertIsNotNone(coverage)
        with tempfile.TemporaryDirectory() as folder:
            service = calendar.EconomicCalendar(Path(folder)/'events.json')
            service._apply([('ff', calendar.parse_events(rows), now, '', coverage)])
            start, end = trading_session(now, {})
            self.assertTrue(service.covers_day(start, end, now))
            restored = calendar.EconomicCalendar(service.path)
            self.assertTrue(restored.covers_day(start, end, now))
            self.assertFalse(restored.covers_day(start, end, now+timedelta(hours=1)))
            self.assertFalse(restored.covers_day(start+timedelta(days=7), end+timedelta(days=7), now))
            restored._apply([('ff', None, None, 'offline')])
            self.assertFalse(restored.covers_day(start, end, now))
        self.assertIsNone(calendar.calendar_week([]))
        self.assertIsNone(calendar.calendar_week([dict(date='bad')]))

    def test_market_news_uses_aware_dates_and_relevant_chinese_topics(self):
        raw = '''<rss><channel>
          <item><title>伊朗稱霍爾木茲海峽運油輪遇襲</title><pubDate>Sun, 15 Nov 2026 09:00:00 +0800</pubDate></item>
          <item><title>金價受美元及美債收益率影響</title><pubDate>Sun, 15 Nov 2026 10:00:00 +0800</pubDate></item>
          <item><title>本地足球比賽結果</title><pubDate>Sun, 15 Nov 2026 10:00:00 +0800</pubDate></item>
          <item><title>聯儲局講話</title><pubDate>2026-11-15 10:00:00</pubDate></item>
        </channel></rss>'''.encode()
        items = calendar.parse_market_news(raw, '香港電台國際')
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].when.hour, 2)
        self.assertIn('伊朗', items[1].title)

    def test_chinese_title_preserves_original_and_numbers_or_falls_back(self):
        self.assertEqual(calendar.local_title('Non-Farm Employment Change'), '非農就業人數變化')
        self.assertEqual(calendar.local_title('Unknown 2027'), 'Unknown 2027')
        self.assertTrue(calendar.valid_translation('Fed schedule 2027', '聯準會 2027 年會議日程'))
        self.assertFalse(calendar.valid_translation('Fed schedule 2027', '聯準會 2026 年會議日程'))
        self.assertFalse(calendar.valid_translation('Fed schedule', 'QUERY LENGTH LIMIT EXCEEDED'))

    def test_translation_is_cached_bounded_and_reused_without_retransmitting(self):
        with tempfile.TemporaryDirectory() as folder:
            service = calendar.EconomicCalendar(Path(folder)/'events.json')
            now = datetime.now(timezone.utc)
            service._apply([('fed', [calendar.Announcement(now, 'Fed', 'Fed schedule 2027')], now, '')])
            with patch.object(calendar, 'translate_title', return_value='聯準會 2027 年會議日程') as translate:
                service._translation_attempts.add('Fed schedule 2027')
                service._translate_titles(['Fed schedule 2027'])
            translate.assert_called_once()
            restored = calendar.EconomicCalendar(service.path)
            self.assertEqual(restored.title('Fed schedule 2027'), '聯準會 2027 年會議日程')
            restored.news = [calendar.Announcement(now, 'Fed', 'Fed schedule 2027')]
            with patch.object(calendar.threading, 'Thread') as thread:
                restored._translate_missing()
                thread.assert_not_called()
            restored.events = [calendar.CalendarEvent(now.replace(year=now.year+1), 'USD', 'Unknown event')]
            restored.news = [calendar.Announcement(now, 'Fed', 'Another new statement')]
            restored._translation_day = now.date().isoformat()
            restored._translation_chars = 4000
            with patch.object(calendar.threading, 'Thread') as thread:
                restored._translate_missing()
                thread.assert_not_called()

    def test_medium_usd_events_are_included_but_low_and_other_medium_are_not(self):
        rows = [dict(title='Retail Sales', country=country, impact=impact, date='2026-11-16T13:30:00Z')
                for country, impact in [('USD', 'Medium'), ('USD', 'Low'), ('EUR', 'Medium')]]
        self.assertEqual(len(calendar.parse_events(rows)), 1)
        self.assertEqual(calendar.parse_events(rows)[0].currency, 'USD')
    def test_old_week_cache_is_migrated_but_missing_sources_are_not_fresh(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'events.json'
            path.write_text(json.dumps({'fetched_at': NOW.isoformat(), 'rows': [
                dict(title='CPI', country='USD', date='2026-11-13T13:30:00Z', impact='High')]}), encoding='utf-8')
            service = calendar.EconomicCalendar(path)
            self.assertEqual(len(service.events), 1)
            self.assertFalse(service.is_fresh(NOW))
            self.assertEqual(set(service.source_times), {'ff'})
            path.write_text('[]', encoding='utf-8')
            self.assertIsNone(calendar.EconomicCalendar(path).fetched_at)

    def test_bea_only_gdp_and_income_schedule_and_aware_dates(self):
        rows = {'Gross Domestic Product': {'release_dates': ['2026-11-25T13:30:00+00:00'] * 2},
                'Personal Income and Outlays': {'release_dates': ['bad', '2026-11-25T13:30:00', '2026-11-25T15:00:00Z']},
                'Regional Data': {'release_dates': ['2026-11-26T13:30:00Z']}}
        events = calendar.parse_bea_schedule(rows)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].source, 'BEA')
        self.assertEqual(events[1].currency, 'USD')
        self.assertIn('PCE', events[1].title)

    def test_empty_ff_cache_does_not_relabel_bea_as_forex_factory(self):
        with tempfile.TemporaryDirectory() as folder:
            service = calendar.EconomicCalendar(Path(folder)/'events.json')
            service._apply([('ff', [], NOW, ''), ('bea', [calendar.CalendarEvent(
                NOW, 'USD', 'GDP', 'BEA')], NOW, '')])
            restored = calendar.EconomicCalendar(service.path)
            self.assertEqual(restored._events_by_source['ff'], [])
            self.assertEqual([event.source for event in restored.events], ['BEA'])

    def test_rss_dates_plain_titles_and_entities_rejected(self):
        raw = b'''<rss><channel><item><title>&lt;b&gt;Rate decision&lt;/b&gt;</title>
          <pubDate>Thu, 12 Nov 2026 17:45:00 GMT</pubDate></item>
          <item><title>Undated</title></item></channel></rss>'''
        items = calendar.parse_announcements(raw, 'Fed')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, '<b>Rate decision</b>')
        self.assertEqual(items[0].when.hour, 17)
        with self.assertRaises(ValueError):
            calendar.parse_announcements(b'<!DOCTYPE rss [<!ENTITY e "bad">]><rss/>', 'Fed')

    def test_partial_failure_retains_old_source_without_losing_good_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            service = calendar.EconomicCalendar(Path(folder)/'events.json')
            old = calendar.CalendarEvent(NOW, 'USD', 'CPI')
            service.events = [old]
            payloads = {
                calendar.BEA_URL: json.dumps({'Gross Domestic Product': {'release_dates': ['2026-11-25T13:30:00Z']}}).encode(),
                calendar.FED_URL: b'<rss><channel><item><title>FOMC statement</title><pubDate>Thu, 12 Nov 2026 17:45:00 GMT</pubDate></item></channel></rss>',
                calendar.ECB_URL: b'<rss><channel><item><title>Interest rate decision</title><pubDate>Fri, 13 Nov 2026 09:00:00 +0100</pubDate></item></channel></rss>',
                calendar.RTHK_FINANCE_URL: '<rss><channel><item><title>金價上升</title><pubDate>Fri, 13 Nov 2026 09:00:00 +0800</pubDate></item></channel></rss>'.encode(),
                calendar.RTHK_WORLD_URL: b'<rss><channel/></rss>',
            }
            def response(request, **kwargs):
                if request.full_url == calendar.FEED_URL:
                    raise OSError('offline')
                mock = MagicMock()
                mock.__enter__.return_value.read.return_value = payloads[request.full_url]
                return mock
            with patch.object(calendar, 'urlopen', side_effect=response):
                service._fetch()
            self.assertIn(old, service.events)
            self.assertTrue(any(event.source == 'BEA' for event in service.events))
            self.assertEqual({item.source for item in service.news}, {'Fed', 'ECB', '香港電台財經'})
            self.assertIn('ff', service.source_errors)
            self.assertFalse(service.is_fresh(datetime.now(timezone.utc)))
            restored = calendar.EconomicCalendar(service.path)
            self.assertEqual(restored.news, service.news)
            self.assertTrue(any(event.source == 'BEA' for event in restored.events))

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
            self.assertEqual({item.source for item in service.news}, {'Fed', 'ECB'})
            self.assertIn('ff', service.source_errors)
            self.assertFalse(service.is_fresh(datetime.now(timezone.utc)))
            restored = calendar.EconomicCalendar(service.path)
            self.assertEqual(restored.news, service.news)
            self.assertTrue(any(event.source == 'BEA' for event in restored.events))

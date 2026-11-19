"""News monitoring uses only temporary files and stubbed public requests."""
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import test_compact_followup_controls as fixtures
from trading_helper import calendar_events as feeds


class NewsMonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'economic-calendar.json'
        self.service = feeds.EconomicCalendar(self.path)
        self.addCleanup(self.service.close)

    def test_30_second_trial_does_not_increase_calendar_frequency(self):
        self.assertEqual(feeds.SOURCE_TTLS['fed'], timedelta(seconds=30))
        self.assertEqual(feeds.SOURCE_TTLS['ff'], timedelta(minutes=30))
        now = datetime.now(feeds.UTC)
        self.service.source_times = dict.fromkeys(feeds.SOURCE_URLS, now-timedelta(seconds=31))
        with patch.object(feeds.threading, 'Thread') as worker:
            self.service.refresh()
        self.assertEqual(set(worker.call_args.kwargs['args'][0]),
                         {'fed', 'ecb', 'rthk_finance', 'rthk_world'})

    def test_actual_request_results_are_logged_without_response_bodies(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.headers = {}
        response.__enter__.return_value.read.return_value = b'<rss><channel/></rss>'
        with patch.object(feeds, 'urlopen', return_value=response):
            self.service._apply([self.service._read_source('fed')])
        for code in (304, 429):
            error = HTTPError(feeds.FED_URL, code, 'test', {'Retry-After': '120'}, io.BytesIO())
            with patch.object(feeds, 'urlopen', side_effect=error):
                self.service._read_source('fed')
        with patch.object(feeds, 'urlopen', side_effect=OSError('private-detail')):
            self.service._read_source('fed')
        rows = [json.loads(line) for line in self.path.with_name('news-poll.jsonl').read_text().splitlines()]
        self.assertEqual([r['outcome'] for r in rows], ['downloaded', 'unchanged', 'http_error', 'network_error'])
        self.assertEqual([r['http_status'] for r in rows], [200, 304, 429, None])
        self.assertTrue(all(r['duration_ms'] >= 0 and r['request_id'] for r in rows))
        self.assertNotIn('private-detail', json.dumps(rows))

    def test_baseline_stale_irrelevant_repeat_and_restart_do_not_popup(self):
        service = self.service
        received = []
        service.announcements.connect(received.extend)
        now = datetime.now(feeds.UTC)
        baseline = feeds.Announcement(now, 'Fed', 'FOMC statement')
        service._apply([('fed', [baseline], now, '')])
        self.assertEqual(received, [])
        fresh = feeds.Announcement(now, 'Fed', 'Interest rate decision')
        stale = feeds.Announcement(now-timedelta(hours=1), 'Fed', 'Inflation report')
        irrelevant = feeds.Announcement(now, 'Fed', 'Banking data release')
        rows = [fresh, stale, irrelevant, baseline]
        service._apply([('fed', rows, now, '')])
        self.assertEqual(received, [fresh])
        service._apply([('fed', rows, now, '')])
        self.assertEqual(received, [fresh])
        restored = feeds.EconomicCalendar(self.path)
        self.addCleanup(restored.close)
        restored.announcements.connect(received.extend)
        restored._apply([('fed', rows, now, '')])
        self.assertEqual(received, [fresh])

    def test_log_rotation_is_bounded_and_disk_failure_does_not_break_fetch(self):
        from trading_helper import news_probe
        path = self.path.with_name('news-poll.jsonl')
        with patch.object(news_probe, 'MAX_LOG_BYTES', 240):
            for i in range(40):
                self.assertTrue(news_probe.append_probe(path, {'sequence': i, 'value': 'x'*50}))
        files = list(path.parent.glob('news-poll.jsonl*'))
        self.assertLessEqual(len(files), 5)
        self.assertTrue(all(f.stat().st_size <= 240 for f in files))
        self.assertEqual(json.loads(path.read_text().splitlines()[-1])['sequence'], 39)
        with patch.object(feeds, 'append_probe', return_value=False), \
             patch.object(feeds, 'urlopen', side_effect=OSError('offline')):
            result = self.service._read_source('fed')
        self.assertEqual(result[3], 'OSError')
        self.assertIn('診斷記錄無法寫入', '\n'.join(self.service.status_lines(datetime.now(feeds.UTC))))

    def test_price_recap_stays_in_feed_but_only_real_catalyst_notifies(self):
        service = self.service
        now = datetime.now(feeds.UTC)
        received = []
        service.announcements.connect(received.extend)
        service._apply([('rthk_finance', [], now, '')])
        recap = feeds.Announcement(now, '香港電台財經', '金價升0.04%')
        catalyst = feeds.Announcement(now, '香港電台財經', '特朗普宣布加徵關稅')
        service._apply([('rthk_finance', [recap, catalyst], now, '')])
        self.assertEqual(received, [catalyst])
        self.assertIn(recap, service.news)
        service._apply([('rthk_finance', [recap, catalyst], now, '')])
        self.assertEqual(received, [catalyst])

    def test_parse_failure_and_manual_request_attribution_are_recorded(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.headers = {}
        response.__enter__.return_value.read.return_value = b'invalid json'
        with patch.object(feeds, 'urlopen', return_value=response):
            record = self.service._read_source('ff', entry_point='manual')
        self.assertTrue(record[3])
        row = json.loads(self.path.with_name('news-poll.jsonl').read_text().splitlines()[-1])
        self.assertEqual(row['entry_point'], 'manual')
        self.assertEqual(row['outcome'], 'parse_error')
        self.assertEqual(row['http_status'], 200)
        response.__enter__.return_value.read.return_value = b'<rss><broken'
        with patch.object(feeds, 'urlopen', return_value=response):
            record = self.service._read_source('fed')
        self.assertEqual(record[3], 'ValueError')  # Parser normalizes malformed RSS.
        rows = [json.loads(line) for line in self.path.with_name('news-poll.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['outcome'], 'parse_error')


class NewsAlertUiTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def test_alert_waits_for_operation_then_nonmodal_popup_and_unread_dot(self):
        from trading_helper import gui
        now = datetime.now(feeds.UTC)
        news = feeds.Announcement(now, '香港電台財經', '聯儲局宣布利率決定')
        self.w._active_tasks = 1
        self.w._queue_news_alerts([news])
        self.assertTrue(self.w.news_badge.isVisible())
        self.assertIsNone(getattr(self.w, '_news_alert_dialog', None))
        self.w._active_tasks = 0
        with patch.object(gui.QApplication, 'activeModalWidget', return_value=None):
            self.w._show_pending_news_alert()
        dialog = self.w._news_alert_dialog
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.windowModality(), Qt.NonModal)
        self.assertEqual(dialog._primary_text.textFormat(), Qt.PlainText)
        dialog.close()
        self.assertTrue(self.w.news_badge.isVisible())
        with patch.object(feeds.EconomicCalendar, 'refresh'):
            self.w._queue_news_alerts([news])
            self.w._news_alert_dialog._buttons[0].click()
        self.assertIs(self.w.main_pages.currentWidget(), self.w.news_page)
        self.assertFalse(self.w.news_badge.isVisible())

    def test_message_open_marks_read_without_extra_popup(self):
        with patch.object(feeds.EconomicCalendar, 'refresh'):
            self.w.switch_workspace('消息')
        news = feeds.Announcement(datetime.now(feeds.UTC), 'Fed', '<b>Interest rate decision</b>')
        self.w._queue_news_alerts([news])
        self.assertFalse(self.w.news_badge.isVisible())
        self.assertIsNone(getattr(self.w, '_news_alert_dialog', None))

    def test_news_popup_is_centered_when_collapsed_and_adjacent_when_expanded(self):
        news = feeds.Announcement(datetime.now(feeds.UTC),'Fed','FOMC statement')
        with patch.object(feeds.EconomicCalendar,'refresh'):
            self.w.toggle_side_panel(True)
        panel = self.w.side_panel
        self.w.hide()
        for collapsed in (True,False):
            panel.set_collapsed(collapsed)
            self.qtapp.processEvents()
            self.w._queue_news_alerts([news])
            dialog = self.w._news_alert_dialog
            area = panel.screen().availableGeometry()
            self.assertFalse(self.w.isVisible())
            if collapsed:
                self.assertLessEqual(abs(dialog.geometry().center().x()-area.center().x()),1)
                self.assertLessEqual(abs(dialog.geometry().center().y()-area.center().y()),1)
            else:
                self.assertEqual(dialog.x(),max(area.left(),panel.x()-dialog.width()-10))
            dialog.close()

    def test_news_popup_is_independent_and_only_view_opens_main(self):
        news = feeds.Announcement(datetime.now(feeds.UTC), 'Fed', 'FOMC statement')
        self.w.hide()
        with patch.object(self.w, 'showNormal') as show, patch.object(self.w, 'raise_') as raise_main:
            self.w._queue_news_alerts([news])
            dialog = self.w._news_alert_dialog
            self.assertIsNone(dialog.parentWidget())
            self.assertTrue(dialog.isVisible())
            self.assertFalse(self.w.isVisible())
            show.assert_not_called()
            raise_main.assert_not_called()
            dialog._buttons[1].click()
            show.assert_not_called()
            self.w._queue_news_alerts([news])
            with patch.object(feeds.EconomicCalendar, 'refresh'):
                self.w._news_alert_dialog._buttons[0].click()
            show.assert_called_once()
            self.assertIs(self.w.main_pages.currentWidget(), self.w.news_page)

    def test_startup_monitor_works_with_sidebar_off(self):
        self.w.side_panel_checkbox.setChecked(False)
        with patch.object(feeds.EconomicCalendar, 'refresh'):
            self.w.initialize_side_panel()
        self.assertTrue(self.w._event_calendar.refresh_timer.isActive())
        self.assertEqual(self.w._event_calendar.refresh_timer.interval(), 30_000)

    def test_starting_automation_hides_existing_alert_until_operation_ends(self):
        news = feeds.Announcement(datetime.now(feeds.UTC), 'Fed', 'FOMC statement')
        self.w._queue_news_alerts([news])
        first = self.w._news_alert_dialog
        self.w._active_tasks = 1
        self.w._hide_for_operation()
        self.assertFalse(first.isVisible())
        self.w._show_pending_news_alert()
        self.assertFalse(first.isVisible())
        self.w._active_tasks = 0
        self.w.operation_hint.hide()
        self.w._show_pending_news_alert()
        self.assertTrue(self.w._news_alert_dialog.isVisible())

    def test_preview_button_runs_real_alert_path_even_while_reading_news(self):
        with patch.object(feeds.EconomicCalendar, 'refresh'):
            self.w.switch_workspace('消息')
        view = self.w.news_feed
        service = view.calendar
        service._save_cache()
        before = service.path.read_bytes() if service.path.exists() else None
        with patch.object(feeds, 'urlopen') as download:
            view.test_alert_button.click()
        download.assert_not_called()
        dialog = self.w._news_alert_dialog
        self.assertTrue(dialog.isVisible())
        self.assertTrue(self.w.news_badge.isVisible())
        self.assertIn('測試', dialog._primary_text.text())
        self.assertIn('測試', view.news_rows.text())
        self.assertEqual(service.path.read_bytes() if service.path.exists() else None, before)
        self.assertFalse(service.path.with_name('news-poll.jsonl').exists())
        dialog._buttons[0].click()
        self.assertFalse(self.w.news_badge.isVisible())
        service._combine()
        self.assertIn('測試', view.news_rows.text())

    def test_preview_uses_same_operation_deferral_and_remains_out_of_saved_sources(self):
        with patch.object(feeds.EconomicCalendar, 'refresh'):
            self.w.switch_workspace('消息')
        self.w._active_tasks = 1
        self.w.news_feed.test_alert_button.click()
        self.assertIsNone(self.w._news_alert_dialog)
        self.assertTrue(self.w.news_badge.isVisible())
        self.w._active_tasks = 0
        self.w._show_pending_news_alert()
        self.assertTrue(self.w._news_alert_dialog.isVisible())
        service = self.w.news_feed.calendar
        now = datetime.now(feeds.UTC)
        service._apply([('fed', [], now, '')])
        saved = json.loads(service.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['sources']['fed'], [])
        self.assertNotIn('測試', json.dumps(saved, ensure_ascii=False))

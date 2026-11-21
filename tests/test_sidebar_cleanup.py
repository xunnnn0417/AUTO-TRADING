"""Release cleanup regressions; isolated UI/config and stubbed public feeds only."""
import io
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import test_side_panel as fixtures
from trading_helper import calendar_events as calendar
from trading_helper import gui


class SidebarRestoreTests(unittest.TestCase):
    setUp = fixtures.SidePanelTests.setUp
    tearDown = fixtures.SidePanelTests.tearDown
    open_panel = fixtures.SidePanelTests.open_panel

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def test_calibration_success_cancel_and_failure_restore_sidebar_for_all_platforms(self):
        panel = self.open_panel()
        for platform in ('cTrader', 'MT5', 'TradingView'):
            for collapsed in (True, False):
                for report in ({'cancelled': True}, None, gui.ScanReport(platform, ())):
                    with self.subTest(platform=platform, collapsed=collapsed, report=report):
                        panel.set_collapsed(collapsed)
                        self.w._calibration_dialog_active = True
                        dialog = gui.CalibrationDialog(self.w, platform)
                        dialog.show()
                        dialog._begin_calibration_operation('離線校準')
                        self.assertFalse(panel.isVisible())
                        with patch.object(gui.QDialog, 'exec', return_value=0):
                            dialog._finish_inventory(report)
                        self.assertTrue(dialog.isVisible())
                        self.assertFalse(self.w.isVisible())
                        self.assertTrue(panel.isVisible())
                        self.assertEqual(panel.collapsed, collapsed)
                        self.assertTrue(self.w.side_panel_checkbox.isChecked())
                        dialog._hover_outline.close()
                        dialog.close()
                        self.w._calibration_dialog_active = False

    def test_disabling_sidebar_during_calibration_is_respected(self):
        panel = self.open_panel()
        self.w._calibration_dialog_active = True
        self.w._hide_for_operation()
        self.w.toggle_side_panel(False)
        self.w._restore_after_operation()
        self.assertFalse(panel.isVisible())
        self.assertFalse(self.w.side_panel_checkbox.isChecked())
        self.w._calibration_dialog_active = False

    def test_shared_news_timer_continues_without_visible_views_and_stops_on_exit(self):
        panel = self.open_panel()
        service = panel.calendar
        panel.suspend()
        self.assertFalse(self.w.news_page.isVisible())
        self.assertTrue(service.refresh_timer.isActive())
        service.source_times = dict.fromkeys(calendar.SOURCE_URLS, datetime.now(calendar.UTC))
        service.start()
        self.assertGreater(service.refresh_timer.interval(), 29_000)
        self.assertLessEqual(service.refresh_timer.interval(), 30_000)
        with patch.object(service, 'refresh') as refresh:
            service.refresh_timer.timeout.emit()
            refresh.assert_called_once_with()
        self.w.close()
        self.assertFalse(service.refresh_timer.isActive())

    def test_approved_incident_actions_do_not_enable_test_symbol_checks(self):
        from dataclasses import replace
        from types import SimpleNamespace
        from trading_helper.test_mode import active_test_symbol_override
        import os
        from test_fill_workflow_guards import sample
        item = replace(sample(), symbol='ETHUSD')
        fake = SimpleNamespace(automation=MagicMock(), log=MagicMock(),
                               emergency=SimpleNamespace(guard=lambda: None),
                               signals=SimpleNamespace(auto_entry_result=MagicMock()))
        request = dict(item=item, internal_platform='cTrader', external_platform='MT5',
                       profile_name='isolated', sheet_url='sheet', symbol='ETHUSD',
                       confirmed_role='internal', confirmed_ticket='1', account_ids={})
        flow = MagicMock()
        def verify_close(*args, **kwargs):
            self.assertEqual(active_test_symbol_override(), '')
            return SimpleNamespace(ticket='1')
        def verify_reenter(*args, **kwargs):
            self.assertEqual(active_test_symbol_override(), '')
            return SimpleNamespace(ticket='1'), SimpleNamespace(ticket='2')
        flow.run_single_leg_close_test.side_effect = verify_close
        flow.run_single_leg_test.side_effect = verify_reenter
        with patch.dict(os.environ, {'TRADING_HELPER_TEST_SYMBOL_OVERRIDE': '',
                                     'TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK': ''}), \
             patch.object(gui, 'AutoEntryWorkflow', return_value=flow), \
             patch.object(gui, 'DemoUiBrokerPort'), \
             patch.object(gui, 'APP_DIR', self.w.store.path.parent):
            for action in ('close', 'reenter'):
                gui.TradingHelperApp._execute_user_approved_incident_action(fake, action, request)


class FeedPollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = calendar.EconomicCalendar(Path(temp.name)/'events.json')
        self.addCleanup(self.service.close)

    def test_news_poll_every_30_seconds_but_calendars_remain_slow(self):
        service = self.service
        now = datetime.now(calendar.UTC)
        service.source_times = dict.fromkeys(calendar.SOURCE_URLS, now-timedelta(seconds=61))
        with patch.object(calendar.threading, 'Thread') as thread:
            service.refresh()
        self.assertEqual(set(thread.call_args.kwargs['args'][0]),
                         {'fed', 'ecb', 'rthk_finance', 'rthk_world'})
        self.assertEqual(calendar.SOURCE_TTLS['ff'], timedelta(minutes=30))
        self.assertEqual(calendar.SOURCE_TTLS['bea'], timedelta(hours=6))

    def test_response_time_does_not_make_30_second_poll_skip_a_whole_cycle(self):
        service = self.service
        now = datetime.now(calendar.UTC)
        service.source_times = dict.fromkeys(calendar.SOURCE_URLS, now-timedelta(seconds=28))
        service._last_attempt = dict.fromkeys(calendar.SOURCE_URLS, now-timedelta(seconds=30))
        with patch.object(calendar.threading, 'Thread') as thread:
            service.refresh()
        self.assertEqual(set(thread.call_args.kwargs['args'][0]),
                         {'fed', 'ecb', 'rthk_finance', 'rthk_world'})

    def test_conditional_request_and_304_preserve_news_and_advance_checked_time(self):
        service = self.service
        response = MagicMock()
        response.__enter__.return_value.headers = {'ETag': '"v1"', 'Last-Modified': 'Mon, 16 Nov 2026 00:00:00 GMT'}
        response.__enter__.return_value.read.return_value = b'<rss><channel><item><title>FOMC statement</title><pubDate>Mon, 16 Nov 2026 00:00:00 GMT</pubDate></item></channel></rss>'
        with patch.object(calendar, 'urlopen', return_value=response):
            service._apply([service._read_source('fed')])
        news = list(service.news)
        self.assertTrue(news)
        old = service.source_times['fed']
        error = HTTPError(calendar.FED_URL, 304, 'Not modified', {}, io.BytesIO())
        with patch.object(calendar, 'urlopen', side_effect=error) as read:
            record = service._read_source('fed')
        headers = dict((key.lower(), value) for key, value in read.call_args.args[0].header_items())
        self.assertEqual(headers['if-none-match'], '"v1"')
        self.assertIn('if-modified-since', headers)
        service._apply([record])
        self.assertEqual(service.news, news)
        self.assertGreaterEqual(service.source_times['fed'], old)
        self.assertNotIn('fed', service.source_errors)

    def test_rate_limit_retry_after_cannot_be_bypassed_by_manual_refresh(self):
        service = self.service
        now = datetime.now(calendar.UTC)
        service.source_times = dict.fromkeys(calendar.SOURCE_URLS, now)
        error = HTTPError(calendar.FEED_URL, 429, 'Too many requests', {'Retry-After': '120'}, io.BytesIO())
        with patch.object(calendar, 'urlopen', side_effect=error):
            record = service._read_source('ff')
        service._apply([record])
        self.assertGreaterEqual(service._retry_at['ff'], now+timedelta(seconds=120))
        self.assertIn('後重試', '\n'.join(service.status_lines(now)))
        with patch.object(calendar.threading, 'Thread') as thread, patch.object(service, '_translate_missing'):
            service.refresh(force=True)
        self.assertNotIn('ff', thread.call_args.kwargs['args'][0])
        self.assertEqual(service.source_times['ff'], now)
        # A successful later response clears backoff, and failures grow it.
        first = service._retry_at['ff']
        service._apply([('ff', None, None, 'offline')])
        self.assertGreaterEqual(service._retry_at['ff'], first)
        service._apply([('ff', [], now, '')])
        self.assertNotIn('ff', service._retry_at)
        self.assertNotIn('ff', service._source_failures)

    def test_slow_network_does_not_block_qt_heartbeat(self):
        service = self.service
        now = datetime.now(calendar.UTC)
        service.source_times = dict.fromkeys(calendar.SOURCE_URLS, now)
        service.source_times['rthk_world'] = now-timedelta(seconds=61)
        gate, entered = threading.Event(), threading.Event()
        def slow_read(key, **kwargs):
            entered.set()
            gate.wait(2)
            return key, [], now, ''
        heartbeat = []
        with patch.object(service, '_read_source', side_effect=slow_read):
            try:
                service.refresh()
                self.assertTrue(entered.wait(1))
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                QTest.qWait(30)
                self.assertEqual(heartbeat, [True])
                self.assertTrue(service._busy)
            finally:
                gate.set()
                for _ in range(100):
                    self.qtapp.processEvents()
                    if not service._busy:
                        break
                    threading.Event().wait(.01)
        self.assertFalse(service._busy)

"""News workspace, forced refresh and shared service; all sources are stubbed."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
import test_compact_followup_controls as fixtures
from trading_helper.calendar_events import CalendarEvent, SOURCE_URLS, UTC


class NewsWorkspaceTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def test_news_works_with_sidebar_off_and_shares_source_results_with_sidebar(self):
        self.w.toggle_side_panel(False)
        self.assertIsNone(getattr(self.w, '_event_calendar', None))
        with patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            self.w.switch_workspace('消息')
            self.qtapp.processEvents()
            service = self.w.news_feed.calendar
            self.assertIsNotNone(service)
            self.assertFalse(self.w.side_panel_checkbox.isChecked())
            self.assertIsNone(self.w.side_panel)
            self.w.toggle_side_panel(True)
            panel = self.w.side_panel
            self.assertIs(service, panel.calendar)
            now = datetime.now(UTC)
            service.events = [CalendarEvent(now+timedelta(hours=1), 'USD', '<b>CPI</b>')]
            service.source_times = dict.fromkeys(SOURCE_URLS, now)
            service.changed.emit()
            self.assertEqual(self.w.news_feed.event_rows.textFormat(), Qt.PlainText)
            self.assertIn('<b>CPI</b>', self.w.news_feed.event_rows.text())
            self.assertEqual(panel.event_rows.text(), self.w.news_feed.event_rows.text())
            panel.close()
            self.assertFalse(service._closed)
            self.w.close()
            self.assertTrue(service._closed)

    def test_manual_buttons_force_one_fetch_and_busy_success_failure_are_visible(self):
        with patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            self.w.switch_workspace('消息')
            self.w.toggle_side_panel(True)
            self.qtapp.processEvents()
        view = self.w.news_feed
        side = self.w.side_panel
        with patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            side.events_button.setChecked(True)
        service = view.calendar
        now = datetime.now(UTC)
        service.source_times = dict.fromkeys(SOURCE_URLS, now)
        service._last_attempt = dict.fromkeys(SOURCE_URLS, now)
        with patch('trading_helper.calendar_events.threading.Thread') as thread, \
             patch.object(service, '_translate_missing'):
            view.refresh_button.click()
            self.assertTrue(service._busy)
            self.assertEqual(view.refresh_button.text(), '更新中')
            self.assertFalse(view.refresh_button.isEnabled())
            self.assertFalse(side.event_view.refresh_button.isEnabled())
            side.event_view.refresh_button.click()
            self.assertEqual(thread.call_count, 1)
            service._apply([('fed', [], now+timedelta(minutes=1), ''), ('ff', None, None, 'offline')])
            self.assertTrue(view.refresh_button.isEnabled())
            self.assertEqual(view.refresh_button.text(), '重整')
            self.assertEqual(service.source_times['ff'], now)
            self.assertIn('待更新', view.event_status.text())
            self.assertEqual(view.source_details.text(), side.source_details.text())
            with patch.object(service, 'refresh') as refresh:
                side.event_view.refresh_button.click()
                refresh.assert_called_once_with(force=True)

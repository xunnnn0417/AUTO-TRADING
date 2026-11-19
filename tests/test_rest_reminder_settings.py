"""Offline editing and shared schedule display, with temporary profile data."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication

import test_compact_followup_controls as fixtures
from trading_helper.calendar_events import TAIPEI, UTC, events_for_display
from trading_helper.rest_reminder_settings import RestReminderSettings


class RestReminderSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_draft_and_invalid_input_do_not_save_and_valid_save_normalizes(self):
        saved = []
        widget = RestReminderSettings(lambda: {}, saved.append)
        self.addCleanup(widget.deleteLater)
        widget.enabled.setChecked(True)
        widget.clock.setTime(QTime(5, 15))
        widget.minutes.setText('30, nope')
        widget.save_button.click()
        self.assertFalse(saved)
        self.assertTrue(widget.status.text())
        widget.minutes.setText('30，60, 30')
        widget.save_button.click()
        self.assertEqual(saved[0]['minutes'], [60, 30])
        self.assertEqual(saved[0]['time'], '05:15')
        self.assertTrue(saved[0]['enabled'])
        self.assertIn('AM', widget.clock.text())
        self.assertTrue(all(check.property('checkmarkOnlyIndicator') for check in [widget.enabled, *widget.days]))


class RestReminderWorkspaceTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def test_save_persists_and_main_sidebar_share_local_rows_without_network(self):
        with patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            self.w.switch_workspace('消息')
            self.w.toggle_side_panel(True)
            self.qtapp.processEvents()
        view = self.w.news_feed
        service = view.calendar
        view.rest_settings_button.click()
        editor = view.rest_editor
        self.assertFalse(editor.isHidden())
        self.assertFalse(editor.enabled.isChecked())
        editor.enabled.setChecked(True)
        editor.clock.setTime(QTime(6, 0))
        editor.save_button.click()
        self.assertTrue(self.w.store.data['ui']['rest_reminder']['enabled'])
        from trading_helper.config import ConfigStore
        self.assertTrue(ConfigStore(self.w.store.path).data['ui']['rest_reminder']['enabled'])
        self.assertIn('休市提醒', view.event_rows.text())
        self.assertIn('即將休市', view.event_rows.text())
        self.assertEqual(view.event_rows.text(), self.w.side_panel.event_rows.text())
        self.assertFalse(hasattr(self.w.side_panel.event_view, 'rest_editor'))
        editor.minutes.setText('15')
        service.changed.emit()
        self.assertEqual(editor.minutes.text(), '15')  # Fetch does not erase draft.
        editor.enabled.setChecked(False)
        editor.save_button.click()
        self.assertNotIn('休市提醒', view.event_rows.text())

    def test_rest_event_summary_is_countdown_even_with_unavailable_external_sources(self):
        from trading_helper.event_summary import event_summary
        with patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            service = self.w._get_event_calendar()
        now = datetime(2026, 11, 20, 5, tzinfo=TAIPEI)
        self.w.store.data['ui']['rest_reminder'] = dict(enabled=True, time='06:00', minutes=[60], days=[4])
        text = event_summary(events_for_display(service, now), now, {}, False)
        self.assertIn('休市', text)
        self.assertIn('再過', text)
        self.assertNotIn('待來源更新', text)

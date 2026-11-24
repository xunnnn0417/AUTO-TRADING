"""Offline editing and shared schedule display, with temporary profile data."""
import unittest
from datetime import datetime
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

import test_compact_followup_controls as fixtures
from trading_helper.calendar_events import TAIPEI, UTC, events_for_display
from trading_helper.rest_reminder_settings import RestReminderSettings


class RestReminderSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_draft_and_invalid_input_do_not_save_and_valid_save_normalizes(self):
        saved, current = [], {}
        def save(value):
            current.update(value)
            saved.append(value)
        widget = RestReminderSettings(lambda: current, save)
        self.addCleanup(widget.deleteLater)
        self.assertEqual(saved, [])  # Opening the settings must not write.
        self.assertFalse(hasattr(widget, 'save_button'))
        widget.enabled.setChecked(True)
        self.assertFalse(hasattr(widget, 'clock'))
        self.assertFalse(hasattr(widget, 'days'))
        self.assertIn('例行休市', widget.schedule_label.text())
        self.assertEqual(set(widget.presets), {30, 60, 90, 120})
        widget.custom.setChecked(True)
        self.assertFalse(widget.custom_input.isHidden())
        widget.custom_input.setText('30, nope')
        count = len(saved)
        widget.custom_input.editingFinished.emit()
        self.assertEqual(len(saved), count)
        self.assertTrue(widget.status.text())
        widget.custom_input.setText('30，60, 30')
        widget.custom_input.editingFinished.emit()
        self.assertEqual(saved[-1]['minutes'], [60, 30])
        self.assertNotIn('time', saved[-1])
        self.assertNotIn('days', saved[-1])
        self.assertTrue(saved[-1]['custom'])
        self.assertTrue(saved[-1]['enabled'])
        self.assertTrue(all(check.property('checkmarkOnlyIndicator') for check in
                            [widget.enabled, widget.custom, *widget.presets.values()]))

    def test_presets_are_multiselect_and_custom_can_be_switched_back(self):
        saved = []
        widget = RestReminderSettings(lambda: {}, saved.append)
        self.addCleanup(widget.deleteLater)
        widget.show()
        widget.advance_menu.popup(widget.advance_button.mapToGlobal(widget.advance_button.rect().bottomLeft()))
        self.qt.processEvents()
        for minutes in (90, 120):
            QTest.mouseClick(widget.presets[minutes], Qt.LeftButton)
            self.assertTrue(widget.advance_menu.isVisible())
        widget.advance_menu.close()
        self.assertEqual(saved[-1]['minutes'], [120, 90, 60, 30])
        widget.custom.setChecked(True)
        widget.custom_input.setText('15, 45')
        widget.custom_input.editingFinished.emit()
        self.assertEqual(saved[-1]['minutes'], [45, 15])
        self.assertTrue(saved[-1]['custom'])
        widget.custom.setChecked(False)
        self.assertFalse(saved[-1]['custom'])
        self.assertEqual(saved[-1]['minutes'], [120, 90, 60, 30])
        widget.close()

    def test_custom_typing_is_debounced_and_profile_change_cannot_write_old_draft(self):
        saved, profile = [], ['A']
        widget = RestReminderSettings(lambda: {}, saved.append, context=lambda: profile[0])
        self.addCleanup(widget.deleteLater)
        widget.show()
        widget.custom.setChecked(True)
        QTest.keyClicks(widget.custom_input, '15')
        self.assertEqual(saved, [])
        timeout = QSignalSpy(widget._save_timer.timeout)
        self.assertTrue(timeout.wait(2000), '自動儲存計時器未觸發')
        self.assertEqual(saved[-1]['minutes'], [15])
        saved.clear()
        widget.custom_input.selectAll()
        QTest.keyClicks(widget.custom_input, '45')
        profile[0] = 'B'
        timeout = QSignalSpy(widget._save_timer.timeout)
        self.assertTrue(timeout.wait(2000), '切換方案後的待存計時器未觸發')
        self.assertEqual(saved, [])
        widget.close()

    def test_disable_still_saves_when_custom_draft_is_invalid(self):
        saved = []
        widget = RestReminderSettings(lambda: dict(enabled=True, minutes=[60, 30]), saved.append)
        self.addCleanup(widget.deleteLater)
        widget.custom.setChecked(True)
        widget.enabled.setChecked(False)
        self.assertFalse(saved[-1]['enabled'])
        self.assertEqual(saved[-1]['minutes'], [60, 30])


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
        self.assertTrue(self.w.store.data['ui']['rest_reminder']['enabled'])
        from trading_helper.config import ConfigStore
        self.assertTrue(ConfigStore(self.w.store.path).data['ui']['rest_reminder']['enabled'])
        self.assertIn('休市提醒', view.event_rows.text())
        self.assertIn('即將休市', view.event_rows.text())
        self.assertEqual(view.event_rows.text(), self.w.side_panel.event_rows.text())
        self.assertFalse(hasattr(self.w.side_panel.event_view, 'rest_editor'))
        editor.custom.setChecked(True)
        editor.custom_input.setText('15')
        service.changed.emit()
        self.assertEqual(editor.custom_input.text(), '15')  # Fetch does not erase draft.
        editor.enabled.setChecked(False)
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

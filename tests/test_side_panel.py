"""Side panel integration with isolated profiles and stubbed I/O only."""
import unittest
from dataclasses import replace
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import test_compact_followup_controls as fixtures
from test_fill_workflow_guards import sample
from trading_helper import gui
from trading_helper.side_panel import SideQuickPanel
from trading_helper.calendar_events import CalendarEvent, UTC


class SidePanelTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def open_panel(self):
        with patch('trading_helper.side_panel.EconomicCalendar.refresh'):
            self.w.toggle_side_panel(True)
            self.qtapp.processEvents()
        return self.w.side_panel

    def test_shared_drafts_placeholders_and_enter_use_existing_update_flow(self):
        panel = self.open_panel()
        self.w.instruction = sample()
        self.w._show_instruction(self.w.instruction)
        panel.sync_from_main()
        self.assertEqual(panel.inputs['internal_balance'].placeholderText(), '50000')
        QTest.keyClicks(panel.inputs['daily_pnl'], '=+10')
        self.assertEqual(self.w.parameter_inputs['daily_pnl'].text(), '=+10')
        self.w.parameter_inputs['daily_pnl'].setText('123')
        panel.sync_from_main()
        self.assertEqual(panel.inputs['daily_pnl'].text(), '123')
        with patch.object(self.w, '_write_trade_parameter_values') as write:
            QTest.keyClick(panel.inputs['daily_pnl'], Qt.Key_Return)
        write.assert_called_once()

    def test_direction_and_fill_delegate_without_second_trade_path(self):
        panel = self.open_panel()
        with patch.object(self.w, '_write_trade_parameter_values') as write:
            panel.direction.setCurrentIndex(1)
        self.assertEqual(self.w.internal_direction_input.currentData(), 'SELL')
        write.assert_called_once()
        with patch.object(self.w, '_launch_fill') as launch:
            panel.fill_button.click()
        launch.assert_called_once_with(('internal', 'external'))

    def test_profile_values_ruler_and_enabled_state_are_mirrored(self):
        panel = self.open_panel()
        self.w.instruction = sample()
        self.w._show_instruction(self.w.instruction)
        panel.sync_from_main()
        self.assertEqual(panel.lots['internal'].text(), '0.40')
        self.assertEqual(panel.ruler.state, self.w.account_ruler.state)
        self.w.instruction = None
        self.w.data_labels['internal_lot'].setText('—')
        self.w._refresh_ruler()
        self.w._active_tasks = 1
        panel.sync_from_main()
        self.assertEqual(panel.lots['internal'].text(), '—')
        self.assertIsNone(panel.ruler.state)
        self.assertFalse(panel.fill_button.isEnabled())
        self.assertTrue(all(not entry.isEnabled() for entry in panel.inputs.values()))
        self.w._active_tasks = 0

    def test_collapse_dock_operation_visibility_and_shutdown(self):
        panel = self.open_panel()
        width = panel.width()
        panel.set_collapsed(True)
        self.assertLess(panel.width(), width)
        panel.set_collapsed(False)
        self.assertEqual(panel.width(), width)
        self.w._hide_for_operation()
        self.assertFalse(panel.isVisible())
        self.w._restore_after_operation()
        self.assertTrue(panel.isVisible())
        self.w.close()
        self.assertFalse(panel.isVisible())
        self.assertFalse(panel.sync_timer.isActive())

    def test_side_fill_collapses_stays_collapsed_and_does_not_restore_main(self):
        panel = self.open_panel()
        def pending_fill(roles):
            self.assertEqual(roles, ('internal', 'external'))
            self.w._active_tasks = 1
            self.w._hide_for_operation()
        with patch.object(self.w, '_launch_fill', side_effect=pending_fill):
            panel.fill_button.click()
        self.assertTrue(panel.collapsed)
        self.w._active_tasks = 0
        self.w._restore_after_operation()
        self.assertFalse(self.w.isVisible())
        self.assertTrue(panel.isVisible())
        self.assertTrue(panel.collapsed)
        # Opening the main UI explicitly restores its original behavior.
        panel.open_main()
        self.assertTrue(panel.collapsed)
        self.assertFalse(self.w._side_fill_active)
        panel.set_collapsed(False)
        with patch.object(self.w, '_launch_fill'):
            self.w.fill_both()
        self.w._hide_for_operation()
        self.w._restore_after_operation()
        self.assertTrue(self.w.isVisible())
        self.assertFalse(panel.collapsed)

    def test_default_on_preference_toggle_and_startup_off_has_no_panel(self):
        self.assertTrue(self.w.side_panel_checkbox.isChecked())
        panel = self.open_panel()
        self.w.toggle_side_panel(False)
        self.assertFalse(panel.isVisible())
        self.assertFalse(panel.event_timer.isActive())
        self.assertFalse(self.w.store.data['ui']['side_panel_enabled'])
        with patch('trading_helper.side_panel.EconomicCalendar.refresh'):
            self.w.initialize_side_panel()
        self.assertFalse(panel.isVisible())

    def test_update_uses_existing_write_or_read_and_event_content_is_plain(self):
        panel = self.open_panel()
        with patch.object(self.w, 'read_sheet') as read, \
             patch('trading_helper.side_panel.EconomicCalendar.refresh'):
            panel.update_button.click()
        read.assert_called_once()
        self.w.parameter_inputs['internal_balance'].setText('51000')
        with patch.object(self.w, '_write_trade_parameter_values') as write, \
             patch('trading_helper.side_panel.EconomicCalendar.refresh'):
            panel.update_button.click()
        write.assert_called_once()
        panel.calendar.events = [CalendarEvent(datetime.now(UTC) + timedelta(hours=1), 'EUR', '<b>Rate</b>')]
        panel.calendar.fetched_at = datetime.now(UTC)
        panel.update_events()
        self.assertIn('1 小時', panel.events_button.text())
        self.assertEqual(panel.event_rows.textFormat(), Qt.PlainText)
        self.assertIn('<b>Rate</b>', panel.event_rows.text())
        panel.calendar.error = '暫時無法更新'
        panel.update_events()
        self.assertIn('資料待更新', panel.events_button.text())
        self.assertNotIn('jin10', panel.event_rows.text().lower())

    def test_placeholder_and_corner_warnings_share_main_conditions_and_actions(self):
        panel = self.open_panel()
        self.w.instruction = replace(sample(), original_sl_points=Decimal('-12'),
                                     expected_sl_points=Decimal('-8.92'))
        self.w._show_instruction(self.w.instruction)
        panel.sync_from_main()
        self.assertEqual(panel.inputs['expected_sl_combined'].placeholderText(), '-8.92')
        self.assertFalse(panel.warnings['expected_sl_combined'].isHidden())
        with patch.object(self.w, '_show_expected_sl_warning') as explain:
            QTest.mouseClick(panel.warnings['expected_sl_combined'], Qt.LeftButton)
        explain.assert_called_once()
        self.w._balance_warning_context = self.w._trade_settings_context()
        panel.sync_from_main()
        self.assertFalse(panel.warnings['internal_balance'].isHidden())
        self.w._balance_warning_context = None
        panel.inputs['expected_sl_combined'].setText('-15')
        self.w.parameter_inputs['expected_sl_combined'].setText('-15')
        panel.sync_from_main()
        self.assertTrue(panel.warnings['internal_balance'].isHidden())
        self.assertTrue(panel.warnings['expected_sl_combined'].isHidden())

    def test_side_fill_cancel_keeps_shared_sl_confirmation_and_no_io(self):
        panel = self.open_panel()
        item = replace(sample(), original_sl_points=Decimal('-12'),
                       expected_sl_points=Decimal('-8.92'))
        self.w.instruction = item
        self.w._show_instruction(item)
        with patch.object(self.w, '_maybe_adjust_repeated_expected_sl', return_value=(item, False)), \
             patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.No) as question, \
             patch.object(self.w, '_start_fill_worker') as start, \
             patch.object(self.w, '_write_trade_parameter_values') as write:
            panel.fill_button.click()
        self.assertIn('確認止損與保證金', question.call_args.args)
        start.assert_not_called()
        write.assert_not_called()
        self.assertTrue(panel.collapsed)

    def test_event_expand_collapse_restores_height_and_control_positions(self):
        panel = self.open_panel()
        original = panel.height()
        button_y, ruler_y = panel.fill_button.y(), panel.ruler.y()
        for _ in range(3):
            panel.events_button.click()
            self.qtapp.processEvents()
            self.assertGreater(panel.height(), original)
            panel.events_button.click()
            self.qtapp.processEvents()
            self.assertEqual(panel.height(), original)
            self.assertEqual((panel.fill_button.y(), panel.ruler.y()), (button_y, ruler_y))

    def test_flush_edge_and_bottom_clamp_preserve_collapsed_anchor(self):
        panel = self.open_panel()
        panel.set_collapsed(True)
        area = panel.screen().availableGeometry()
        panel._y = area.bottom() - panel.height() + 1
        panel.dock()
        anchor = panel.y()
        self.assertEqual(panel.frameGeometry().right(), area.right())
        panel.set_collapsed(False)
        self.qtapp.processEvents()
        self.assertEqual(panel.frameGeometry().bottom(), area.bottom())
        panel.events_button.click()
        self.qtapp.processEvents()
        self.assertEqual(panel.frameGeometry().bottom(), area.bottom())
        panel.events_button.click()
        panel.set_collapsed(True)
        self.qtapp.processEvents()
        self.assertEqual(panel.y(), anchor)
        self.assertEqual(panel.frameGeometry().right(), area.right())

    def test_handle_long_press_floats_as_ball_and_release_snaps_without_opening(self):
        panel = self.open_panel()
        panel.set_collapsed(True)
        QTest.mousePress(panel.handle, Qt.LeftButton)
        QTest.qWait(240)
        self.assertEqual(panel.width(), panel.height())
        self.assertFalse(panel.mask().isEmpty())
        area = panel.screen().availableGeometry()
        destination = QPoint(area.left() + 100, area.top() + 400)
        local = panel.handle.mapFromGlobal(destination)
        event = QMouseEvent(QEvent.MouseMove, QPointF(local), QPointF(destination),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(panel.handle, event)
        self.assertLess(panel.x(), area.right() - 100)
        release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(panel.handle.mapFromGlobal(destination)),
                              QPointF(destination), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(panel.handle, release)
        self.qtapp.processEvents()
        self.assertTrue(panel.collapsed)
        self.assertTrue(panel.mask().isEmpty())
        self.assertEqual(panel.frameGeometry().right(), area.right())
        self.assertEqual(panel.y(), destination.y() - panel.height() // 2)
        self.assertEqual(self.w.store.data['ui']['side_panel_y'], panel.y())
        QTest.mouseClick(panel.handle, Qt.LeftButton)
        self.assertFalse(panel.collapsed)

    def test_disabling_while_holding_cancels_drag_and_can_be_reopened(self):
        panel = self.open_panel()
        panel.set_collapsed(True)
        QTest.mousePress(panel.handle, Qt.LeftButton)
        QTest.qWait(240)
        self.w.toggle_side_panel(False)
        self.assertFalse(panel._hold_timer.isActive())
        self.assertIsNone(panel._handle_press)
        self.assertFalse(panel._handle_dragging)
        with patch('trading_helper.side_panel.EconomicCalendar.refresh'):
            self.w.toggle_side_panel(True)
        self.assertTrue(panel.mask().isEmpty())
        QTest.mouseClick(panel.handle, Qt.LeftButton)
        self.assertFalse(panel.collapsed)

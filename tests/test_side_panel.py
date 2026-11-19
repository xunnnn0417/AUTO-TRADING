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
from trading_helper.calendar_events import CalendarEvent, UTC, SOURCE_URLS


class SidePanelTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def open_panel(self):
        no_network = patch('trading_helper.calendar_events.EconomicCalendar.refresh')
        no_network.start()
        self.addCleanup(no_network.stop)
        self.w.toggle_side_panel(True)
        self.qtapp.processEvents()
        return self.w.side_panel

    def test_late_window_move_is_redocked_after_geometry_events_settle(self):
        panel = self.open_panel()
        area = panel._screen.availableGeometry()
        for collapsed in (False, True, False):
            panel.set_collapsed(collapsed)
            # Reproduce the screenshot: an expanded panel retains the parked
            # handle's x-coordinate after a late native geometry update.
            panel.move(area.right()-27, panel.y())
            self.qtapp.processEvents()
            self.qtapp.processEvents()
            self.assertLessEqual(panel.frameGeometry().right(), area.right())
            self.assertGreaterEqual(panel.frameGeometry().left(), area.left())

    def test_periodic_sync_repairs_native_drift_even_without_qt_move_events(self):
        panel = self.open_panel()
        with patch('trading_helper.side_panel.ensure_native_sidebar') as repair:
            panel.sync_from_main()
            repair.assert_called_once()
            self.assertIs(repair.call_args.args[0], panel)
            panel._handle_dragging = True
            repair.reset_mock()
            panel.sync_from_main()
            repair.assert_not_called()
            panel._handle_dragging = False

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

    def test_sidebar_stage_mirrors_options_and_uses_main_setting_flow(self):
        from trading_helper.sheet_preferences import TradeSheetSettings
        panel = self.open_panel()
        settings = TradeSheetSettings('第一階段', ('第一階段','真金階段'),
                                     dict(C2=False,B6=False,E14=True))
        self.w._show_trade_sheet_settings((self.w._trade_settings_context(),settings,''))
        with patch.object(self.w, '_confirm_trade_setting') as change:
            panel.sync_from_main()
            change.assert_not_called()
            self.assertEqual(panel.stage_selector.currentText(),'第一階段')
            panel.stage_selector.setCurrentText('真金階段')
            change.assert_called_once_with('A4','真金階段')
        self.w._trade_settings_busy = True
        panel.sync_from_main()
        self.assertFalse(panel.stage_selector.isEnabled())
        self.w._trade_settings_busy = False

    def test_stage_popup_keyboard_selection_keeps_the_shared_stage_action(self):
        from trading_helper.sheet_preferences import TradeSheetSettings
        panel = self.open_panel()
        settings = TradeSheetSettings('第一階段', ('第一階段', '真金階段'), dict(C2=False, B6=False, E14=True))
        self.w._show_trade_sheet_settings((self.w._trade_settings_context(), settings, ''))
        panel.sync_from_main()
        combo = panel.stage_selector
        with patch.object(self.w, '_confirm_trade_setting') as change:
            combo.showPopup()
            self.qtapp.processEvents()
            self.assertTrue(combo.view().isVisible())
            QTest.keyClick(combo.view(), Qt.Key_Down)
            QTest.keyClick(combo.view(), Qt.Key_Return)
            self.qtapp.processEvents()
            self.assertFalse(combo.view().isVisible())
            self.assertEqual(combo.currentText(), '真金階段')
            change.assert_called_once_with('A4', '真金階段')

    def test_sidebar_has_only_one_seconds_countdown_without_more_source_requests(self):
        panel = self.open_panel()
        now = datetime.now(UTC)
        panel.calendar.events = [CalendarEvent(now+timedelta(seconds=42),'USD','CPI')]
        with patch('trading_helper.side_panel.datetime') as clock, \
                patch.object(panel.calendar,'refresh') as refresh:
            clock.now.return_value = now
            panel.update_event_summary()
            self.assertIn('42 秒',panel.events_button.text())
            clock.now.return_value = now+timedelta(seconds=1)
            panel.update_event_summary()
            self.assertIn('41 秒',panel.events_button.text())
            refresh.assert_not_called()
        self.assertEqual(panel.summary_timer.interval(),1000)
        self.assertTrue(panel.event_view.countdown_label.isHidden())
        self.assertFalse(panel.event_view.countdown_timer.isActive())

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
        with patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            self.w.initialize_side_panel()
        self.assertFalse(panel.isVisible())

    def test_update_uses_existing_write_or_read_and_event_content_is_plain(self):
        panel = self.open_panel()
        with patch.object(self.w, 'read_sheet') as read, \
             patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            panel.update_button.click()
        read.assert_called_once()
        self.w.parameter_inputs['internal_balance'].setText('51000')
        with patch.object(self.w, '_write_trade_parameter_values') as write, \
             patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            panel.update_button.click()
        write.assert_called_once()
        panel.calendar.events = [CalendarEvent(datetime.now(UTC) + timedelta(hours=1), 'EUR', '<b>Rate</b>')]
        panel.calendar.fetched_at = datetime.now(UTC)
        panel.calendar.source_times = dict.fromkeys(SOURCE_URLS, datetime.now(UTC))
        panel.update_events()
        self.assertIn('1 小時', panel.events_button.text())
        self.assertFalse(panel.event_rows.openExternalLinks())
        self.assertIn('<b>Rate</b>', panel.event_rows.text())
        self.assertIn('&lt;b&gt;Rate&lt;/b&gt;', panel.event_rows.toHtml())
        panel.calendar.error = '暫時無法更新'
        panel.update_events()
        self.assertIn('待更新', panel.event_status.text())
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
        explain.assert_not_called()
        self.assertTrue(panel.warning_flyout.isVisible())
        self.assertIn('-8.92', panel.warning_numbers.text())
        self.w._balance_warning_context = self.w._trade_settings_context()
        panel.sync_from_main()
        self.assertFalse(panel.warnings['internal_balance'].isHidden())
        self.w._balance_warning_context = None
        panel.inputs['expected_sl_combined'].setText('-15')
        self.w.parameter_inputs['expected_sl_combined'].setText('-15')
        panel.sync_from_main()
        self.assertTrue(panel.warnings['internal_balance'].isHidden())
        self.assertFalse(panel.warnings['expected_sl_combined'].isHidden())
        self.w.reader.read = lambda _: replace(self.w.instruction, expected_sl_points=Decimal('-15'))
        self.w.reader.read_a1_values = lambda config, cells: {cell: '' for cell in cells}
        self.w._read_sheet_task()
        self.qtapp.processEvents()
        panel.sync_from_main()
        self.assertTrue(panel.warnings['expected_sl_combined'].isHidden())

    def warning_panel(self):
        panel = self.open_panel()
        self.w.instruction = replace(sample(), original_sl_points=Decimal('-12'),
                                     expected_sl_points=Decimal('-8.92'))
        self.w._show_instruction(self.w.instruction)
        self.w._balance_warning_context = self.w._trade_settings_context()
        panel.sync_from_main()
        return panel

    def test_side_warning_is_nonmodal_toggles_switches_and_keeps_main_hidden(self):
        panel = self.warning_panel()
        self.w.hide()
        panel.events_button.setChecked(True)
        QTest.mouseClick(panel.warnings['expected_sl_combined'], Qt.LeftButton)
        self.qtapp.processEvents()
        self.assertTrue(panel.warning_flyout.isVisible())
        self.assertFalse(panel.collapsed)
        self.assertFalse(panel.event_flyout.isVisible())
        self.assertFalse(self.w.isVisible())
        self.assertIsNone(QApplication.activeModalWidget())
        self.assertEqual(panel.warning_text.textFormat(), Qt.PlainText)
        self.assertLessEqual(panel.warning_flyout.frameGeometry().right(), panel.x())
        QTest.mouseClick(panel.warnings['internal_balance'], Qt.LeftButton)
        self.assertEqual(panel.warning_title.text(), '場內餘額提醒')
        self.assertTrue(panel.warning_flyout.isVisible())
        QTest.mouseClick(panel.warnings['internal_balance'], Qt.LeftButton)
        self.assertFalse(panel.warning_flyout.isVisible())
        panel._show_warning('expected_sl_combined')
        QTest.keyClick(panel.warning_flyout, Qt.Key_Escape)
        self.assertFalse(panel.warning_flyout.isVisible())
        self.assertFalse(panel.collapsed)

    def test_warning_outside_click_passes_through_and_lifecycle_dismisses(self):
        panel = self.warning_panel()
        panel._show_warning('expected_sl_combined')
        QTest.mouseClick(panel.inputs['daily_pnl'], Qt.LeftButton)
        QTest.keyClicks(panel.inputs['daily_pnl'], '123')
        self.assertFalse(panel.warning_flyout.isVisible())
        self.assertEqual(self.w.parameter_inputs['daily_pnl'].text(), '123')
        panel._show_warning('expected_sl_combined')
        self.w._active_tasks = 1
        panel.sync_from_main()
        self.assertFalse(panel.warning_flyout.isVisible())
        self.w._active_tasks = 0
        panel.sync_from_main()
        panel._show_warning('expected_sl_combined')
        panel.set_collapsed(True)
        self.assertFalse(panel.warning_flyout.isVisible())
        panel.set_collapsed(False)
        panel._show_warning('expected_sl_combined')
        self.w.toggle_side_panel(False)
        self.assertFalse(panel.warning_flyout.isVisible())

    def test_warning_clamps_to_screen_and_disappears_when_context_or_warning_changes(self):
        panel = self.warning_panel()
        area = panel.screen().availableGeometry()
        for y in (area.top(), area.bottom()):
            panel._y = y
            panel.dock()
            panel._show_warning('expected_sl_combined')
            self.assertTrue(area.contains(panel.warning_flyout.frameGeometry()))
            panel._hide_warning()
        panel._show_warning('expected_sl_combined')
        with patch.object(self.w, '_trade_settings_context', return_value=('different',)):
            panel.sync_from_main()
        self.assertFalse(panel.warning_flyout.isVisible())
        panel._show_warning('expected_sl_combined')
        self.w.reader.read = lambda _: replace(self.w.instruction, expected_sl_points=Decimal('-15'))
        self.w.reader.read_a1_values = lambda config, cells: {cell: '' for cell in cells}
        self.w._read_sheet_task()
        self.qtapp.processEvents()
        panel.sync_from_main()
        self.assertFalse(panel.warning_flyout.isVisible())

    def test_source_status_is_one_line_and_details_are_available_on_demand(self):
        panel = self.open_panel()
        self.assertNotIn('\n', panel.event_status.text())
        self.assertIn('來源', panel.event_status.text())
        self.assertIn('Forex Factory', panel.event_status.toolTip())
        self.assertLess(panel.event_status.sizeHint().height(), 35)

    def test_far_away_schedule_is_distinct_from_recent_chinese_news(self):
        from trading_helper.calendar_events import Announcement, SOURCE_URLS
        panel = self.open_panel()
        now = datetime.now(UTC)
        panel.calendar.source_times = dict.fromkeys(SOURCE_URLS, now)
        panel.calendar.events = [CalendarEvent(now + timedelta(days=10), 'USD', 'GDP')]
        panel.calendar.news = [Announcement(now-timedelta(hours=1), '香港電台財經', '金價受美元走強影響')]
        panel.update_events()
        self.assertNotIn('10 天', panel.events_button.text())
        self.assertIn('下一場', panel.events_button.text())
        self.assertNotIn('金價受美元走強影響', panel.news_rows.text())
        self.assertIn('GDP', panel.event_rows.text())

    def test_event_sources_start_collapsed_each_time_and_only_two_tabs_remain(self):
        panel = self.open_panel()
        self.assertEqual([panel.event_tabs.tabText(i) for i in range(panel.event_tabs.count())], ['即將發生', '已公布／新聞'])
        panel.events_button.setChecked(True)
        self.assertFalse(panel.event_status.isChecked())
        panel.event_status.setChecked(True)
        self.assertTrue(panel.source_details.isVisible())
        panel.events_button.setChecked(False)
        panel.events_button.setChecked(True)
        self.assertFalse(panel.event_status.isChecked())
        self.assertFalse(panel.source_details.isVisible())
        self.assertIn('今日事件範圍', panel.events_button.toolTip())
        self.assertNotIn('提醒交易日', panel.events_button.toolTip())

    def test_news_outside_click_dismisses_only_news_and_preserves_click(self):
        panel = self.open_panel()
        panel.events_button.setChecked(True)
        self.assertTrue(panel.event_flyout.isVisible())
        QTest.mouseClick(panel.event_tabs.tabBar(), Qt.LeftButton)
        self.assertTrue(panel.event_flyout.isVisible())
        QTest.mouseClick(panel.inputs['daily_pnl'], Qt.LeftButton)
        self.assertTrue(panel.event_flyout.isVisible())
        QTest.mouseClick(self.w.parameter_inputs['daily_pnl'], Qt.LeftButton)
        self.assertFalse(panel.event_flyout.isVisible())
        self.assertFalse(panel.events_button.isChecked())
        self.assertTrue(panel.isVisible())
        self.assertFalse(panel.collapsed)
        QTest.keyClicks(self.w.parameter_inputs['daily_pnl'], '123')
        self.assertEqual(self.w.parameter_inputs['daily_pnl'].text(), '123')

    def test_native_window_presses_on_news_controls_do_not_dismiss_flyout(self):
        panel = self.open_panel()
        panel.events_button.setChecked(True)
        self.qtapp.processEvents()
        for widget in (panel.event_view.refresh_button, panel.event_status, panel.news_rows.viewport()):
            global_point = QPointF(widget.mapToGlobal(widget.rect().center()))
            event = QMouseEvent(QEvent.MouseButtonPress, QPointF(widget.rect().center()),
                                global_point, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            panel.eventFilter(panel.event_flyout.windowHandle(), event)
            self.assertTrue(panel.event_flyout.isVisible())
        with patch.object(panel.calendar, 'refresh') as refresh:
            QTest.mouseClick(panel.event_view.refresh_button, Qt.LeftButton)
            refresh.assert_called_once_with(force=True)
        QTest.mouseClick(panel.event_status, Qt.LeftButton)
        self.assertTrue(panel.source_details.isVisible())
        self.assertTrue(panel.event_flyout.isVisible())

    def test_news_switching_to_another_app_dismisses_without_hiding_sidebar(self):
        panel = self.open_panel()
        panel.events_button.setChecked(True)
        QApplication.sendEvent(self.qtapp, QEvent(QEvent.ApplicationDeactivate))
        self.assertFalse(panel.event_flyout.isVisible())
        self.assertFalse(panel.events_button.isChecked())
        self.assertTrue(panel.isVisible())
        self.assertFalse(panel.collapsed)
        panel.events_button.setChecked(True)
        self.assertTrue(panel.event_flyout.isVisible())
        self.assertFalse(panel.event_status.isChecked())

    def test_single_line_event_summary_keeps_full_title_in_tooltip(self):
        panel = self.open_panel()
        now = datetime.now(UTC)
        title = '美國消費者物價指數公布與政策影響' * 8
        panel.calendar.events = [CalendarEvent(now+timedelta(minutes=1), 'USD', title)]
        panel.update_events()
        self.assertNotIn('\n', panel.events_button.text())
        self.assertIn(title, panel.events_button.toolTip())
        self.assertLess(panel.events_button.height(), 35)
        self.assertIn('消息可能延遲或漏報', panel.source_details.text())
        self.assertNotIn('GDP/PCE', panel.source_details.text())
        self.assertLess(len(panel.source_details.text().splitlines()), 9)

    def test_side_balance_draft_shares_range_badge_and_fill_guard(self):
        from test_progress_ruler import sheet_values
        panel = self.open_panel()
        self.w.instruction = sample()
        self.w._show_instruction(self.w.instruction)
        self.w.ruler_sheet_values = sheet_values()
        QTest.keyClicks(panel.inputs['internal_balance'], '56000')
        panel.sync_from_main()
        self.assertFalse(panel.warnings['internal_balance'].isVisible())
        self.w.instruction = replace(self.w.instruction, internal_balance=Decimal('56000'))
        self.w._show_instruction(self.w.instruction)
        panel.sync_from_main()
        self.assertTrue(panel.warnings['internal_balance'].isVisible())
        self.assertTrue(self.w.balance_warning_badge.isVisible())
        self.assertIn('高於帳號獲利目標', panel.warnings['internal_balance'].toolTip())
        with patch.object(gui.QMessageBox, 'warning') as warning, \
             patch.object(self.w, '_start_fill_worker') as worker:
            panel.fill_button.click()
        warning.assert_called_once()
        worker.assert_not_called()
        panel.set_collapsed(False)
        panel.inputs['internal_balance'].selectAll()
        QTest.keyClicks(panel.inputs['internal_balance'], '50000')
        panel.sync_from_main()
        self.assertTrue(panel.warnings['internal_balance'].isVisible())
        self.assertTrue(self.w.balance_warning_badge.isVisible())

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
            self.assertEqual(panel.height(), original)
            self.assertTrue(panel.event_flyout.isVisible())
            self.assertLessEqual(panel.event_flyout.frameGeometry().right(), panel.frameGeometry().left())
            panel.events_button.click()
            self.qtapp.processEvents()
            self.assertEqual(panel.height(), original)
            self.assertFalse(panel.event_flyout.isVisible())
            self.assertEqual((panel.fill_button.y(), panel.ruler.y()), (button_y, ruler_y))
        panel.events_button.click()
        panel.event_flyout.close()
        self.assertFalse(panel.events_button.isChecked())
        panel.events_button.click()
        self.assertTrue(panel.event_flyout.isVisible())
        self.w._hide_for_operation()
        self.assertFalse(panel.event_flyout.isVisible())
        self.assertFalse(panel.events_button.isChecked())
        self.w._restore_after_operation()

    def test_flush_edge_and_bottom_clamp_collapse_at_current_panel_top(self):
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
        opened_top = panel.y()
        panel.events_button.click()
        self.qtapp.processEvents()
        self.assertEqual(panel.frameGeometry().bottom(), area.bottom())
        panel.events_button.click()
        panel.set_collapsed(True)
        self.qtapp.processEvents()
        self.assertNotEqual(panel.y(), anchor)
        self.assertEqual(panel.y(), opened_top)
        self.assertEqual(panel.frameGeometry().right(), area.right())

    def test_handle_long_press_floats_as_ball_and_release_snaps_without_opening(self):
        panel = self.open_panel()
        panel.set_collapsed(True)
        QTest.mousePress(panel.handle, Qt.LeftButton)
        for _ in range(50):
            if panel._handle_dragging:
                break
            QTest.qWait(20)
        self.assertTrue(panel._handle_dragging)
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

    def test_collapse_button_drags_only_vertically_and_short_click_collapses(self):
        panel = self.open_panel()
        button = panel.collapse_button
        old = panel.pos()
        QTest.mousePress(button, Qt.LeftButton)
        destination = button.mapToGlobal(button.rect().center()) + QPoint(-70, 60)
        event = QMouseEvent(QEvent.MouseMove, QPointF(button.mapFromGlobal(destination)), QPointF(destination),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(button, event)
        release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(button.mapFromGlobal(destination)),
                              QPointF(destination), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(button, release)
        self.assertFalse(panel.collapsed)
        self.assertEqual(panel.x(), old.x())
        self.assertEqual(panel.y(), old.y() + 60)
        self.assertTrue(panel.mask().isEmpty())
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertTrue(panel.collapsed)

    def test_progress_heading_is_closer_to_chart_than_action_and_main_is_unchanged(self):
        panel = self.open_panel()
        self.assertTrue(panel.ruler.compact)
        self.assertFalse(self.w.account_ruler.compact)
        heading = panel.progress_label
        above = heading.y() - panel.fill_button.geometry().bottom()
        below = panel.ruler.y() + 14 - heading.geometry().bottom()
        self.assertLess(below, above)
        self.assertGreaterEqual(below, 0)
        width, starts = panel.ruler._label_positions([(30,()), (90,()), (180,()), (280,())],
                                                    panel.ruler.width(), min_width=66)
        self.assertGreaterEqual(starts[0], 0)
        self.assertLessEqual(starts[-1]+width, panel.ruler.width())

    def test_disabling_while_holding_cancels_drag_and_can_be_reopened(self):
        panel = self.open_panel()
        panel.set_collapsed(True)
        QTest.mousePress(panel.handle, Qt.LeftButton)
        QTest.qWait(240)
        self.w.toggle_side_panel(False)
        self.assertFalse(panel._hold_timer.isActive())
        self.assertIsNone(panel._handle_press)
        self.assertFalse(panel._handle_dragging)
        with patch('trading_helper.calendar_events.EconomicCalendar.refresh'):
            self.w.toggle_side_panel(True)
        self.assertTrue(panel.mask().isEmpty())
        QTest.mouseClick(panel.handle, Qt.LeftButton)
        self.assertFalse(panel.collapsed)

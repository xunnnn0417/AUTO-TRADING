"""Isolated Qt UI: no real sheets, broker windows, or personal profiles."""
import unittest
from unittest.mock import MagicMock, patch

from trading_helper import gui
import test_compact_followup_controls as ui_fixture
from test_trade_sheet_settings import FakePreferencesReader
from trading_helper.sheet_preferences import read_trade_settings


class TradeSettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ui_fixture.CompactFollowUpControlsTests.setUpClass.__func__(cls)
    setUp=ui_fixture.CompactFollowUpControlsTests.setUp
    tearDown=ui_fixture.CompactFollowUpControlsTests.tearDown

    def load_settings(self):
        w=self.w
        w.reader=FakePreferencesReader()
        settings=read_trade_settings(w.reader,w.store.data['sheet'])
        with patch.object(gui.QMessageBox,'question') as confirm:
            w._show_trade_sheet_settings((w._trade_settings_context(),settings,''))
        confirm.assert_not_called()
        return settings

    def test_loaded_settings_match_sheet_and_never_write_on_load(self):
        self.load_settings()
        self.assertEqual(self.w.stage_selector.currentText(),'階段甲')
        self.assertEqual(self.w.stage_selector.count(),2)
        self.assertFalse(self.w.trade_rule_checkboxes['C2'].isChecked())
        self.assertTrue(self.w.trade_rule_checkboxes['E14'].isChecked())
        self.assertEqual(self.w.reader.writes,[])

    def test_each_rule_asks_before_writing_and_cancel_keeps_original(self):
        self.load_settings()
        for cell,checkbox in self.w.trade_rule_checkboxes.items():
            with self.subTest(cell=cell),patch.object(gui.QMessageBox,'question',return_value=gui.QMessageBox.No) as confirm,\
                 patch.object(self.w,'_start') as start:
                before=checkbox.isChecked();checkbox.click()
                confirm.assert_called_once()
                self.assertEqual(checkbox.isChecked(),before)
                self.assertEqual(confirm.call_args.kwargs['no_text'],'取消')
                start.assert_not_called()
        self.assertEqual(self.w.reader.writes,[])

    def test_confirmed_rule_writes_only_after_consent_and_refreshes(self):
        self.load_settings()
        with patch.object(gui.QMessageBox,'question',return_value=gui.QMessageBox.Yes),\
             patch.object(self.w,'_start') as start,\
             patch.object(self.w,'_read_sheet_task') as refresh:
            self.w.trade_rule_checkboxes['C2'].click()
            self.assertEqual(self.w.reader.writes,[])
            self.assertFalse(self.w.trade_rule_checkboxes['C2'].isChecked())
            self.assertTrue(self.w._trade_settings_busy)
            start.call_args.args[1]()
            self.qtapp.processEvents()
        self.assertEqual(self.w.reader.writes,[{'C2':'是'}])
        refresh.assert_called_once_with(retries=2)
        self.assertTrue(self.w.trade_rule_checkboxes['C2'].isChecked())
        self.assertFalse(self.w._trade_settings_busy)

    def test_stage_choice_confirms_and_refreshes_same_a4(self):
        self.load_settings()
        with patch.object(gui.QMessageBox,'question',return_value=gui.QMessageBox.Yes),\
             patch.object(self.w,'_start') as start,\
             patch.object(self.w,'_read_sheet_task'):
            self.w.stage_selector.setCurrentIndex(1)
            start.call_args.args[1]()
            self.qtapp.processEvents()
        self.assertEqual(self.w.reader.writes,[{'A4':'真金階段'}])
        self.assertEqual(self.w.stage_selector.currentText(),'真金階段')

    def test_all_three_rules_require_confirmation_in_both_directions(self):
        self.load_settings()
        for cell,checkbox in self.w.trade_rule_checkboxes.items():
            for _ in range(2):
                with self.subTest(cell=cell),patch.object(gui.QMessageBox,'question',return_value=gui.QMessageBox.Yes) as confirm,\
                     patch.object(self.w,'_start') as start,patch.object(self.w,'_read_sheet_task'):
                    target=not checkbox.isChecked();checkbox.click()
                    confirm.assert_called_once()
                    self.assertIn('啟用' if target else '關閉',confirm.call_args.args[2])
                    start.call_args.args[1]();self.qtapp.processEvents()
                    self.assertEqual(self.w.reader.writes[-1],{cell:'是' if target else '否'})
                    self.assertEqual(checkbox.isChecked(),target)

    def test_failed_write_disables_controls_and_invalidates_old_instruction(self):
        from trading_helper.models import ValidationError
        self.load_settings();self.w.reader.bad_readback=True
        self.w.instruction=object()
        with patch.object(gui.QMessageBox,'question',return_value=gui.QMessageBox.Yes),patch.object(self.w,'_start') as start:
            self.w.trade_rule_checkboxes['C2'].click()
            with self.assertRaisesRegex(ValidationError,'重新讀取'):
                start.call_args.args[1]()
            self.qtapp.processEvents()
        self.assertIsNone(self.w.instruction)
        self.assertFalse(self.w._trade_settings_busy)
        self.assertTrue(all(not c.isEnabled() for c in self.w.trade_rule_checkboxes.values()))
        self.assertEqual(self.w.reader.writes,[{'C2':'是'}])

    def test_stale_reply_and_failed_read_do_not_enable_controls(self):
        settings=self.load_settings()
        context=self.w._trade_settings_context()
        self.w._show_trade_sheet_settings((context,None,'讀取失敗'))
        self.assertFalse(self.w.stage_selector.isEnabled())
        self.assertTrue(all(not c.isEnabled() for c in self.w.trade_rule_checkboxes.values()))
        self.w._show_trade_sheet_settings((('other-profile',*context[1:]),settings,''))
        self.assertFalse(self.w.stage_selector.isEnabled())

    def test_new_profile_platforms_require_choice_and_preserve_old_scheme(self):
        w=self.w;old=w.profiles.active_name
        w.save_ui_state();old_platforms=(w.internal_platform.currentText(),w.external_platform.currentText())
        w.profiles.create('新方案',w.store.data)
        w.store.data=w.profiles.load_profile();w._apply_profile_ui()
        w.switch_workspace('交易');self.qtapp.processEvents()
        for combo in (w.internal_platform,w.external_platform):
            self.assertEqual(combo.currentIndex(),-1)
            self.assertEqual(combo.placeholderText(),'請選擇')
            self.assertTrue(w._platform_selection_dots[combo].isVisible())
        w.internal_platform.setCurrentText('MT5')
        self.assertFalse(w._platform_selection_dots[w.internal_platform].isVisible())
        self.assertTrue(w._platform_selection_dots[w.external_platform].isVisible())
        previous=w.profiles.load_profile(old)['ui']
        self.assertEqual((previous['internal_platform'],previous['external_platform']),old_platforms)

    def test_platform_not_selected_cannot_bind_or_start_broker_operation(self):
        self.w.internal_platform.setCurrentIndex(-1)
        with patch.object(gui.QMessageBox,'warning') as warning:
            self.assertFalse(self.w.bind_role_window('internal'))
            self.w._start('同步場外止盈止損',MagicMock())
        self.assertEqual(warning.call_count,2)
        self.assertEqual(self.w._active_tasks,0)

    def test_rules_share_automation_row_and_fit_with_a_vertical_divider(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QFrame
        self.load_settings()
        for width,height in ((1438,825),(1150,630),(1020,580)):
            with self.subTest(width=width):
                self.w.resize(width,height);self.w.switch_workspace('交易');self.qtapp.processEvents()
                parent=self.w.auto_draw_tv_after_entry.parentWidget()
                separator=parent.findChild(QFrame,'tradeRuleSeparator')
                self.assertEqual(separator.frameShape(),QFrame.VLine)
                self.assertLess(self.w.auto_draw_tv_after_entry.x(),separator.x())
                previous=separator.x()
                for checkbox in self.w.trade_rule_checkboxes.values():
                    self.assertIs(checkbox.parentWidget(),parent)
                    self.assertGreater(checkbox.x(),previous)
                    self.assertLessEqual(checkbox.x()+checkbox.width(),parent.width())
                    self.assertLessEqual(abs(checkbox.y()-self.w.auto_draw_tv_after_entry.y()),2)
                    previous=checkbox.x()

    def test_single_side_fill_only_requires_its_selected_platform(self):
        self.w.internal_platform.setCurrentText('cTrader')
        self.w.external_platform.setCurrentIndex(-1)
        with patch.object(gui.QMessageBox,'warning') as warning,patch.object(gui.threading,'Thread') as thread:
            self.w._start('填入場內',MagicMock())
        warning.assert_not_called()
        thread.return_value.start.assert_called_once()

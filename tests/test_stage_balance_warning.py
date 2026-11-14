"""Stage persistence and balance warnings use isolated sheet and Qt fixtures."""
import unittest
from unittest.mock import MagicMock, patch

from trading_helper import gui
from trading_helper.models import InvalidInternalTakeProfit, TradeInstruction, ValidationError
from trading_helper.sheet_preferences import read_trade_settings
from test_models import valid_values
from test_trade_sheet_settings import FakePreferencesReader
import test_compact_followup_controls as ui_fixture


class BalanceReader(FakePreferencesReader):
    def __init__(self):
        super().__init__()
        self.balance = '50000'

    def read(self, config):
        values = valid_values()
        values['internal_balance'] = self.balance
        values['daily_pnl'] = '-123.45' if self.values['A4'] == '真金階段' else '50'
        values['internal_entry_price'] = '2345.67'
        values['expected_sl_points'] = '-8.92'
        values['original_sl_points'] = '-8.35'
        if self.values['A4'] == '真金階段' and self.balance == '50000':
            values['internal_tp_points'] = '0'
        return TradeInstruction.from_mapping(4, values)

    def read_a1_values(self, config, cells):
        return {cell: '' for cell in cells}

    def read_field_values(self, config, fields, **kwargs):
        return {'C6': self.balance}

    def write_field_values(self, config, values, **kwargs):
        assert set(values) == {'internal_balance'}
        self.balance = values['internal_balance']
        self.writes.append({'C6': self.balance})
        return {'internal_balance': 'C6'}


class StageBalanceWarningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ui_fixture.CompactFollowUpControlsTests.setUpClass.__func__(cls)

    setUp = ui_fixture.CompactFollowUpControlsTests.setUp
    tearDown = ui_fixture.CompactFollowUpControlsTests.tearDown

    def load(self):
        self.w.reader = BalanceReader()
        context = self.w._trade_settings_context()
        self.w._show_trade_sheet_settings((context, read_trade_settings(
            self.w.reader, self.w.store.data['sheet']), ''))
        self.w.instruction = self.w.reader.read(self.w.store.data['sheet'])
        self.w._show_instruction(self.w.instruction)

    def change_stage(self):
        with patch.object(self.w, '_start') as start, patch.object(gui.time, 'sleep'):
            self.w.stage_selector.setCurrentIndex(1)
            with self.assertRaises(ValidationError):
                start.call_args.args[1]()
            self.qtapp.processEvents()

    def test_confirmed_stage_survives_invalid_take_profit_and_stays_selectable(self):
        self.load()
        self.change_stage()
        self.assertEqual(self.w.reader.writes, [{'A4': '真金階段'}])
        self.assertEqual(self.w.stage_selector.currentText(), '真金階段')
        self.assertTrue(self.w.stage_selector.isEnabled())
        self.assertTrue(self.w.balance_warning_badge.isVisible())
        self.assertIs(type(self.w.balance_warning_badge), type(self.w.expected_sl_warning_badge))
        self.assertEqual(self.w.balance_warning_badge.size(), self.w.expected_sl_warning_badge.size())
        self.assertEqual(self.w.balance_warning_badge.x(), self.w.balance_warning_container.width()-14)
        self.assertEqual(self.w.balance_warning_badge.y(), 1)
        self.assertIsNone(self.w.instruction)
        self.assertEqual(self.w.data_labels['internal_tp'].text(), '0')
        self.assertTrue(self.w.parameter_inputs['internal_balance'].isEnabled())

    def test_warning_blocks_both_single_fills_and_worker_entry_without_writes(self):
        self.load()
        self.change_stage()
        before = list(self.w.reader.writes)
        with patch.object(gui.QMessageBox, 'warning') as warning, \
             patch.object(self.w, '_start') as start:
            self.w.fill_both()
            self.w.fill_role('internal')
            self.w.fill_role('external')
            self.assertEqual(warning.call_count, 3)
            self.assertTrue(all('修改場內餘額' in c.args[2] for c in warning.call_args_list))
            start.assert_not_called()
        with patch.object(gui.QMessageBox, 'warning'), patch.object(gui.threading, 'Thread') as thread:
            self.w._start('同步場外止盈止損', MagicMock())
            thread.assert_not_called()
        self.assertEqual(self.w.reader.writes, before)

    def test_editing_balance_does_not_clear_warning_but_verified_update_does(self):
        self.load()
        self.w._parameter_write_last_signature = self.w._parameter_write_signature({'internal_balance': '10000'})
        self.change_stage()
        self.w.parameter_inputs['internal_balance'].setText('10000')
        self.assertTrue(self.w.balance_warning_badge.isVisible())
        with patch.object(self.w, '_start') as start:
            self.w.update_all_trade_parameters()
            start.call_args.args[1]()
            self.qtapp.processEvents()
        self.assertFalse(self.w.balance_warning_badge.isVisible())
        self.assertIsNotNone(self.w.instruction)
        self.assertEqual(self.w.stage_selector.currentText(), '真金階段')
        self.assertEqual(self.w.data_labels['internal_tp'].text(), '200')
        self.assertEqual(self.w.reader.writes, [{'A4': '真金階段'}, {'C6': '10000'}])

    def test_initial_read_loads_stage_even_when_trade_values_are_invalid(self):
        self.load()
        self.w.reader.values['A4'] = '真金階段'
        self.w._show_trade_sheet_settings((self.w._trade_settings_context(), None, ''))
        with self.assertRaises(ValidationError):
            self.w._read_sheet_task(include_trade_settings=True)
        self.qtapp.processEvents()
        self.assertEqual(self.w.stage_selector.currentText(), '真金階段')
        self.assertTrue(self.w.balance_warning_badge.isVisible())
        self.assertEqual(self.w.reader.writes, [])

    def test_failed_stage_readback_does_not_claim_success_or_show_balance_warning(self):
        self.load()
        self.w.reader.bad_readback = True
        self.change_stage()
        self.assertEqual(self.w.stage_selector.currentText(), '')
        self.assertFalse(self.w.balance_warning_badge.isVisible())

    def test_switching_back_to_valid_stage_clears_warning_without_rewriting_balance(self):
        self.load()
        self.change_stage()
        with patch.object(self.w, '_start') as start:
            self.w.stage_selector.setCurrentIndex(0)
            start.call_args.args[1]()
            self.qtapp.processEvents()
        self.assertEqual(self.w.stage_selector.currentText(), '階段甲')
        self.assertFalse(self.w.balance_warning_badge.isVisible())
        self.assertEqual(self.w.reader.writes, [{'A4': '真金階段'}, {'A4': '階段甲'}])

    def test_one_original_error_popup_includes_balance_guidance(self):
        self.load()

        def immediate_thread(*, target, **kwargs):
            thread = MagicMock()
            thread.start.side_effect = target
            return thread

        with patch.object(gui.threading, 'Thread', side_effect=immediate_thread), \
             patch.object(gui.time, 'sleep'), patch.object(gui.QMessageBox, 'warning') as notice:
            self.w.stage_selector.setCurrentIndex(1)
            self.qtapp.processEvents()
        notice.assert_called_once()
        self.assertIn('場內止盈點數必須大於零', notice.call_args.args[2])
        self.assertIn('修改場內餘額', notice.call_args.args[2])
        self.assertNotIn('更新未確認', notice.call_args.args[2])
        self.assertEqual(self.w.stage_selector.currentText(), '真金階段')

    def test_connection_error_after_verified_stage_keeps_stage_without_balance_warning(self):
        self.load()
        self.w.reader.read = MagicMock(side_effect=ValidationError('連線中斷'))
        self.change_stage()
        self.assertEqual(self.w.stage_selector.currentText(), '真金階段')
        self.assertFalse(self.w.balance_warning_badge.isVisible())
        self.assertIsNone(self.w.instruction)

    def test_balance_warning_does_not_leak_between_profiles_or_late_signals(self):
        self.load()
        old_context = self.w._trade_settings_context()
        self.change_stage()
        self.w.profiles.create('另一方案', self.w.store.data)
        self.w.store.data = self.w.profiles.load_profile()
        self.w._apply_profile_ui()
        self.w._set_balance_warning(old_context)
        self.assertFalse(self.w.balance_warning_badge.isVisible())
        self.assertFalse(self.w._balance_warning_active())
        before = self.w.parameter_inputs['daily_pnl'].placeholderText()
        self.w._show_trade_values_preview((old_context, {'daily_pnl': '999999'}))
        self.assertEqual(self.w.parameter_inputs['daily_pnl'].placeholderText(), before)
        self.w._set_balance_warning(self.w._trade_settings_context())
        self.w._clear_balance_warning(old_context)
        self.assertTrue(self.w._balance_warning_active())

    def test_only_nonpositive_internal_take_profit_uses_balance_guidance(self):
        for raw in ('0', '-1.25'):
            values = valid_values()
            values['internal_tp_points'] = raw
            with self.subTest(raw=raw), self.assertRaises(InvalidInternalTakeProfit):
                TradeInstruction.from_mapping(4, values)
        for field, raw in (('internal_tp_points', ''), ('external_tp_points', '0')):
            values = valid_values()
            values[field] = raw
            with self.subTest(field=field), self.assertRaises(ValidationError) as error:
                TradeInstruction.from_mapping(4, values)
            self.assertNotIsInstance(error.exception, InvalidInternalTakeProfit)

    def test_balance_badge_click_shows_guidance_without_starting_work(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.load()
        self.change_stage()
        with patch.object(gui.QMessageBox, 'warning') as notice, patch.object(self.w, '_start') as start:
            QTest.mouseClick(self.w.balance_warning_badge, Qt.LeftButton)
            notice.assert_called_once()
            self.assertIn('修改場內餘額', notice.call_args.args[2])
            start.assert_not_called()
        self.assertIn('修改場內餘額', self.w.balance_warning_badge.toolTip())

    def test_invalid_trade_values_still_show_fresh_sheet_numbers_and_placeholders(self):
        self.load()
        self.assertEqual(self.w.parameter_inputs['daily_pnl'].placeholderText(), '50')
        self.change_stage()
        for field, expected in (('internal_balance', '50000'), ('daily_pnl', '-123.45'),
                                ('expected_sl_combined', '-8.92'), ('internal_entry_price', '2345.67')):
            self.assertEqual(self.w.parameter_inputs[field].placeholderText(), expected)
        self.assertEqual(self.w.data_labels['symbol'].text(), 'EURUSD')
        self.assertEqual(self.w.data_labels['internal_lot'].text(), '1.2')
        self.assertEqual(self.w.data_labels['external_tp'].text(), '240')
        self.assertEqual(self.w.data_labels['original_sl_points'].text(), '-8.35')
        self.assertIsNone(self.w.instruction)
        with self.assertRaisesRegex(gui.AutomationError, '修改場內餘額'):
            self.w._require_instruction()

    def test_invalid_values_notice_is_an_adjustment_warning_not_a_read_failure(self):
        self.load()
        def immediate_thread(*, target, **kwargs):
            thread = MagicMock()
            thread.start.side_effect = target
            return thread
        with patch.object(gui.threading, 'Thread', side_effect=immediate_thread), \
             patch.object(gui.time, 'sleep'), patch.object(gui.QMessageBox, 'warning') as notice, \
             patch.object(gui.QMessageBox, 'critical') as error:
            self.w.stage_selector.setCurrentIndex(1)
        notice.assert_called_once()
        self.assertEqual(notice.call_args.args[1], '請調整交易數值')
        error.assert_not_called()

    def test_progress_reads_fresh_cash_values_without_an_executable_instruction(self):
        self.load()
        with patch.object(gui, 'calculate_ruler_from_sheet', return_value=(None, '')) as calculate:
            self.change_stage()
        self.assertEqual(str(calculate.call_args.kwargs['balance']), '50000')
        self.assertEqual(str(calculate.call_args.kwargs['daily_pnl']), '-123.45')
        self.assertIsNone(self.w.instruction)

    def test_relative_cash_edits_use_fresh_display_values_while_entry_is_blocked(self):
        self.load()
        self.change_stage()
        self.assertEqual(str(self.w._resolve_daily_pnl_input('=+10')), '-113.45')
        balance, pnl = self.w._resolve_internal_balance_delta_input('~50100')
        self.assertEqual(str(balance), '50100')
        self.assertEqual(str(pnl), '-23.45')
        self.assertIsNone(self.w.instruction)
        self.assertEqual(self.w.reader.writes, [{'A4': '真金階段'}])

    def test_stage_auto_focus_transfer_does_not_trigger_reload_help(self):
        from PySide6.QtCore import Qt
        self.load()
        self.w.stage_selector.setFocus(Qt.OtherFocusReason)
        self.qtapp.processEvents()
        with patch.object(self.w, '_start'):
            self.w.stage_selector.setCurrentIndex(1)
            self.qtapp.processEvents()
        self.assertIsNot(self.qtapp.focusWidget(), self.w.stage_selector)
        self.assertFalse(self.w._hover_help._timer.isActive())
        self.assertIsNone(self.w._hover_help._active)

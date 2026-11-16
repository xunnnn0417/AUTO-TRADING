"""Confirmed parameter edits survive formula warnings; unverified edits stay drafts."""
import unittest
from unittest.mock import patch, MagicMock
from trading_helper import gui
from trading_helper.models import TradeInstruction, ValidationError
from trading_helper.sheets import SheetReader
from test_models import valid_values
from test_progress_ruler import sheet_values
import test_compact_followup_controls as fixture


class ParameterReader:
    def __init__(self):
        self.values = valid_values()
        self.values.update(internal_balance='50000', daily_pnl='0', expected_sl_points='-10',
                           original_sl_points='-8', internal_entry_price='4000')
        self.warn = False
        self.bad_readback = False
        self.write_a1_values = MagicMock()

    def read(self, config):
        return SheetReader._instruction_from_values(4, self.values)

    def read_a1_values(self, config, cells):
        return {cell: ('請調整交易數值' if self.warn and cell == 'A20' else
                      sheet_values().get(config.get('worksheet'), {}).get(cell, '')) for cell in cells}

    def read_field_values(self, config, fields, **kwargs):
        return {field: ('未確認' if self.bad_readback else self.values[field]) for field in fields}

    def write_field_values(self, config, values, **kwargs):
        self.values.update(values)
        return {field: field for field in values}


class ParameterRetentionTests(unittest.TestCase):
    setUp = fixture.CompactFollowUpControlsTests.setUp
    tearDown = fixture.CompactFollowUpControlsTests.tearDown
    setUpClass = classmethod(fixture.CompactFollowUpControlsTests.setUpClass.__func__)

    def load(self):
        self.w.reader = ParameterReader()
        self.w._read_sheet_task()
        self.qtapp.processEvents()

    def update(self):
        with patch.object(self.w, '_start') as start:
            self.w.update_all_trade_parameters()
            start.call_args.args[1]()
        self.qtapp.processEvents()

    def test_all_four_parameters_keep_confirmed_warning_values_as_placeholders(self):
        self.load()
        self.w.reader.warn = True
        for field, new, source in (
            ('internal_balance', '55000', 'internal_balance'), ('daily_pnl', '-123', 'daily_pnl'),
            ('expected_sl_combined', '-11', 'expected_sl_points'), ('internal_entry_price', '4010', 'internal_entry_price')):
            with self.subTest(field=field), patch.object(gui.QMessageBox, 'warning'):
                self.w.parameter_inputs[field].setText(new)
                self.update()
                self.assertEqual(self.w.reader.values[source], new)
                self.assertEqual(self.w.parameter_inputs[field].text(), '')
                self.assertEqual(self.w.parameter_inputs[field].placeholderText(), new)
                self.assertTrue(self.w._balance_warning_active())
                with self.assertRaises(gui.AutomationError):
                    self.w._require_instruction()
                self.w.reader.write_a1_values.assert_not_called()

    def test_unconfirmed_write_keeps_draft_and_blocks_operations(self):
        self.load()
        self.w.parameter_inputs['internal_balance'].setText('54000')
        self.w.reader.bad_readback = True
        with self.assertRaises(ValidationError):
            self.update()
        self.qtapp.processEvents()
        self.assertEqual(self.w.parameter_inputs['internal_balance'].text(), '54000')
        self.assertEqual(self.w.parameter_inputs['internal_balance'].placeholderText(), '50000')
        self.assertTrue(self.w._balance_warning_active())
        self.w.reader.write_a1_values.assert_not_called()

    def test_invalid_calculation_keeps_new_cash_value_but_never_creates_instruction(self):
        self.load()
        self.w.reader.values['external_tp_points'] = '0'
        self.w.parameter_inputs['internal_balance'].setText('54000')
        with self.assertRaises(ValidationError):
            self.update()
        self.qtapp.processEvents()
        self.assertEqual(self.w.parameter_inputs['internal_balance'].text(), '')
        self.assertEqual(self.w.parameter_inputs['internal_balance'].placeholderText(), '54000')
        self.assertIsNone(self.w.instruction)
        self.assertTrue(self.w._balance_warning_active())
        self.w.reader.write_a1_values.assert_not_called()

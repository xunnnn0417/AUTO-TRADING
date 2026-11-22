"""Offline bulk-close calibration; no platform clicks or live positions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QMainWindow
from trading_helper.bulk_close_calibration import targets, role_for, match_controls, open_mt5_context
from trading_helper.calibration_scan import Control
from trading_helper.gui import CalibrationDialog
from trading_helper.windows import AutomationError


class BulkCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_optional_final_stage_has_two_fields_for_each_role(self):
        for platform in ('cTrader', 'MT5'):
            parent = QMainWindow()
            dialog = CalibrationDialog(parent, platform)
            self.assertEqual(set(dialog._stage_keys[-1]), {key for key, _ in targets(platform)})
            self.assertEqual(len(dialog._stage_keys[-1]), 4)
            self.assertEqual(dialog._display_role(targets(platform)[-1][0]), 'external')
            self.assertTrue(all(key in dialog._field_capture_buttons for key, _ in targets(platform)))
            self.assertFalse(any(c.isChecked() for c in dialog.bulk_scope_checkboxes.values()))
            dialog.close()
            parent.close()

    def test_all_positions_scope_requires_confirmation_and_preserves_other_role(self):
        import trading_helper.gui as gui
        parent = QMainWindow()
        parent.store = SimpleNamespace(data={'ui': {}, 'platforms': {'cTrader': {'points': {}}}})
        parent.save_config = Mock()
        dialog = CalibrationDialog(parent, 'cTrader')
        parent.save_config.assert_not_called()
        with patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.No):
            dialog.bulk_scope_checkboxes['external'].setChecked(True)
        self.assertFalse(dialog.bulk_scope_checkboxes['external'].isChecked())
        parent.save_config.assert_not_called()
        with patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.Yes):
            dialog.bulk_scope_checkboxes['external'].setChecked(True)
        self.assertEqual(parent.store.data['ui']['rest_close_all'], {'external': True})
        self.assertFalse(dialog.bulk_scope_checkboxes['internal'].isChecked())
        dialog.bulk_scope_checkboxes['external'].setChecked(False)
        self.assertEqual(parent.store.data['ui']['rest_close_all'], {'external': False})
        dialog.close()
        parent.close()

    def test_confirm_only_matches_close_positions_dialog_not_new_order_yes(self):
        requested = [row for row in targets('cTrader') if row[0].startswith('internal')]
        yes = Control('Button', 'Yes', '', (10, 10, 50, 40), ancestors=('New order - cTrader',))
        report = match_controls('cTrader', requested, [yes])
        self.assertNotIn('internal_bulk_close_confirm', report.candidates)
        yes = Control('Button', 'Yes', '', yes.rect, ancestors=('Close selected positions - cTrader',))
        self.assertIn('internal_bulk_close_confirm', match_controls('cTrader', requested, [yes]).candidates)

    def test_mt5_menu_can_open_left_and_does_not_match_delete_orders(self):
        requested = [row for row in targets('MT5') if row[0].startswith('external')]
        controls = [Control('MenuItem', '批量操作', '', (800, 100, 950, 130)),
                    Control('MenuItem', '所有持倉平倉', '', (600, 100, 790, 130)),
                    Control('MenuItem', '刪除所有訂單', '', (600, 200, 790, 230))]
        report = match_controls('MT5', requested, controls)
        self.assertEqual(report.candidates['external_bulk_close_all'].rect, (600, 100, 790, 130))
        controls[1] = Control('MenuItem', '所有持倉平倉', '', (600, 100, 790, 130), enabled=False)
        self.assertNotIn('external_bulk_close_all', match_controls('MT5', requested, controls).candidates)

    def test_ambiguous_controls_are_not_selected(self):
        requested = targets('cTrader')[:2]
        controls = [Control('Button', 'Close 2', '', (10, 10, 100, 35)),
                    Control('Button', 'Close 3', '', (10, 50, 100, 75))]
        self.assertFalse(match_controls('cTrader', requested, controls).candidates)

    def test_preparation_only_opens_context_menu_at_saved_sl(self):
        windows = Mock()
        point = dict(x=0.5, y=0.5)
        open_mt5_context(windows, 'bound-main', point)
        windows.right_click.assert_called_once_with('bound-main', point)
        windows.click.assert_not_called()
        with self.assertRaises(AutomationError):
            open_mt5_context(windows, 'bound-main', None)
        self.assertEqual(role_for('external_bulk_close_all'), 'external')

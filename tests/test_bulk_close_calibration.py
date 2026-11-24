"""Offline bulk-close calibration; no platform clicks or live positions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QCheckBox, QMainWindow
from trading_helper.bulk_close_calibration import targets, is_bulk_key, match_controls, open_mt5_context
from trading_helper.calibration_scan import Control
from trading_helper.gui import CalibrationDialog
from trading_helper.windows import AutomationError


class BulkCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_optional_final_stage_has_one_pair_of_fields_per_platform(self):
        # The close-all UI is the platform's own; 場內/場外 is not duplicated.
        for platform in ('cTrader', 'MT5'):
            parent = QMainWindow()
            dialog = CalibrationDialog(parent, platform)
            self.assertEqual(set(dialog._stage_keys[-1]), {key for key, _ in targets(platform)})
            self.assertEqual(len(dialog._stage_keys[-1]), 2)
            self.assertFalse(any('場內' in label or '場外' in label for _, label in targets(platform)))
            self.assertTrue(all(key in dialog._field_capture_buttons for key, _ in targets(platform)))
            # Close-all scope moved to the main screen's gear settings.
            self.assertIsNone(dialog.findChild(QCheckBox, 'bulkCloseAll_external'))
            dialog.close()
            parent.close()

    def test_all_positions_scope_requires_confirmation_and_preserves_other_role(self):
        import trading_helper.gui as gui
        parent = QMainWindow()
        parent.store = SimpleNamespace(data={'ui': {}, 'platforms': {'cTrader': {'points': {}}}})
        parent.save_config = Mock()
        dialog = gui.RestCloseSettingsDialog(parent)
        boxes = dialog.scope_checkboxes
        self.assertFalse(any(c.isChecked() for c in boxes.values()))
        with patch.object(dialog, '_confirm_all_positions', return_value=False):
            boxes['external'].setChecked(True)
        self.assertFalse(boxes['external'].isChecked())
        parent.save_config.assert_not_called()
        with patch.object(dialog, '_confirm_all_positions', return_value=True):
            boxes['external'].setChecked(True)
        self.assertEqual(parent.store.data['ui']['rest_close_all'], {'external': True})
        self.assertFalse(boxes['internal'].isChecked())
        boxes['external'].setChecked(False)
        self.assertEqual(parent.store.data['ui']['rest_close_all'], {'external': False})
        dialog.close()
        parent.close()

    def test_confirm_only_matches_close_positions_dialog_not_new_order_yes(self):
        requested = list(targets('cTrader'))
        yes = Control('Button', 'Yes', '', (10, 10, 50, 40), ancestors=('New order - cTrader',))
        report = match_controls('cTrader', requested, [yes])
        self.assertNotIn('bulk_close_confirm', report.candidates)
        yes = Control('Button', 'Yes', '', yes.rect, ancestors=('Close selected positions - cTrader',))
        self.assertIn('bulk_close_confirm', match_controls('cTrader', requested, [yes]).candidates)

    def test_mt5_menu_can_open_left_and_does_not_match_delete_orders(self):
        requested = list(targets('MT5'))
        controls = [Control('MenuItem', '批量操作', '', (800, 100, 950, 130)),
                    Control('MenuItem', '所有持倉平倉', '', (600, 100, 790, 130)),
                    Control('MenuItem', '刪除所有訂單', '', (600, 200, 790, 230))]
        report = match_controls('MT5', requested, controls)
        self.assertEqual(report.candidates['bulk_close_all'].rect, (600, 100, 790, 130))
        controls[1] = Control('MenuItem', '所有持倉平倉', '', (600, 100, 790, 130), enabled=False)
        # MT5 greys the item out while there are no positions; its place is the same.
        self.assertIn('bulk_close_all', match_controls('MT5', requested, controls).candidates)

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
        self.assertTrue(is_bulk_key('bulk_close_all'))
        self.assertFalse(is_bulk_key('position_close_button'))


class CTraderCloseAllButtonTests(unittest.TestCase):
    # Real cTrader 5.10.22 UIA shape (read-only inspection, no positions open).
    BUTTON_ID = 'TradeWatch_CloseAll_CloseAllButton__Button_ButtonContent_AId'
    TEXT_ID = 'TradeWatch_CloseAll_CloseAllButton__TextBlock_PrimaryOneTextIcons_AId'

    def test_matches_by_automation_id_whatever_the_caption(self):
        requested = [row for row in targets('cTrader') if row[0] == 'bulk_close_button']
        for caption in ('Nothing to close', 'Close 3', '全部平倉', 'Something new'):
            with self.subTest(caption=caption):
                controls = [Control('Button', caption, self.BUTTON_ID, (1280, 530, 1400, 556)),
                            Control('Text', caption, self.TEXT_ID, (1290, 535, 1395, 551))]
                report = match_controls('cTrader', requested, controls)
                self.assertEqual(report.candidates['bulk_close_button'].rect, (1280, 530, 1400, 556))

    def test_manual_capture_on_the_caption_text_still_counts(self):
        requested = [row for row in targets('cTrader') if row[0] == 'bulk_close_button']
        text_only = [Control('Text', 'Nothing to close', self.TEXT_ID, (1290, 535, 1395, 551))]
        self.assertIn('bulk_close_button', match_controls('cTrader', requested, text_only).candidates)

    def test_other_buttons_are_not_mistaken_for_close_all(self):
        requested = [row for row in targets('cTrader') if row[0] == 'bulk_close_button']
        others = [Control('Button', 'New order', 'TradeWatch_NewOrder_Button', (1170, 530, 1270, 556)),
                  Control('Button', 'Place order', 'Orders_Create_Place_AId', (1470, 576, 1866, 600))]
        self.assertFalse(match_controls('cTrader', requested, others).candidates)

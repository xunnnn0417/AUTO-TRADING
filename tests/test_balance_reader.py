"""場內實際餘額: parsing, cTrader OCR guard rails, MT5 read-only account check."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from trading_helper import balance_reader as br
from trading_helper.windows import AutomationError, WindowInfo


class ParseTests(unittest.TestCase):
    def test_common_formats_and_ocr_misreads(self):
        for text, value in (("$ 5 002 318.58", "5002318.58"), ("5,002,318.58", "5002318.58"),
                            ("C5.002318.58", "5002318.58"), ("$0.00", "0.00"), ("12345", "12345")):
            self.assertEqual(br.parse_balance_text(text), Decimal(value), text)
        self.assertIsNone(br.parse_balance_text("N/A"))


def box(cx, cy, w=60, h=12):
    return [[cx - w, cy - h], [cx + w, cy - h], [cx + w, cy + h], [cx - w, cy + h]]


class CTraderTests(unittest.TestCase):
    window = WindowInfo(1, "cTrader", 0, 0, 800, 600)

    def test_header_value_is_used_without_any_screen_reading(self):
        with patch("trading_helper.windows._native_names_by_automation_id",
                   return_value=["$ 5 002 318.58 • 1:1000"]):
            value = br.read_ctrader_balance(self.window, capture=lambda h: self.fail("no capture"))
        self.assertEqual(value, Decimal("5002318.58"))

    def read_bottom(self, results):
        calls = iter(results)
        return br.read_ctrader_balance(self.window, header=lambda h: None,
                                       capture=lambda h: np.zeros((600, 800, 3), np.uint8),
                                       ocr=lambda image: next(calls))

    def test_bottom_balance_cell_found_without_calibration(self):
        strip = [(box(150, 20), "Balance", 1.0), (box(340, 20), "Equity", 1.0),
                 (box(160, 60), "$ 5 002 318.58", 0.93), (box(350, 60), "$ 5 002 400.00", 0.93)]
        self.assertEqual(self.read_bottom([strip, strip]), Decimal("5002318.58"))

    def test_refuses_when_unreadable_or_readings_disagree(self):
        other = [(box(150, 20), "Balance", 1.0), (box(160, 60), "5002313.58", 0.9)]
        strip = [(box(150, 20), "Balance", 1.0), (box(160, 60), "5002318.58", 0.9)]
        with self.assertRaises(AutomationError):
            self.read_bottom([strip, other])
        with self.assertRaises(AutomationError):
            self.read_bottom([[], []])


class Mt5Tests(unittest.TestCase):
    expected = SimpleNamespace(verified=True, account_id="123456", server="Demo-Server")

    def sdk(self, login="123456", server="Demo-Server"):
        return SimpleNamespace(initialize=lambda **k: True, shutdown=lambda: None,
                               account_info=lambda: SimpleNamespace(login=login, server=server, balance=10123.45))

    def test_reads_balance_of_the_bound_account(self):
        with patch.object(Path, "is_file", return_value=True):
            value = br.read_mt5_balance(self.expected, terminal_path=Path("terminal64.exe"), sdk=self.sdk())
        self.assertEqual(value, Decimal("10123.45"))

    def test_refuses_another_account(self):
        with patch.object(Path, "is_file", return_value=True), self.assertRaises(AutomationError):
            br.read_mt5_balance(self.expected, terminal_path=Path("terminal64.exe"), sdk=self.sdk(login="999999"))


if __name__ == "__main__":
    unittest.main()


import test_compact_followup_controls as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from trading_helper import gui  # noqa: E402


class ApplyBalanceTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def click(self, label):
        def exec_(box):
            box._clicked_button = next((b for b in box._buttons if b.text() == label), None)
            return 0
        return patch.object(gui.ThemedMessageBox, "exec", exec_)

    def test_button_exists_and_fills_only_after_confirm(self):
        self.assertEqual(self.w.read_balance_button.objectName(), "readInternalBalance")
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("")
        with self.click("取消"):
            self.w._apply_internal_balance_read({"platform": "cTrader", "value": "5002318.58"})
        self.assertEqual(field.text(), "")
        with self.click("填入"):
            self.w._apply_internal_balance_read({"platform": "cTrader", "value": "5002318.58"})
        self.assertEqual(field.text(), "5002318.58")

    def test_error_is_shown_and_nothing_filled(self):
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("100")
        with patch.object(gui.ThemedMessageBox, "warning") as warning:
            self.w._apply_internal_balance_read({"platform": "MT5", "error": "讀不到"})
        warning.assert_called_once()
        self.assertEqual(field.text(), "100")


class BalanceFieldButtonsTests(ApplyBalanceTests):
    def test_prefix_buttons_always_put_tilde_then_minus_in_front(self):
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("100")
        self.w.balance_prefix_buttons["-"].click()
        self.w.balance_prefix_buttons["~"].click()
        self.assertEqual(field.text(), "~-100")
        self.assertTrue(self.w.balance_prefix_buttons["~"].isChecked())
        self.w.balance_prefix_buttons["-"].click()
        self.assertEqual(field.text(), "~100")
        self.assertFalse(self.w.balance_prefix_buttons["-"].isChecked())

    def test_read_keeps_chosen_prefix_and_session_skip_stops_asking(self):
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("")
        self.w.balance_prefix_buttons["~"].click()

        def exec_(box):
            box.findChild(gui.QCheckBox, "balanceAutofillSession").setChecked(True)
            box._clicked_button = next(b for b in box._buttons if b.text() == "填入")
            return 0
        with patch.object(gui.ThemedMessageBox, "exec", exec_):
            self.w._apply_internal_balance_read({"platform": "cTrader", "value": "5002318.58"})
        self.assertEqual(field.text(), "~5002318.58")
        with patch.object(gui.ThemedMessageBox, "exec", side_effect=AssertionError("asked again")):
            self.w._apply_internal_balance_read({"platform": "cTrader", "value": "10.00"})
        self.assertEqual(field.text(), "~10.00")
        self.assertEqual(self.w.read_balance_button.text(), "")  # icon only


class ReadButtonFeedbackTests(ApplyBalanceTests):
    def test_spins_while_reading_then_shows_result_and_returns(self):
        button = self.w.read_balance_button
        self.w._set_balance_button_state("loading")
        self.assertFalse(button.isEnabled())
        self.assertTrue(self.w._balance_spin_timer.isActive())
        self.w._spin_balance_button()
        self.assertFalse(button.icon().isNull())
        self.w._set_balance_button_state("done")
        self.assertTrue(button.isEnabled())
        self.assertFalse(self.w._balance_spin_timer.isActive())
        self.w._set_balance_button_state("idle")
        self.assertTrue(button.isEnabled())


class BalanceFieldLayoutTests(ApplyBalanceTests):
    def test_prefix_buttons_sit_left_of_box_and_box_lines_up_with_field_below(self):
        self.w.resize(1400, 850)
        self.w.show()
        self.qtapp.processEvents()
        balance = self.w.parameter_inputs["internal_balance"]
        below = self.w.parameter_inputs["expected_sl_combined"]
        root = self.w
        self.assertEqual(balance.mapTo(root, balance.rect().topLeft()).x(),
                         below.mapTo(root, below.rect().topLeft()).x())
        tilde = self.w.balance_prefix_buttons["~"]
        self.assertIsNot(tilde.parentWidget(), balance)  # outside the text box
        self.assertLess(tilde.mapTo(root, tilde.rect().topRight()).x(),
                        balance.mapTo(root, balance.rect().topLeft()).x())
        self.assertEqual(self.w.read_balance_button.parentWidget(), balance)  # read icon inside
        gap = balance.mapTo(root, balance.rect().topLeft()).x() - (tilde.mapTo(root, tilde.rect().topRight()).x() + 1)
        self.assertLessEqual(gap, 1)                     # keys touch the box
        self.assertEqual(tilde.width(), tilde.height())  # square keys
        reader = self.w.read_balance_button
        self.assertEqual(reader.geometry().right(), balance.width() - 2)  # flush with the right border


class SideAndPhoneBalanceTests(ApplyBalanceTests):
    def open_panel(self):
        with patch("trading_helper.calendar_events.EconomicCalendar.refresh"):
            self.w.toggle_side_panel(True)
        self.qtapp.processEvents()
        return self.w.side_panel

    def test_side_panel_keys_edit_the_shared_field_and_read_marks_origin(self):
        panel = self.open_panel()
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("200")
        panel.balance_prefix_buttons["~"].click()
        self.assertEqual(field.text(), "~200")
        panel.sync_from_main()
        self.assertTrue(panel.balance_prefix_buttons["~"].isChecked())
        self.assertIs(panel.read_balance_button.parentWidget(), panel.inputs["internal_balance"])
        with patch.object(self.w, "read_internal_balance") as read:
            panel.read_balance_button.click()
        read.assert_called_once_with("side")

    def test_phone_read_fills_directly_without_question(self):
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("-")
        self.w._balance_read_origin = "phone"
        with patch.object(gui.ThemedMessageBox, "exec", side_effect=AssertionError("asked")):
            self.w._apply_internal_balance_read({"platform": "MT5", "value": "123.4"})
        self.assertEqual(field.text(), "-123.40")

    def test_phone_page_has_prefix_keys_and_read_action(self):
        from trading_helper import remote_mobile, remote_ui
        page = "".join(v for v in vars(remote_mobile).values() if isinstance(v, str))
        self.assertIn('data-prefix="~"', page)
        self.assertIn('data-action="read_balance"', page)
        self.assertIn("read_balance", remote_ui.ACTIONS)


class CalmSpinnerAndComboTests(ApplyBalanceTests):
    def test_spinner_turns_in_small_even_steps(self):
        self.w._set_balance_button_state("loading")
        self.assertEqual(self.w._balance_spin_timer.interval(), 40)
        self.w._spin_balance_button()
        self.assertEqual(len(self.w._balance_spin_frames), 36)  # 10 degrees per frame
        self.w._set_balance_button_state("idle")

    def test_combo_is_not_highlighted_just_because_it_has_focus(self):
        from PySide6.QtGui import QCursor
        from trading_helper.compact_controls import HoverStageCombo
        combo = HoverStageCombo()
        combo.addItems(["方案1", "方案2"])
        combo.show()
        self.addCleanup(combo.close)
        combo.setFocus()
        with patch.object(QCursor, "pos", return_value=combo.mapToGlobal(combo.rect().bottomRight()) + gui.QPoint(50, 50)):
            image = combo.grab().toImage()
        self.assertNotEqual(image.pixelColor(2, combo.height() // 2).name(), "#262030")

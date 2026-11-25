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

    def test_button_exists_and_fills_straight_away_without_a_question(self):
        self.assertEqual(self.w.read_balance_button.objectName(), "readInternalBalance")
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("")
        with patch.object(gui.ThemedMessageBox, "exec", side_effect=AssertionError("asked")):
            self.w._apply_internal_balance_read({"platform": "cTrader", "value": "5002318.58"})
        self.assertEqual(field.text(), "5002318.58")

    def test_error_is_shown_and_nothing_filled(self):
        field = self.w.parameter_inputs["internal_balance"]
        field.setText("100")
        with patch.object(gui.ThemedMessageBox, "warning") as warning:
            self.w._apply_internal_balance_read({"platform": "MT5", "error": "讀不到"})
        warning.assert_called_once()
        self.assertEqual(field.text(), "100")


class AfterCloseTests(ApplyBalanceTests):
    def test_tp_sl_hit_reads_with_tilde_updates_then_tells_the_phone(self):
        field = self.w.parameter_inputs["internal_balance"]
        self.w.internal_platform.setCurrentText("cTrader")
        with patch.object(self.w, "read_internal_balance") as read, \
             patch.object(self.w, "can_update", return_value=True):
            self.w._live_pnl_closed({"ticket": 1})
        read.assert_called_once_with("auto")
        self.assertEqual(field.text(), "~")
        updates = []
        field.returnPressed.connect(lambda: updates.append(1))
        self.w._balance_read_origin = "auto"  # what read_internal_balance("auto") records
        from test_progress_ruler import instruction
        self.w.instruction = instruction()  # a sheet already read, as after a trade
        with patch.object(gui.ThemedMessageBox, "exec", side_effect=AssertionError("asked")), \
             patch.object(self.w, "_start"):
            self.w._apply_internal_balance_read({"platform": "cTrader", "value": "51234.5"})
        self.assertEqual(field.text(), "~51234.50")  # 「~」: daily P/L follows
        self.assertEqual(updates, [1])                # 「更新」 pressed
        with patch.object(self.w, "_push_trade_message") as push:
            self.w._send_after_close_summary()
        title, body = push.call_args.args
        self.assertIn("餘額已更新", title)

    def test_other_scheme_open_means_no_automatic_update(self):
        with patch.object(self.w, "read_internal_balance") as read, \
             patch.object(self.w, "_push_trade_message") as push:
            self.w._live_pnl_closed({"ticket": 1, "profile": "另一個方案"})
        read.assert_not_called()
        self.assertIn("沒有自動更新", push.call_args.args[1])

    def test_test_profile_asks_before_the_automatic_read(self):
        self.w.internal_platform.setCurrentText("cTrader")
        with patch.object(type(self.w.profiles), "active_name",
                          new_callable=lambda: property(lambda _s: gui.TEST_PROFILE_NAME)), \
             patch.object(self.w, "can_update", return_value=True), \
             patch.object(self.w, "read_internal_balance") as read:
            with patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.No) as ask:
                self.w._after_close_update()
            ask.assert_called_once()
            read.assert_not_called()
            self.assertEqual(self.w.parameter_inputs["internal_balance"].text(), "")  # no ~, no number
            with patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.Yes):
                self.w._after_close_update()
            read.assert_called_once_with("auto")

    def test_other_scheme_open_switches_back_then_updates(self):
        active = {"name": "測試"}
        self.w.internal_platform.setCurrentText("cTrader")
        with patch.object(type(self.w.profiles), "active_name",
                          new_callable=lambda: property(lambda _s: active["name"])), \
             patch.object(self.w.profiles, "names", return_value=["測試", "開單方案"]), \
             patch.object(self.w, "switch_profile", side_effect=lambda n: active.update(name=n)) as switch, \
             patch.object(self.w, "can_update", return_value=True), \
             patch.object(gui.QTimer, "singleShot") as later, \
             patch.object(self.w, "read_internal_balance") as read:
            self.w._live_pnl_closed({"ticket": 1, "profile": "開單方案"})
            switch.assert_called_once_with("開單方案")
            read.assert_not_called()               # waits for the switched sheet first
            later.call_args.args[1]()              # sheet read finished
            read.assert_called_once_with("auto")
        self.assertIn("開單方案", self.w._after_close_switched)

    def test_failed_auto_read_notifies_without_a_popup(self):
        with patch.object(gui.ThemedMessageBox, "warning", side_effect=AssertionError("popup")), \
             patch.object(self.w, "_push_trade_message") as push:
            self.w._balance_read_origin = "auto"
            self.w._apply_internal_balance_read({"platform": "cTrader", "error": "讀不到"})
        self.assertIn("讀取餘額失敗", push.call_args.args[1])


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
        self.w._set_balance_button_state("ready")
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
        self.assertEqual(reader.geometry().right(), balance.width() - 3)  # at the right edge, inside the border
        self.assertGreaterEqual(reader.geometry().top(), 2)               # hover never covers the border


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
        self.assertEqual(self.w._balance_spin_timer.interval(), 20)
        self.w._spin_balance_button()
        self.assertEqual(len(self.w._balance_spin_frames), 72)  # 5 degrees per frame
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


class CheckThenUpdateTests(ApplyBalanceTests):
    def fill(self, value="777.00"):
        self.w._balance_autofill_session = True
        self.w._apply_internal_balance_read({"platform": "cTrader", "value": value})

    def test_fill_does_not_update_by_itself_and_check_stays(self):
        with patch.object(self.w, "update_all_trade_parameters") as update:
            self.fill()
        update.assert_not_called()
        self.assertEqual(self.w._balance_button_state, "ready")

    def test_prefix_keys_keep_the_check_but_editing_digits_drops_it(self):
        self.fill()
        self.w.balance_prefix_buttons["~"].click()
        self.assertEqual(self.w.parameter_inputs["internal_balance"].text(), "~777.00")
        self.assertEqual(self.w._balance_button_state, "ready")
        self.w.parameter_inputs["internal_balance"].setText("~778.00")
        self.assertEqual(self.w._balance_button_state, "idle")

    def test_pressing_the_check_runs_update_then_shows_read_icon(self):
        self.fill()
        emitted = []
        self.w.parameter_inputs["internal_balance"].returnPressed.connect(lambda: emitted.append(1))
        # The real 「更新」 worker is not part of this check (no sheet here).
        with patch.object(self.w, "read_internal_balance") as read, patch.object(self.w, "_start"):
            self.w.read_balance_button.click()
        read.assert_not_called()
        self.assertEqual(emitted, [1])
        self.assertEqual(self.w._balance_button_state, "idle")
        with patch.object(self.w, "read_internal_balance") as read:
            self.w.read_balance_button.click()
        read.assert_called_once_with("main")


class PhoneBalanceStateTests(unittest.TestCase):
    def test_phone_page_reenables_prefix_keys_and_swaps_read_for_check(self):
        from trading_helper import remote_mobile
        js = remote_mobile.ASSETS["/app.js"][1]
        js = js if isinstance(js, str) else js.decode()
        self.assertIn('b.disabled=balanceInput.disabled', js)
        self.assertIn('rb.dataset.action=ready?"update":"read_balance"', js)

    def test_phone_read_is_reported_as_completed_without_popup(self):
        import inspect
        from trading_helper import remote_ui
        source = inspect.getsource(remote_ui.RemoteController._finish)
        self.assertIn('"read_balance"', source)
        self.assertIn("balance_ready", inspect.getsource(remote_ui.RemoteController.snapshot))


class PhoneOptionsTests(unittest.TestCase):
    def test_phone_lists_rest_close_with_settings_and_groups_them(self):
        import inspect
        from trading_helper import remote_mobile, remote_ui
        source = inspect.getsource(remote_ui.RemoteController._options)
        self.assertNotIn('"auto_tv"', source)  # TradingView hidden for now
        self.assertIn('"rest_close"', source)
        js = remote_mobile.ASSETS["/app.js"][1]
        js = js if isinstance(js, str) else js.decode()
        self.assertIn('rest_close:"休市平倉"', js)
        self.assertIn("option-group", js)
        self.assertIn("openRestSettings", js)
        self.assertNotIn('data-action="fill_internal"', remote_mobile.ASSETS["/"][1] if isinstance(remote_mobile.ASSETS["/"][1], str) else remote_mobile.ASSETS["/"][1].decode())



class TradingViewHiddenAndPhoneRestTests(ApplyBalanceTests):
    def test_tradingview_controls_hidden_and_never_drawn(self):
        self.assertFalse(gui.TRADINGVIEW_ENABLED)
        self.assertTrue(self.w.auto_draw_tv_after_entry.isHidden())
        self.assertTrue(self.w.action_buttons["校準 TradingView"].isHidden())

    def test_phone_rest_settings_validate_and_save(self):
        from trading_helper.remote_ui import RemoteController
        good = {"reminder": {"enabled": True, "minutes": [60, 30]},
                "close": {"minutes": 45, "internal": True, "external": False}}
        reminder, close = RemoteController._clean_rest_settings(good)
        self.assertEqual(close["minutes"], 45)
        with self.assertRaises(ValueError):
            RemoteController._clean_rest_settings(dict(good, close={"minutes": 999, "internal": True, "external": False}))
        fake = type("C", (), {"app": self.w, "_clean_rest_settings": staticmethod(RemoteController._clean_rest_settings)})()
        with patch.object(self.w, "save_config"):
            RemoteController._apply_rest_settings(fake, good)
        ui = self.w.store.data["ui"]
        self.assertEqual(ui["rest_close_minutes"], 45)
        self.assertEqual(ui["rest_close_all"], {"internal": True, "external": False})
        self.assertTrue(ui["rest_reminder"]["enabled"])
        # 消息 page saves the reminder alone; the gear saves 休市平倉 alone.
        with patch.object(self.w, "save_config"):
            RemoteController._apply_rest_settings(fake, {"reminder": {"enabled": False, "minutes": [45, 15], "custom": True}})
        self.assertEqual(ui["rest_reminder"], {"enabled": False, "minutes": [45, 15], "custom": True})
        self.assertEqual(ui["rest_close_minutes"], 45)
        with self.assertRaises(ValueError):
            RemoteController._clean_rest_settings({})
        with self.assertRaises(ValueError):
            RemoteController._clean_rest_settings({"reminder": {"enabled": True, "minutes": [30], "x": 1}})

    def test_switching_scheme_shows_that_schemes_rest_close_setting(self):
        self.w.rest_close_checkbox.blockSignals(True)
        self.w.rest_close_checkbox.setChecked(True)
        self.w.rest_close_checkbox.blockSignals(False)
        self.w.store.data["ui"]["rest_close_enabled"] = False
        self.w._apply_profile_ui()
        self.assertFalse(self.w.rest_close_checkbox.isChecked())

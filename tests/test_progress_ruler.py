"""Offline regression tests for sheet-backed account-progress ruler."""
import os
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QGroupBox, QScrollArea
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest

from trading_helper.progress_ruler import (
    SHEET_RULER_REFERENCES, calculate_ruler_from_sheet, approximate_orders,
    display_groups,
)
from trading_helper.models import TradeInstruction, SideValues, ValidationError
from trading_helper import gui


def sheet_values():
    return {
        "運算區": {
            "B2": "50000", "F7": "46500.00", "F6": "2500.00",
            "B9": "55000.00", "C20": "484.00",
        },
        "主要計算區": {"E2": "-390.00", "F2": "484.00"},
    }


def instruction():
    return TradeInstruction(
        source_row=2, status="", symbol="GOLD", sheet_direction="BUY",
        internal=SideValues(D(".74"), D("-5.27"), D("6.54")),
        external=SideValues(D(".16"), D("-6.84"), D("4.97")),
        estimated_price=None, point_size=D(".01"), price_digits=2,
        internal_balance=D("54551"), daily_pnl=D("0"),
    )


class RulerMath(unittest.TestCase):
    def test_exact_sheet_cells_and_absolute_balance_thresholds(self):
        self.assertEqual(SHEET_RULER_REFERENCES["運算區"], ("B2","F7","F6","B9","C20"))
        self.assertEqual(SHEET_RULER_REFERENCES["主要計算區"], ("E2","F2"))
        state, error = calculate_ruler_from_sheet(
            sheet_values(), balance=D("54551"), daily_pnl=D("0"))
        self.assertEqual(error, "")
        marks = dict(state.markers)
        self.assertEqual(marks["帳號初始餘額"], D("50000"))
        self.assertEqual(marks["最大虧損"], D("46500"))
        self.assertEqual(marks["每日最大虧損"], D("52051"))
        self.assertEqual(marks["今天獲利目標"], D("55035"))
        self.assertEqual(marks["帳號獲利目標"], D("55000"))
        self.assertEqual(len(state.markers), 6)
        grouped = display_groups(state.markers)
        goal = next(nodes for point, nodes in grouped if point == D("55000"))
        self.assertEqual({name for name, _ in goal},
                         {"今天獲利目標", "帳號獲利目標"})
        self.assertEqual(state.tp_cash, D("484"))
        self.assertEqual(state.sl_cash, D("390"))
        self.assertEqual(state.win_crossing, 1)
        self.assertEqual(state.loss_crossing, 7)
        self.assertEqual(state.win_hint, "接近 1 單")
        self.assertEqual(state.loss_hint, "接近 6 單")

    def test_crossing_goals_merges_into_account_goal_and_counts_to_it(self):
        data = sheet_values()
        data["運算區"]["C20"] = "5000"
        state, error = calculate_ruler_from_sheet(
            data, balance=D("52000"), daily_pnl=D("0"))
        self.assertEqual(error, "")
        self.assertEqual(dict(state.markers)["今天獲利目標"], D("57000"))
        self.assertEqual(dict(state.markers)["帳號獲利目標"], D("55000"))
        grouped = display_groups(state.markers)
        goal = next(nodes for point, nodes in grouped if point == D("55000"))
        self.assertEqual(len(goal), 2)
        self.assertEqual(state.win_crossing, 7)
        self.assertEqual(state.win_hint, "接近 6 單")

    def test_crossing_losses_merges_into_max_loss_and_counts_to_it(self):
        data = sheet_values()
        data["運算區"]["F6"] = "4000"
        state, error = calculate_ruler_from_sheet(
            data, balance=D("49000"), daily_pnl=D("0"))
        self.assertEqual(error, "")
        self.assertEqual(dict(state.markers)["每日最大虧損"], D("45000"))
        self.assertEqual(dict(state.markers)["最大虧損"], D("46500"))
        grouped = display_groups(state.markers)
        loss = next(nodes for point, nodes in grouped if point == D("46500"))
        self.assertEqual(len(loss), 2)
        self.assertEqual(state.loss_crossing, 7)
        self.assertEqual(state.loss_hint, "接近 6 單")

    def test_equal_boundaries_appear_once(self):
        data = sheet_values()
        data["運算區"]["C20"] = "1000"
        data["運算區"]["F6"] = "1500"
        state, error = calculate_ruler_from_sheet(
            data, balance=D("48000"), daily_pnl=D("0"))
        self.assertEqual(error, "")
        # Same amount means one shared tick but both source labels remain.
        self.assertEqual(dict(state.markers)["每日最大虧損"], D("46500"))
        self.assertEqual(dict(state.markers)["最大虧損"], D("46500"))
        grouped = display_groups(state.markers)
        loss = next(nodes for point, nodes in grouped if point == D("46500"))
        self.assertEqual(len(loss), 2)
        self.assertIn("今天獲利目標", dict(state.markers))

    def test_reset_from_current_balance_minus_daily_pnl(self):
        state, _ = calculate_ruler_from_sheet(
            sheet_values(), balance=D("52000"), daily_pnl=D("500"))
        self.assertEqual(dict(state.markers)["每日最大虧損"], D("49000"))
        self.assertEqual(dict(state.markers)["今天獲利目標"], D("51984"))
        self.assertEqual(state.win_hint, "已達目標")

    def test_sheet_amount_not_lot_multiplier(self):
        state, _ = calculate_ruler_from_sheet(
            sheet_values(), balance=D("50000"), daily_pnl=D("0"))
        self.assertEqual(state.tp_cash, D("484"))
        self.assertEqual(state.sl_cash, D("390"))

    def test_display_thresholds_and_unambiguous_crossing(self):
        self.assertEqual(approximate_orders(D("130"),D("100"), win=True),"接近 1 單")
        self.assertEqual(approximate_orders(D("140"),D("100"), win=True),"接近 2 單")
        self.assertEqual(approximate_orders(D("40"),D("100"), win=False),"接近 0 單")
        self.assertEqual(approximate_orders(D("39"),D("100"), win=False),"不足 1 單")
        self.assertEqual(approximate_orders(D("0"),D("100"), win=False),"已觸及限制")

    def test_missing_values_never_use_fabricated_defaults(self):
        data = sheet_values()
        del data["運算區"]["B9"]
        state, error = calculate_ruler_from_sheet(
            data, balance=D("50000"), daily_pnl=D("0"))
        self.assertIsNone(state)
        self.assertIn("B9", error)

    def test_reject_mis_signed_pnl(self):
        data = sheet_values()
        data["主要計算區"]["E2"] = "390"
        state, error = calculate_ruler_from_sheet(
            data, balance=D("50000"), daily_pnl=D("0"))
        self.assertIsNone(state)
        self.assertIn("E2", error)


class RulerGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)
        real_config, real_profiles = gui.ConfigStore, gui.ProfileStore
        with patch.object(gui, "ConfigStore", side_effect=lambda:real_config(path=path/"cfg.json")),\
             patch.object(gui, "ProfileStore",side_effect=lambda x:real_profiles(x,path=path/"profiles.json")),\
             patch.object(gui.WindowController,"warm_ocr",return_value=None),\
             patch.object(gui.TradingHelperApp,"read_sheet",lambda _:None):
            self.win = gui.TradingHelperApp()
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_visible_read_only_and_sheet_backed(self):
        w = self.win
        self.assertTrue(w.account_ruler.isVisible())
        self.assertFalse(w.ruler_settings_button.isVisible())
        self.assertEqual(w.ruler_settings_button.text(), "來源")
        self.assertFalse(w.trade_page.findChildren(QScrollArea))
        self.assertIsNone(w.account_ruler.state)
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        self.assertIsNone(w.account_ruler.state)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name, w.store.data["sheet"]["spreadsheet_url"]))
        self.app.processEvents()
        self.assertIsNotNone(w.account_ruler.state)
        self.assertIn("接近 1 單", w.ruler_win_label.text())
        self.assertIn("接近 6 單", w.ruler_loss_label.text())

    def test_source_dialog_explains_mapping_without_writes(self):
        w = self.win
        with patch.object(gui.QMessageBox, "information") as info,\
             patch.object(w, "save_config") as save:
            w._edit_ruler_settings()
        info.assert_called_once()
        self.assertIn("B9", info.call_args.args[2])
        save.assert_not_called()

    def test_reader_fetches_both_tabs_and_preserves_primary_data(self):
        w = self.win
        w.store.data["sheet"]["worksheet"] = "主要計算區"
        w.store.data["sheet"]["spreadsheet_url"] = "https://docs.google.com/spreadsheets/d/mock"
        w.reader.read = lambda config: instruction()
        observed = []
        def stub(config, refs):
            observed.append((config["worksheet"], tuple(refs)))
            if refs == ["A12"]:
                return {"A12": ""}
            return {key:sheet_values()[config["worksheet"]][key] for key in refs}
        w.reader.read_a1_values = stub
        w._read_sheet_task()
        self.assertEqual(
            [v[0] for v in observed if v[1]!=("A12",)],
            ["運算區", "主要計算區"]
        )
        self.assertEqual(w.store.data["sheet"]["worksheet"],"主要計算區")
        self.assertIsNotNone(w.account_ruler.state)
        self.assertEqual(len(w.data_labels),11)

    def test_last_trade_data_row_stays_clear_of_ruler_heading(self):
        w = self.win
        w.resize(1150, 800)
        w.show()
        self.app.processEvents()
        last_row = w.data_labels["external_sl"]
        last_row_bottom = last_row.mapTo(w, QPoint(0, last_row.height())).y()
        ruler_title_top = w.ruler_title.mapTo(w, QPoint(0, 0)).y()
        self.assertGreaterEqual(ruler_title_top - last_row_bottom, 16)
        self.assertEqual(w.findChild(QGroupBox, "dataCard").height(), 295)
        row_tops = [
            w.data_labels[key].parentWidget().mapTo(w, QPoint(0, 0)).y()
            for key in (
                "external_direction", "external_lot", "external_tp", "external_sl"
            )
        ]
        row_gaps = [right - left for left, right in zip(row_tops, row_tops[1:])]
        self.assertEqual(len(set(row_gaps)), 1)
        self.assertGreaterEqual(row_gaps[0], 20)

    def test_missing_sheet_fails_closed_without_blocking_trade_data(self):
        w = self.win
        w.reader.read = lambda config: instruction()
        def stub(config, refs):
            if config["worksheet"] == "運算區":
                raise ValidationError("工作表不存在")
            return {"A12":""}
        w.reader.read_a1_values = stub
        w._read_sheet_task()
        self.assertEqual(w.instruction.symbol, "GOLD")
        self.assertIsNone(w.account_ruler.state)
        self.assertIn("無法讀取", w.account_ruler.placeholder)

    def test_switch_profile_data_does_not_leak(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name, w.store.data["sheet"]["spreadsheet_url"]))
        self.assertIsNotNone(w.account_ruler.state)
        w._apply_profile_ui()
        self.assertIsNone(w.account_ruler.state)
        w._show_ruler_sheet((sheet_values(), "", "some-old-profile", w.store.data["sheet"]["spreadsheet_url"]))
        self.assertIsNone(w.account_ruler.state)

    def test_hover_highlights_the_shared_goal_tick(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        self.app.processEvents()
        ruler = w.account_ruler
        groups, xs, _ = ruler._geometry()
        self.assertEqual(
            {name for name, _ in dict(groups)[D("55000")]},
            {"今天獲利目標", "帳號獲利目標"},
        )
        dot_x = round(xs[D("55000")])
        normal = ruler.grab().toImage().pixelColor(dot_x, 94)
        QTest.mouseMove(ruler, QPoint(dot_x, 94))
        self.app.processEvents()
        hovered = ruler.grab().toImage().pixelColor(dot_x, 94)
        self.assertGreater(
            hovered.red() + hovered.green() + hovered.blue(),
            normal.red() + normal.green() + normal.blue(),
        )
        self.assertEqual(ruler._hot_anchor, D("55000"))
        self.assertIn("55,035", ruler.toolTip())
        self.assertIn("55,000", ruler.toolTip())
        QTest.mouseMove(ruler, QPoint(200, 80))
        self.app.processEvents()
        self.assertIsNone(ruler._hot_anchor)

    def test_current_balance_dot_is_saturated_violet_and_hover_white(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        self.app.processEvents()
        ruler = w.account_ruler
        _, xs, _ = ruler._geometry()
        x = round(xs[D("54551")])
        normal = ruler.grab().toImage().pixelColor(x, 89)
        # Current equity marker is noticeably purple, not pale grey.
        self.assertGreater(normal.blue(), normal.red() + 30)
        self.assertGreater(normal.red(), normal.green() + 20)
        QTest.mouseMove(ruler, QPoint(x, 89))
        self.app.processEvents()
        hovered = ruler.grab().toImage().pixelColor(x, 89)
        self.assertGreater(sum((hovered.red(), hovered.green(), hovered.blue())),
                           sum((normal.red(), normal.green(), normal.blue())))
        self.assertEqual(ruler._hot_anchor, D("54551"))

    def test_initial_balance_marker_is_quiet_but_hover_is_visible(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        self.app.processEvents()
        ruler = w.account_ruler
        _, coords, _ = ruler._geometry()
        initial_x = round(coords[D("50000")])
        current_x = round(coords[D("54551")])
        img = ruler.grab().toImage()
        initial = img.pixelColor(initial_x, 89)
        current = img.pixelColor(current_x, 89)
        # The initial dot stays neutral grey and less luminous than current.
        self.assertLess(max(initial.red(), initial.green(), initial.blue()), 155)
        self.assertGreater(current.blue() - current.red(), 30)
        QTest.mouseMove(ruler, QPoint(initial_x, 89))
        self.app.processEvents()
        highlighted = ruler.grab().toImage().pixelColor(initial_x, 89)
        self.assertGreater(
            highlighted.red() + highlighted.green() + highlighted.blue(),
            initial.red() + initial.green() + initial.blue() + 120,
        )
        self.assertEqual(ruler._hot_anchor, D("50000"))

    def test_initial_marker_remains_muted_on_colored_active_segment(self):
        w = self.win
        item = instruction()
        w.instruction = item
        w._show_instruction(item)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        ruler = w.account_ruler
        # On this balance, the purple loss-direction line crosses initial.
        w.parameter_inputs["internal_balance"].setText("50200")
        with patch.object(w, "_write_trade_parameter_values"):
            w.parameter_inputs["internal_balance"].returnPressed.emit()
        self.app.processEvents()
        _, coords, _ = ruler._geometry()
        pix = ruler.grab().toImage().pixelColor(round(coords[D("50000")]), 89)
        self.assertLess(max(pix.red(), pix.green(), pix.blue()), 155)

    def test_dynamic_middle_segment_and_inverse_hedge_labels(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        self.app.processEvents()
        ruler = w.account_ruler
        self.assertIn("場外止損", w.ruler_win_label.text())
        self.assertIn("場外止盈", w.ruler_loss_label.text())
        self.assertNotIn("場內", w.ruler_win_label.text())
        self.assertNotIn("場內", w.ruler_loss_label.text())
        self.assertFalse(w.ruler_win_label.isVisible())
        self.assertFalse(w.ruler_loss_label.isVisible())
        self.assertTrue(ruler.isVisible())
        self.assertEqual(len(ruler._segment_regions), 2)
        original_centers = [rect.center().x() for rect, _ in ruler._segment_regions]
        # Typing is only a draft and must not move the ruler.
        entry = w.parameter_inputs["internal_balance"]
        entry.setText("53,000")
        self.app.processEvents()
        self.assertEqual(w.account_ruler.state.balance, D("54551"))
        self.assertEqual(
            original_centers,
            [rect.center().x() for rect, _ in ruler._segment_regions],
        )
        # Pressing Enter updates the ruler immediately, before the existing
        # asynchronous sheet-write callback (mocked here for safety).
        with patch.object(w, "_write_trade_parameter_values") as write:
            entry.returnPressed.emit()
        self.app.processEvents()
        write.assert_called_once()
        self.assertEqual(w.account_ruler.state.balance, D("53000"))
        updated_centers = [rect.center().x() for rect, _ in ruler._segment_regions]
        self.assertNotEqual(original_centers, updated_centers)

    def test_daily_pnl_is_draft_until_its_own_enter(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        balance = w.parameter_inputs["internal_balance"]
        pnl = w.parameter_inputs["daily_pnl"]
        balance.setText("53000")
        pnl.setText("=+250")
        self.app.processEvents()
        original = w.account_ruler.state
        self.assertEqual(original.balance, D("54551"))
        self.assertEqual(dict(original.markers)["今天獲利目標"], D("55035"))
        with patch.object(w, "_write_trade_parameter_values"):
            balance.returnPressed.emit()
        self.app.processEvents()
        changed = w.account_ruler.state
        self.assertEqual(changed.balance, D("53000"))
        self.assertEqual(dict(changed.markers)["今天獲利目標"], D("53484"))
        # The other field still says +250, but it must stay unconfirmed.
        self.assertEqual(w._ruler_confirmed_parameters["daily_pnl"], "")
        with patch.object(w, "_write_trade_parameter_values"):
            pnl.returnPressed.emit()
        self.app.processEvents()
        self.assertEqual(
            dict(w.account_ruler.state.markers)["今天獲利目標"], D("53234")
        )
        pnl.setText("=+750")
        self.app.processEvents()
        self.assertEqual(
            dict(w.account_ruler.state.markers)["今天獲利目標"], D("53234")
        )

    def test_update_button_confirms_both_cash_fields_and_reset_clears(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        w.parameter_inputs["internal_balance"].setText("53000")
        w.parameter_inputs["daily_pnl"].setText("-100")
        self.app.processEvents()
        self.assertEqual(w.account_ruler.state.balance, D("54551"))
        with patch.object(w, "_write_trade_parameter_values") as write:
            w.parameter_update_button.click()
        self.app.processEvents()
        write.assert_called_once()
        self.assertEqual(w.account_ruler.state.balance, D("53000"))
        self.assertEqual(
            dict(w.account_ruler.state.markers)["今天獲利目標"], D("53584")
        )
        w._clear_parameter_inputs(["internal_balance", "daily_pnl"])
        self.app.processEvents()
        self.assertEqual(w._ruler_confirmed_parameters,
                         {"internal_balance": "", "daily_pnl": ""})
        self.assertEqual(w.account_ruler.state.balance, D("54551"))

    def test_profile_switch_discards_enter_confirmed_preview(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        w.parameter_inputs["internal_balance"].setText("53000")
        with patch.object(w, "_write_trade_parameter_values"):
            w.parameter_inputs["internal_balance"].returnPressed.emit()
        self.assertEqual(w.account_ruler.state.balance, D("53000"))
        w._apply_profile_ui()
        self.assertEqual(w._ruler_confirmed_parameters,
                         {"internal_balance": "", "daily_pnl": ""})
        self.assertIsNone(w.account_ruler.state)

    def test_equal_initial_and_current_balance_both_fit_at_compact_height(self):
        w = self.win
        item = instruction()
        w.instruction = item
        w._show_instruction(item)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                             w.store.data["sheet"]["spreadsheet_url"]))
        w.parameter_inputs["internal_balance"].setText("50000")
        with patch.object(w, "_write_trade_parameter_values"):
            w.parameter_inputs["internal_balance"].returnPressed.emit()
        w.resize(1020, 650)
        self.app.processEvents()
        ruler = w.account_ruler
        ruler.grab()
        matches = [
            rect for rect, anchor in ruler._hit_regions
            if anchor == D("50000") and rect.width() > 70
        ]
        self.assertEqual(len(matches), 1)
        self.assertLess(matches[0].bottom(), ruler.height())
        grouped = dict(display_groups(ruler.state.markers))
        self.assertEqual({name for name, _ in grouped[D("50000")]},
                         {"帳號初始餘額", "當前餘額"})

    def test_layout_c_keeps_label_lanes_separate_at_small_window(self):
        w = self.win
        w.instruction = instruction()
        w._show_instruction(w.instruction)
        w._show_ruler_sheet((sheet_values(), "", w.profiles.active_name,
                            w.store.data["sheet"]["spreadsheet_url"]))
        for width, height in ((1150, 630), (1020, 580)):
            with self.subTest(width=width, height=height):
                w.resize(width, height)
                self.app.processEvents()
                ruler = w.account_ruler
                ruler.grab()
                self.assertGreaterEqual(w.height(), 630)
                self.assertGreaterEqual(ruler.height(), 206)
                from PySide6.QtWidgets import QGroupBox
                from PySide6.QtCore import QPoint
                data = w.trade_page.findChild(QGroupBox, "dataCard")
                data_pos = data.mapTo(w.trade_page, QPoint(0, 0))
                section_pos = w.ruler_section.mapTo(w.trade_page, QPoint(0, 0))
                self.assertGreaterEqual(
                    section_pos.y() - (data_pos.y() + data.height()), 10
                )
                self.assertLessEqual(
                    section_pos.y() + w.ruler_section.height(),
                    w.trade_page.height()
                )
                self.assertFalse(w.ruler_settings_button.isVisible())
                self.assertEqual(len(ruler._segment_regions), 2)
                # Label boxes occupy independent upper and lower rows.
                label_rects = [
                    rect for rect, _ in ruler._hit_regions
                    if rect.width() > 70
                ]
                top = sorted((r for r in label_rects if r.y() < 100),
                             key=lambda r:r.left())
                bottom = sorted((r for r in label_rects if r.y() >= 100),
                                key=lambda r:r.left())
                self.assertEqual(len(top), 3)
                self.assertEqual(len(bottom), 2)
                for lane in (top, bottom):
                    for left, right in zip(lane, lane[1:]):
                        self.assertLessEqual(left.right(), right.left() + 1)
                for rect in label_rects:
                    self.assertGreaterEqual(rect.left(), 0)
                    self.assertLessEqual(rect.right(), ruler.width())

    def test_no_injected_trade_callbacks(self):
        w = self.win
        self.assertEqual(len(w.data_labels),11)
        self.assertEqual(len(w.parameter_inputs),4)
        self.assertTrue(w.action_buttons["填入兩邊"].isVisible())
        self.assertEqual(w.ruler_settings_button.objectName(),"accountRulerSettings")


if __name__ == "__main__":
    unittest.main()

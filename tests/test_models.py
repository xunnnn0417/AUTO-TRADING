from decimal import Decimal
import ctypes
import unittest

from trading_helper.models import TradeInstruction, ValidationError
from trading_helper.sheets import SheetReader, _cell_position
from trading_helper.windows import (
    KEYEVENTF_KEYUP,
    INPUT,
    VK_LMENU,
    VK_LSHIFT,
    VK_RIGHT,
    WindowController,
    WindowInfo,
    _alt_shift_right_events,
    _extract_decimal_candidates,
)
from trading_helper.automation import PlatformAutomation, _decimal_close, _plain
from trading_helper.gui import _window_title_pattern


def valid_values() -> dict[str, str]:
    return {
        "status": "READY",
        "symbol": "EURUSD",
        "direction": "BUY",
        "internal_lot": "1.2",
        "internal_sl_points": "100",
        "internal_tp_points": "200",
        "external_lot": "0.8",
        "external_sl_points": "120",
        "external_tp_points": "240",
        "estimated_price": "1.10000",
        "point_size": "0.00001",
        "price_digits": "5",
    }


class TradeInstructionTests(unittest.TestCase):
    def test_direction_is_reversed(self) -> None:
        item = TradeInstruction.from_mapping(2, valid_values())
        self.assertEqual(item.internal_direction, "BUY")
        self.assertEqual(item.external_direction, "SELL")

    def test_mt5_prices_follow_direction(self) -> None:
        item = TradeInstruction.from_mapping(2, valid_values())
        sl, tp = item.estimated_prices("BUY", item.internal)
        self.assertEqual(sl, Decimal("-98.90000"))
        self.assertEqual(tp, Decimal("201.10000"))
        sl, tp = item.estimated_prices("SELL", item.external)
        self.assertEqual(sl, Decimal("121.10000"))
        self.assertEqual(tp, Decimal("-238.90000"))

    def test_mt5_prices_accept_current_platform_price(self) -> None:
        item = TradeInstruction.from_mapping(2, valid_values())
        sl, tp = item.estimated_prices(
            "BUY", item.internal, Decimal("2000.00")
        )
        self.assertEqual(sl, Decimal("1900.00"))
        self.assertEqual(tp, Decimal("2200.00"))

    def test_gold_mt5_uses_sheet_price_distances(self) -> None:
        values = valid_values()
        values["external_sl_points"] = "-31.35"
        values["external_tp_points"] = "6.05"
        values["point_size"] = "0.01"
        values["price_digits"] = "2"
        item = TradeInstruction.from_mapping(2, values)
        sl, tp = item.estimated_prices(
            "SELL", item.external, Decimal("4172.89")
        )
        self.assertEqual(item.format_price(sl), "4204.24")
        self.assertEqual(item.format_price(tp), "4166.84")

    def test_mt5_estimate_always_reads_ask(self) -> None:
        self.assertEqual(
            PlatformAutomation._mt5_price_point("external", "BUY"),
            "ask_price",
        )
        self.assertEqual(
            PlatformAutomation._mt5_price_point("external", "SELL"),
            "ask_price",
        )
        self.assertEqual(
            PlatformAutomation._mt5_price_point("internal", "SELL"),
            "ask_price",
        )

    def test_rejects_unknown_direction(self) -> None:
        values = valid_values()
        values["direction"] = "HOLD"
        with self.assertRaises(ValidationError):
            TradeInstruction.from_mapping(2, values)

    def test_accepts_chinese_direction(self) -> None:
        values = valid_values()
        values["direction"] = "多"
        item = TradeInstruction.from_mapping(2, values)
        self.assertEqual(item.internal_direction, "BUY")
        self.assertEqual(item.external_direction, "SELL")

        values["direction"] = "空"
        item = TradeInstruction.from_mapping(2, values)
        self.assertEqual(item.internal_direction, "SELL")
        self.assertEqual(item.external_direction, "BUY")

    def test_accepts_optional_account_parameters(self) -> None:
        values = valid_values()
        values.update(
            {
                "daily_pnl": "-123.45",
                "internal_balance": "50000",
                "expected_sl_points": "-6.81",
                "expected_sl_percent": "-1.2",
            }
        )

        item = TradeInstruction.from_mapping(2, values)

        self.assertEqual(item.daily_pnl, Decimal("-123.45"))
        self.assertEqual(item.internal_balance, Decimal("50000"))
        self.assertEqual(item.expected_sl_points, Decimal("-6.81"))
        self.assertEqual(item.expected_sl_percent, Decimal("-1.2"))

    def test_negative_stop_points_are_preserved_for_ctrader(self) -> None:
        values = valid_values()
        values["internal_sl_points"] = "-100"
        values["external_sl_points"] = "-120"
        item = TradeInstruction.from_mapping(2, values)
        self.assertEqual(item.internal.sl_points, Decimal("-100"))
        self.assertEqual(item.external.sl_points, Decimal("-120"))
        sl, _ = item.estimated_prices("BUY", item.internal)
        self.assertEqual(sl, Decimal("-98.90000"))

    def test_cell_reference_position(self) -> None:
        self.assertEqual(_cell_position("B5"), (4, 1))
        self.assertEqual(_cell_position("AA12"), (11, 26))

    def test_write_value_uses_cell_mapping(self) -> None:
        class FakeWorksheet:
            def __init__(self):
                self.updated = None

            def update_acell(self, target, value):
                self.updated = (target, value)

        class FakeReader(SheetReader):
            def __init__(self):
                self.worksheet = FakeWorksheet()

            def _open_gspread_worksheet(self, config):
                return self.worksheet

        config = {
            "mode": "service_account",
            "data_layout": "cells",
            "columns": {"internal_entry_price": "D8"},
        }
        reader = FakeReader()

        target = reader.write_value(config, "internal_entry_price", "4174.64")

        self.assertEqual(target, "D8")
        self.assertEqual(reader.worksheet.updated, ("D8", "4174.64"))

    def test_read_and_restore_a1_values(self) -> None:
        class FakeCell:
            def __init__(self, value):
                self.value = value

        class FakeWorksheet:
            def __init__(self):
                self.values = {"D8": "old", "A20": "", "E12": "warning"}

            def acell(self, target):
                return FakeCell(self.values.get(target, ""))

            def update_acell(self, target, value):
                self.values[target] = value

        class FakeReader(SheetReader):
            def __init__(self):
                self.worksheet = FakeWorksheet()

            def _open_gspread_worksheet(self, config):
                return self.worksheet

        config = {
            "mode": "service_account",
            "data_layout": "cells",
            "columns": {"internal_entry_price": "D8"},
        }
        reader = FakeReader()

        previous = reader.read_field_values(config, ["internal_entry_price"])
        warnings = reader.read_a1_values(config, ["A20", "E12"])
        reader.write_a1_values(config, {"D8": "old"})

        self.assertEqual(previous, {"D8": "old"})
        self.assertEqual(warnings, {"A20": "", "E12": "warning"})
        self.assertEqual(reader.worksheet.values["D8"], "old")

    def test_write_value_uses_selected_row_for_row_mapping(self) -> None:
        class FakeWorksheet:
            def __init__(self):
                self.updated = None

            def get_all_values(self):
                return [["Status", "Internal Entry Price"]]

            def update_acell(self, target, value):
                self.updated = (target, value)

        class FakeReader(SheetReader):
            def __init__(self):
                self.worksheet = FakeWorksheet()

            def _open_gspread_worksheet(self, config):
                return self.worksheet

        config = {
            "mode": "service_account",
            "data_layout": "row",
            "row_number": 2,
            "columns": {"internal_entry_price": "Internal Entry Price"},
        }
        reader = FakeReader()

        target = reader.write_value(
            config,
            "internal_entry_price",
            "4174.64",
            source_row=5,
        )

        self.assertEqual(target, "B5")
        self.assertEqual(reader.worksheet.updated, ("B5", "4174.64"))

    def test_calibration_uses_exact_pixels_when_window_size_matches(self) -> None:
        controller = WindowController(None)
        calibrated = WindowInfo(1, "test", 100, 50, 1100, 850)
        point = controller.relative_point(calibrated, 725, 410)
        moved = WindowInfo(1, "test", 300, 120, 1300, 920)
        self.assertEqual(controller.screen_point(moved, point), (925, 480))

    def test_plain_number_keeps_integer_trailing_zeroes(self) -> None:
        self.assertEqual(_plain(Decimal("4410")), "4410")
        self.assertEqual(_plain(Decimal("0.5700")), "0.57")

    def test_lot_match_accepts_equivalent_decimal_formats(self) -> None:
        self.assertTrue(
            _decimal_close(Decimal("0.40"), Decimal("0.4"), Decimal("0.001"))
        )
        self.assertTrue(
            _decimal_close(Decimal("0.400"), Decimal("0.4"), Decimal("0.001"))
        )
        self.assertFalse(
            _decimal_close(Decimal("0.45"), Decimal("0.4"), Decimal("0.001"))
        )

    def test_ctrader_points_apply_point_size(self) -> None:
        values = valid_values()
        values["internal_sl_points"] = "-7.11"
        values["internal_tp_points"] = "44.10"
        values["point_size"] = "0.01"
        item = TradeInstruction.from_mapping(2, values)
        automation = PlatformAutomation({}, None, None, lambda _: None)
        fields = automation._field_values(
            "GooeyTrade", "BUY", item.internal, item
        )
        self.assertEqual(fields[1][2], "-711")
        self.assertEqual(fields[2][2], "4410")

    def test_real_ctrader_uses_sheet_points_without_conversion(self) -> None:
        values = valid_values()
        values["internal_sl_points"] = "-7.11"
        values["internal_tp_points"] = "44.10"
        values["point_size"] = "0.01"
        item = TradeInstruction.from_mapping(2, values)
        automation = PlatformAutomation({}, None, None, lambda _: None)

        fields = automation._field_values(
            "cTrader", "BUY", item.internal, item
        )

        self.assertEqual(fields[1][2], "-7.11")
        self.assertEqual(fields[2][2], "44.1")

    def test_ctrader_does_not_convert_just_because_title_has_gooeytrade(self) -> None:
        values = valid_values()
        values["internal_sl_points"] = "-7.11"
        values["internal_tp_points"] = "44.10"
        values["point_size"] = "0.01"
        item = TradeInstruction.from_mapping(2, values)
        automation = PlatformAutomation({}, None, None, lambda _: None)

        uses_point_size = automation._ctrader_uses_point_size(
            "cTrader",
            {"window_title": {"internal": "GooeyTrade"}},
            "internal",
            {},
        )
        fields = automation._field_values(
            "cTrader",
            "BUY",
            item.internal,
            item,
            ctrader_uses_point_size=uses_point_size,
        )

        self.assertEqual(fields[1][2], "-7.11")
        self.assertEqual(fields[2][2], "44.1")

    def test_window_lookup_uses_selected_platform_title(self) -> None:
        automation = PlatformAutomation(
            {
                "platforms": {
                    "GooeyTrade": {
                        "window_title": {
                            "internal": "GooeyTrade",
                            "external": "GooeyTrade",
                        }
                    },
                    "cTrader": {
                        "window_title": {
                            "internal": "cTrader",
                            "external": "cTrader",
                        }
                    },
                }
            },
            None,
            None,
            lambda _: None,
        )

        class FakeWindows:
            def __init__(self):
                self.patterns = []

            def find(self, pattern):
                self.patterns.append(pattern)
                return WindowInfo(1, pattern, 0, 0, 100, 100)

        fake = FakeWindows()
        automation.windows = fake

        automation._window_for_point(
            automation.config["platforms"]["cTrader"],
            "internal",
            {"window_title": "GooeyTrade old point title"},
        )

        self.assertEqual(fake.patterns, ["cTrader"])

    def test_mt5_window_binding_uses_account_and_server_only(self) -> None:
        pattern = _window_title_pattern(
            "原版MT5",
            "569569160 - Bybit-Live-2 - Hedge - Infra Capital Limited - [GOLD_,M1]",
        )

        self.assertEqual(pattern, r"569569160.*Bybit\-Live\-2")

    def test_mt5_points_prefer_order_window_title(self) -> None:
        automation = PlatformAutomation(
            {
                "platforms": {
                    "MT5": {
                        "window_title": {
                            "internal": "Main Window",
                            "external": "Main Window",
                        }
                    }
                }
            },
            None,
            None,
            lambda _: None,
        )

        class FakeWindows:
            def __init__(self):
                self.patterns = []

            def find(self, pattern):
                self.patterns.append(pattern)
                return WindowInfo(1, pattern, 0, 0, 100, 100)

        fake = FakeWindows()
        automation.windows = fake

        automation._window_for_point(
            automation.config["platforms"]["MT5"],
            "external",
            {"window_title": "Order Window"},
        )

        self.assertEqual(fake.patterns, ["Order Window"])

    def test_ctrader_window_binding_uses_platform_keyword(self) -> None:
        self.assertEqual(
            _window_title_pattern("GooeyTrade", "GooeyTrade cTrader 5.7.10"),
            "GooeyTrade",
        )
        self.assertEqual(
            _window_title_pattern("cTrader", "cTrader"),
            "cTrader",
        )

    def test_mt5_position_point_moves_by_calibrated_row_height(self) -> None:
        point = {"x": 0.5, "y": 0.4, "x_px": 500, "y_px": 400}
        first = {"y": 0.3, "y_px": 300}
        second = {"y": 0.35, "y_px": 350}

        moved = PlatformAutomation._offset_position_point(
            point, first, second, 2
        )

        self.assertEqual(moved["y"], 0.5)
        self.assertEqual(moved["y_px"], 500)

    def test_ocr_price_parser_prefers_complete_price(self) -> None:
        values = _extract_decimal_candidates(["0.18", "4180.92", "18"])
        self.assertEqual(values[0], Decimal("4180.92"))

    def test_alt_shift_right_holds_both_modifiers(self) -> None:
        events = _alt_shift_right_events()
        self.assertEqual([key for key, _ in events[:3]], [
            VK_LMENU,
            VK_LSHIFT,
            VK_RIGHT,
        ])
        self.assertEqual(events[3][0], VK_RIGHT)
        self.assertTrue(events[3][1] & KEYEVENTF_KEYUP)
        self.assertEqual([key for key, _ in events[4:]], [
            VK_LSHIFT,
            VK_LMENU,
        ])
        self.assertTrue(all(flags & KEYEVENTF_KEYUP for _, flags in events[4:]))
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


if __name__ == "__main__":
    unittest.main()

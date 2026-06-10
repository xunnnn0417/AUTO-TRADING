from decimal import Decimal
import unittest

from trading_helper.models import TradeInstruction, ValidationError
from trading_helper.sheets import _cell_position
from trading_helper.windows import (
    WindowController,
    WindowInfo,
    _extract_decimal_candidates,
)
from trading_helper.automation import PlatformAutomation, _plain


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
        self.assertEqual(sl, Decimal("1.09900"))
        self.assertEqual(tp, Decimal("1.10200"))
        sl, tp = item.estimated_prices("SELL", item.external)
        self.assertEqual(sl, Decimal("1.10120"))
        self.assertEqual(tp, Decimal("1.09760"))

    def test_mt5_prices_accept_current_platform_price(self) -> None:
        item = TradeInstruction.from_mapping(2, valid_values())
        sl, tp = item.estimated_prices(
            "BUY", item.internal, Decimal("2000.00")
        )
        self.assertEqual(sl, Decimal("1999.99900"))
        self.assertEqual(tp, Decimal("2000.00200"))

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

    def test_negative_stop_points_are_preserved_for_ctrader(self) -> None:
        values = valid_values()
        values["internal_sl_points"] = "-100"
        values["external_sl_points"] = "-120"
        item = TradeInstruction.from_mapping(2, values)
        self.assertEqual(item.internal.sl_points, Decimal("-100"))
        self.assertEqual(item.external.sl_points, Decimal("-120"))
        sl, _ = item.estimated_prices("BUY", item.internal)
        self.assertEqual(sl, Decimal("1.09900"))

    def test_cell_reference_position(self) -> None:
        self.assertEqual(_cell_position("B5"), (4, 1))
        self.assertEqual(_cell_position("AA12"), (11, 26))

    def test_calibration_uses_exact_pixels_when_window_size_matches(self) -> None:
        controller = WindowController(None)
        calibrated = WindowInfo(1, "test", 100, 50, 1100, 850)
        point = controller.relative_point(calibrated, 725, 410)
        moved = WindowInfo(1, "test", 300, 120, 1300, 920)
        self.assertEqual(controller.screen_point(moved, point), (925, 480))

    def test_plain_number_keeps_integer_trailing_zeroes(self) -> None:
        self.assertEqual(_plain(Decimal("4410")), "4410")
        self.assertEqual(_plain(Decimal("0.5700")), "0.57")

    def test_ctrader_points_apply_point_size(self) -> None:
        values = valid_values()
        values["internal_sl_points"] = "-7.11"
        values["internal_tp_points"] = "44.10"
        values["point_size"] = "0.01"
        item = TradeInstruction.from_mapping(2, values)
        automation = PlatformAutomation({}, None, None, lambda _: None)
        fields = automation._field_values(
            "cTrader", "BUY", item.internal, item
        )
        self.assertEqual(fields[1][2], "-711")
        self.assertEqual(fields[2][2], "4410")

    def test_ocr_price_parser_prefers_complete_price(self) -> None:
        values = _extract_decimal_candidates(["0.18", "4180.92", "18"])
        self.assertEqual(values[0], Decimal("4180.92"))


if __name__ == "__main__":
    unittest.main()

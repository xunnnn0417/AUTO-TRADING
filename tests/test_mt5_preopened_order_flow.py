"""MT5 pre-opened modal is reused; a new-order click happens at most once.
All tests are offline, with no real broker clicks or fills.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.automation import PlatformAutomation
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.models import TradeInstruction, SideValues
from trading_helper.windows import AutomationError, WindowInfo


class ExistingMt5OrderDialogTests(unittest.TestCase):
    def setUp(self):
        self.main = WindowInfo(
            10, "53099775 - ICMarketsSC-Demo", 0, 0, 1920, 1040,
        )
        self.dialog = WindowInfo(
            11, "訂單: XAUUSD - Gold vs US Dollar", 389, 229, 1531, 792,
        )
        self.points = {
            key: {
                "x_px": 400, "y_px": y, "window_width": 1142,
                "window_height": 563, "window_title": r"訂單:\ XAUUSD\+",
            }
            for key, y in (
                ("lot_input", 120), ("sl_input", 154), ("tp_input", 188)
            )
        }
        self.points["new_order_button"] = {
            "x_px": 42, "y_px": 30, "window_width": 1920,
            "window_height": 1040,
        }
        self.profile = {
            "window_title": {"internal": "ICMarketsSC-Demo",
                             "external": "ICMarketsSC-Demo"},
            "points": self.points,
        }
        self.windows = MagicMock()
        self.windows.find.return_value = self.main
        self.automation = PlatformAutomation(
            {"platforms": {"MT5": self.profile}},
            self.windows, SimpleNamespace(guard=lambda: None),
            lambda _: None,
        )
        self.automation._fill_field = MagicMock()
        self.automation._verify_filled_side = MagicMock()
        self.instruction = TradeInstruction(
            source_row=2, status="", symbol="XAUUSD",
            sheet_direction="BUY",
            internal=SideValues(Decimal(".4"), Decimal("-6"), Decimal("10")),
            external=SideValues(Decimal(".16"), Decimal("-8"), Decimal("9")),
            estimated_price=Decimal("4100"),
            point_size=Decimal(".01"), price_digits=2,
        )

    def test_preopened_mt5_dialog_is_reused_without_new_order_click(self):
        with patch.object(
            DemoUiBrokerPort, "_form_window",
            return_value=(self.profile, self.dialog),
        ) as lookup:
            self.automation.fill("MT5", "external", self.instruction)
        lookup.assert_called_once_with(
            "MT5", "external", allow_absent=True,
        )
        self.windows.click.assert_not_called()
        self.automation._verify_filled_side.assert_called_once()
        self.assertEqual(
            self.automation._verify_filled_side.call_args.args[6],
            self.dialog,
        )

    def test_absent_mt5_dialog_opens_once_then_uses_verified_modal(self):
        with patch.object(
            DemoUiBrokerPort, "_form_window",
            side_effect=[
                (self.profile, None), (self.profile, None),
                (self.profile, self.dialog),
            ],
        ) as lookup, patch("trading_helper.automation.time.sleep"):
            self.automation.fill("MT5", "external", self.instruction)
        self.assertEqual(lookup.call_count, 3)
        self.windows.click.assert_called_once_with(
            self.main, self.points["new_order_button"],
        )
        self.windows.wait_for_active_window_change.assert_not_called()
        self.windows.wait_for_point_window.assert_not_called()

    def test_existing_wrong_symbol_refuses_before_click(self):
        with patch.object(
            DemoUiBrokerPort, "_form_window",
            side_effect=AutomationError("MT5 商品不符"),
        ):
            with self.assertRaisesRegex(AutomationError, "商品不符"):
                self.automation.fill("MT5", "external", self.instruction)
        self.windows.click.assert_not_called()
        self.automation._fill_field.assert_not_called()

    def test_existing_window_does_not_need_new_order_calibration(self):
        self.points.pop("new_order_button")
        with patch.object(
            DemoUiBrokerPort, "_form_window",
            return_value=(self.profile, self.dialog),
        ):
            self.automation.fill("MT5", "external", self.instruction)
        self.windows.click.assert_not_called()

    def test_no_dialog_or_new_order_calibration_fails_closed(self):
        self.points.pop("new_order_button")
        with patch.object(
            DemoUiBrokerPort, "_form_window",
            return_value=(self.profile, None),
        ):
            with self.assertRaisesRegex(AutomationError, "尚未校準新訂單按鈕"):
                self.automation.fill("MT5", "external", self.instruction)
        self.windows.click.assert_not_called()
        self.automation._fill_field.assert_not_called()

    def test_failed_open_is_not_reclicked(self):
        with patch.object(
            DemoUiBrokerPort, "_form_window",
            return_value=(self.profile, None),
        ), patch(
            "trading_helper.automation.time.monotonic",
            side_effect=[1, 4],
        ):
            with self.assertRaisesRegex(AutomationError, "點擊新訂單後未找到"):
                self.automation.fill("MT5", "external", self.instruction)
        self.windows.click.assert_called_once()
        self.automation._fill_field.assert_not_called()


if __name__ == "__main__":
    unittest.main()

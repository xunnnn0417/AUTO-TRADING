"""Regression: never replace an MT5 order modal with the terminal main HWND."""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import WindowInfo, AutomationError


class Mt5OrderWindowTests(unittest.TestCase):
    def setUp(self):
        self.main = WindowInfo(
            800, "55512345 - ICMarketsSC-Demo: Test - Hedge",
            -9, -9, 1929, 1029,
        )
        self.dialog = WindowInfo(
            801, "訂單: XAUUSD - Gold vs US Dollar",
            389, 229, 1531, 792,
        )
        self.points = {
            "lot_input": dict(
                window_width=1142, window_height=563, x_px=391, y_px=120,
                window_title=r"訂單:\ XAUUSD\+\ \-\ Gold\ US\ Dollar",
            ),
            "sl_input": dict(window_width=1142, window_height=563, x_px=391, y_px=154),
            "tp_input": dict(window_width=1142, window_height=563, x_px=391, y_px=188),
        }
        self.automation = MagicMock()
        self.automation.config = {
            "platforms": {
                "MT5": {
                    "window_title": {"external": "ICMarketsSC-Demo", "internal": "ICMarketsSC-Demo"},
                    "points": self.points,
                }
            }
        }
        self.automation.windows.find.return_value = self.main
        self.automation.windows.list_windows.return_value = [self.dialog, self.main]
        self.port = DemoUiBrokerPort(self.automation, lambda msg: None)
        self.port.set_expected_symbol("XAUUSD")
        self.owned = patch.object(
            self.port, "_mt5_owned_order_dialog",
            side_effect=lambda main, child: main == 800 and child in (801, 802),
        )

    def test_stale_broker_symbol_suffix_selects_owned_real_dialog(self):
        with self.owned:
            _, selected = self.port._form_window("MT5", "external")
        self.assertEqual(selected.handle, self.dialog.handle)
        self.automation._window_for_point.assert_not_called()

    def test_readback_uses_selected_dialog_and_keeps_field_verification(self):
        self.automation.windows.read_fill_snapshot.return_value = {
            "values": {
                "lot_input": "0.16",
                "sl_input": "4125.56",
                "tp_input": "4164.61",
            },
            "direction": None, "checks": {},
        }
        self.automation._normalize_numeric_input.side_effect = (
            lambda raw, expected=None: Decimal(str(raw))
        )
        with self.owned:
            self.port.verify_order_form("MT5", "external", "BUY", Decimal("0.16"))
        self.automation.windows.read_fill_snapshot.assert_called_once_with(
            self.dialog, self.points, ctrader=False,
        )
        self.automation.windows.click.assert_not_called()

    def test_no_owned_order_dialog_stops_before_any_click(self):
        self.automation.windows.list_windows.return_value = [self.main]
        with self.owned:
            with self.assertRaisesRegex(AutomationError, "沒有找到唯一"):
                self.port._form_window("MT5", "external")
        self.automation._window_for_point.assert_not_called()
        self.automation.windows.click.assert_not_called()

    def test_wrong_size_refuses_to_reuse_calibration(self):
        wrong = WindowInfo(
            801, self.dialog.title, 389, 229, 1500, 792,
        )
        self.automation.windows.list_windows.return_value = [self.main, wrong]
        with self.owned:
            with self.assertRaisesRegex(AutomationError, "視窗尺寸"):
                self.port._form_window("MT5", "external")

    def test_wrong_symbol_or_unowned_dialog_is_not_allowed(self):
        wrong = WindowInfo(
            801, "Order: BTCUSD - Bitcoin", 389, 229, 1531, 792,
        )
        self.automation.windows.list_windows.return_value = [self.main, wrong]
        with self.owned:
            with self.assertRaises(AutomationError):
                self.port._form_window("MT5", "external")
        self.automation.windows.list_windows.return_value = [self.main, self.dialog]
        with patch.object(self.port, "_mt5_owned_order_dialog", return_value=False):
            with self.assertRaises(AutomationError):
                self.port._form_window("MT5", "external")

    def test_multiple_owned_order_dialogs_are_rejected(self):
        second = WindowInfo(
            802, "Order: XAUUSD+ - Gold", 389, 229, 1531, 792,
        )
        self.automation.windows.list_windows.return_value = [
            self.main, self.dialog, second,
        ]
        with self.owned:
            with self.assertRaisesRegex(AutomationError, "符合 2 個"):
                self.port._form_window("MT5", "external")


if __name__ == "__main__":
    unittest.main()

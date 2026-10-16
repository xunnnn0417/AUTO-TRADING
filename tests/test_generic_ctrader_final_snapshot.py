"""LAB-only simulated cTrader final-click snapshot and main HWND invariants.

All UIA, account and click objects are synthetic. No broker or order is touched.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.automation import PlatformAutomation
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError, WindowController, WindowInfo


class MainWindowTests(unittest.TestCase):
    def setUp(self):
        self.ctrl = WindowController(SimpleNamespace(guard=lambda: None))
        self.point = {"window_width": 1938, "window_height": 1038}
        self.main = WindowInfo(22, "cTrader 5.5.21", 0, 0, 1938, 1038)
        self.dialog = WindowInfo(
            11, "Modify order or position - cTrader",
            0, 0, 1199, 772
        )
        self.ctrl.find_all = MagicMock(
            return_value=[self.dialog, self.main]
        )

    def test_main_chosen_over_same_title_popup(self):
        actual = self.ctrl.find_calibrated_main("cTrader", self.point)
        self.assertEqual(actual.handle, self.main.handle)

    def test_arbitrary_calibrated_screen_size_is_supported(self):
        other = WindowInfo(44, "cTrader 5.5.21", 0, 0, 1440, 900)
        self.ctrl.find_all.return_value = [self.dialog, other]
        actual = self.ctrl.find_calibrated_main(
            "cTrader", {"window_width": 1440, "window_height": 900}
        )
        self.assertEqual(actual.handle, other.handle)

    def test_duplicate_main_fail_closed(self):
        second = WindowInfo(88, "cTrader 5.6.0", 0, 0, 1938, 1038)
        self.ctrl.find_all.return_value = [
            self.main, second, self.dialog
        ]
        with self.assertRaises(AutomationError):
            self.ctrl.find_calibrated_main("cTrader", self.point)

    def test_resized_window_fail_closed(self):
        self.ctrl.find_all.return_value = [self.dialog]
        with self.assertRaises(AutomationError):
            self.ctrl.find_calibrated_main("cTrader", self.point)

    def test_resized_main_identified_but_stale_calibration_cannot_click(self):
        resized = WindowInfo(66, "cTrader 5.6.0", 0, 0, 1580, 900)
        self.ctrl.find_all.return_value = [self.dialog, resized]
        selected = self.ctrl.find_calibrated_main("cTrader", self.point)
        self.assertEqual(selected.handle, resized.handle)
        # Identification succeeds, but using the old 1938x1038 mouse
        # calibration remains forbidden: never scale/guess broker clicks.
        with self.assertRaises(AutomationError):
            self.ctrl.screen_point(selected, {
                **self.point, "x_px": 100, "y_px": 100
            })

    def test_main_with_wrong_native_title_still_fails(self):
        impostor = WindowInfo(
            77, "cTrader Modify order or position", 0, 0, 1938, 1038
        )
        self.ctrl.find_all.return_value = [self.dialog, impostor]
        with self.assertRaises(AutomationError):
            self.ctrl.find_calibrated_main("cTrader", self.point)

    def test_missing_calibration_fails_closed(self):
        with self.assertRaises(AutomationError):
            self.ctrl.find_calibrated_main("cTrader", {})

    def test_gooeytrade_uses_own_main_title(self):
        gooey = WindowInfo(75, "GooeyTrade", 0, 0, 1938, 1038)
        self.ctrl.find_all.return_value = [self.main, gooey]
        self.assertEqual(
            self.ctrl.find_calibrated_main(
                "GooeyTrade", self.point, platform="GooeyTrade"
            ).handle, 75
        )


class Node:
    def __init__(self, automation_id, kind, text="", bounds=None,
                 parent=None):
        self.element_info = SimpleNamespace(
            automation_id=automation_id, control_type=kind
        )
        self._text = text
        self._bounds = bounds or (0, 0, 10, 10)
        self._parent = parent

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def window_text(self):
        return self._text

    def rectangle(self):
        return SimpleNamespace(
            left=self._bounds[0], top=self._bounds[1],
            right=self._bounds[2], bottom=self._bounds[3]
        )

    def parent(self):
        return self._parent


class OneInventorySubmitTests(unittest.TestCase):
    def setUp(self):
        self.window = WindowInfo(
            202, "cTrader 5.5.21", 0, 0, 1938, 1038
        )
        grandparent = Node("PropertySectionView_AId", "Custom")
        parent = Node(
            "AspPlaceOrderButton_AId", "Custom",
            parent=grandparent
        )
        self.button = Node(
            "Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId",
            "Button", bounds=(1500, 550, 1600, 650),
            parent=parent,
        )
        self.account = Node(
            "CTraderAccountNumberTextBlock_AId", "Text", "12345678"
        )
        self.kind = Node(
            "CTraderAccountTypeTextBlock_AId", "Text", "Demo"
        )
        self.broker = Node("BrokerNameShort_AId", "Text", "Mock Broker")
        self.symbol = Node(
            "SymbolQuickInfoTemplates__TextBlock_Description_AId",
            "Text", "Gold vs US Dollar",
            bounds=(1520, 190, 1800, 205),
        )
        self.nodes = [
            self.account, self.kind, self.broker, self.symbol, self.button
        ]
        self.read_snapshot = MagicMock(return_value={
            "values": {
                "lot_input": "0.74",
                "sl_input": "-500",
                "tp_input": "200",
            },
            "direction": "SELL",
            "checks": {"sl_checkbox": True, "tp_checkbox": True},
        })
        self.windows = SimpleNamespace(
            focus=MagicMock(return_value=self.window),
            screen_point=MagicMock(return_value=(1550, 600)),
            read_fill_snapshot=self.read_snapshot,
            click=MagicMock(),
            relative_point=MagicMock(),
        )
        self.config = {"platforms": {"cTrader": {
            "points": {
                "order_submit_button": {
                    "window_width": 1938,
                    "window_height": 1038,
                },
            }
        }}}
        automation = SimpleNamespace(
            windows=self.windows,
            config=self.config,
            emergency=SimpleNamespace(guard=lambda: None),
            _normalize_numeric_input=PlatformAutomation._normalize_numeric_input,
            _last_verified_fills={
                ("cTrader", "external"): {
                    "direction": "SELL",
                    "symbol": "XAUUSD",
                    "values": {
                        "lot_input": Decimal("0.74"),
                        "sl_input": Decimal("-500"),
                        "tp_input": Decimal("200"),
                    },
                }
            },
        )
        self.adapter = DemoUiBrokerPort(automation, MagicMock())
        self.adapter.set_expected_symbol("XAUUSD")
        self.adapter._form_window = MagicMock(
            return_value=(self.config["platforms"]["cTrader"], self.window)
        )
        self.root = SimpleNamespace(
            descendants=MagicMock(side_effect=lambda: list(self.nodes))
        )

    def submit(self):
        with patch(
            "pywinauto.Desktop",
            return_value=SimpleNamespace(
                window=MagicMock(return_value=self.root)
            ),
        ):
            self.adapter.submit_once(
                "cTrader", "external", "SELL",
                Decimal("0.74"), "offline-id"
            )

    def test_single_fresh_inventory_drives_all_guards_and_click(self):
        self.submit()
        self.root.descendants.assert_called_once_with()
        self.windows.click.assert_called_once()
        self.assertIs(
            self.read_snapshot.call_args.kwargs["_controls"][0],
            self.account,
        )
        timings = self.adapter.submit_phase_timings["external"]
        self.assertLessEqual(
            timings["start"], timings["uia_inventory_returned"]
        )
        self.assertLessEqual(
            timings["uia_inventory_returned"], timings["click_started"]
        )

    def test_non_demo_cannot_click(self):
        self.kind._text = "Live"
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_duplicate_account_control_cannot_click(self):
        self.nodes.append(Node(
            "CTraderAccountNumberTextBlock_AId", "Text", "12345678"
        ))
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_wrong_symbol_cannot_click(self):
        self.symbol._text = "Silver vs US Dollar"
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_empty_uia_inventory_cannot_click(self):
        self.nodes.clear()
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_missing_order_button_cannot_click(self):
        self.nodes.remove(self.button)
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_duplicate_order_button_cannot_click(self):
        self.nodes.append(self.button)
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_wrong_direction_cannot_click(self):
        self.read_snapshot.return_value["direction"] = "BUY"
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_missing_sl_cannot_click(self):
        self.read_snapshot.return_value["values"]["sl_input"] = "0"
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_nonzero_but_wrong_sl_cannot_click(self):
        self.read_snapshot.return_value["values"]["sl_input"] = "-499"
        with self.assertRaisesRegex(AutomationError, "被改動"):
            self.submit()
        self.windows.click.assert_not_called()

    def test_nonzero_but_wrong_tp_cannot_click(self):
        self.read_snapshot.return_value["values"]["tp_input"] = "201"
        with self.assertRaisesRegex(AutomationError, "被改動"):
            self.submit()
        self.windows.click.assert_not_called()

    def test_final_order_with_no_verified_fill_cannot_click(self):
        self.adapter.automation._last_verified_fills.clear()
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_verified_fill_wrong_direction_cannot_click(self):
        self.adapter.automation._last_verified_fills[
            ("cTrader", "external")
        ]["direction"] = "BUY"
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()

    def test_account_switch_between_attempts_cannot_click(self):
        self.submit()
        self.windows.click.reset_mock()
        self.account._text = "87654321"
        with self.assertRaises(AutomationError):
            self.submit()
        self.windows.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

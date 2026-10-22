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
        # A maximized window on a different resolution still fails closed;
        # never scale or guess with the old 1938x1038 mouse calibration.
        with patch.object(self.ctrl, "_is_maximized", return_value=True):
            with self.assertRaisesRegex(AutomationError, "尺寸"):
                self.ctrl.find_calibrated_main("cTrader", self.point)

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

    def test_mt5_maximizes_unique_terminal_and_rechecks_not_order_dialog(self):
        terminal = WindowInfo(
            91,
            "53099775 - ICMarketsSC-Demo: Demo - Hedge - [BTCUSD,H1]",
            0, 0, 1600, 900,
        )
        order_dialog = WindowInfo(
            92, "Order: BTCUSD - Bitcoin (USD)", 0, 0, 620, 480
        )
        current = {"terminal": terminal}
        controller = WindowController(SimpleNamespace(guard=lambda: None))
        controller.find_all = MagicMock(
            side_effect=lambda _pattern: [order_dialog, current["terminal"]]
        )

        def maximize(handle):
            self.assertEqual(handle, terminal.handle)
            current["terminal"] = WindowInfo(
                91, terminal.title, 0, 0, 1938, 1038
            )

        with patch.object(controller, "_is_maximized", return_value=False), \
             patch.object(controller, "_maximize_window", side_effect=maximize) as maximize_call:
            selected = controller.find_calibrated_main(
                r"53099775.*ICMarketsSC-Demo",
                self.point,
                platform="MT5",
            )

        self.assertEqual(selected.handle, terminal.handle)
        self.assertEqual((selected.width, selected.height), (1938, 1038))
        maximize_call.assert_called_once_with(terminal.handle)

    def test_mt5_duplicate_terminals_fail_closed_without_maximize(self):
        first = WindowInfo(
            91, "53099775 - ICMarketsSC-Demo - [BTCUSD,H1]",
            0, 0, 1600, 900,
        )
        second = WindowInfo(
            92, "53099775 - ICMarketsSC-Demo - [ETHUSD,H1]",
            0, 0, 1600, 900,
        )
        self.ctrl.find_all.return_value = [first, second]
        with patch.object(self.ctrl, "_maximize_window") as maximize:
            with self.assertRaisesRegex(AutomationError, "主交易視窗有 2"):
                self.ctrl.find_calibrated_main(
                    r"53099775.*ICMarketsSC-Demo",
                    self.point,
                    platform="MT5",
                )
        maximize.assert_not_called()

    def test_mt5_main_calibration_point_uses_main_window_resolver(self):
        from trading_helper.automation import PlatformAutomation

        point = {"window_width": 1938, "window_height": 1038}
        profile = {
            "window_title": {"internal": r"53099775.*ICMarketsSC-Demo"},
            "points": {"new_order_button": point},
        }
        controller = MagicMock(spec=WindowController)
        controller.find_calibrated_main.return_value = self.main
        automation = SimpleNamespace(
            config={"platforms": {"MT5": profile}}, windows=controller
        )

        selected = PlatformAutomation._window_for_point(
            automation, profile, "internal", point
        )

        self.assertEqual(selected.handle, self.main.handle)
        controller.find_calibrated_main.assert_called_once_with(
            r"53099775.*ICMarketsSC-Demo",
            point,
            platform="MT5",
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

    def test_btcusd_description_allows_matching_verified_submit(self):
        self.symbol._text = "Bitcoin vs US Dollar"
        self.adapter.set_expected_symbol("BTCUSD")
        self.adapter.automation._last_verified_fills[
            ("cTrader", "external")
        ]["symbol"] = "BTCUSD"
        self.submit()
        self.windows.click.assert_called_once()

    def test_btcusd_rejects_a_different_bitcoin_pair(self):
        self.symbol._text = "Bitcoin vs Tether"
        self.adapter.set_expected_symbol("BTCUSD")
        self.adapter.automation._last_verified_fills[
            ("cTrader", "external")
        ]["symbol"] = "BTCUSD"
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



class MT5FinalExpectedPriceTests(unittest.TestCase):
    """Wrong but nonzero MT5 prices cannot bypass final form readback."""

    def setUp(self):
        self.readback={
            "values": {
                "lot_input": "1.00",
                "sl_input": "4050.00",
                "tp_input": "4150.00",
            },
            "direction": None,
            "checks": {},
        }
        self.profile={"points": {}}
        self.windows=SimpleNamespace(
            read_fill_snapshot=MagicMock(return_value=self.readback)
        )
        self.automation=SimpleNamespace(
            config={"platforms":{"MT5":self.profile}},
            windows=self.windows,
            _normalize_numeric_input=PlatformAutomation._normalize_numeric_input,
            _last_verified_fills={
                ("MT5","internal"): {
                    "direction": "BUY",
                    "symbol": "XAUUSD",
                    "values": {
                        "lot_input": Decimal("1"),
                        "sl_input": Decimal("4050"),
                        "tp_input": Decimal("4150"),
                    },
                }
            },
        )
        self.adapter=DemoUiBrokerPort(self.automation,MagicMock())
        self.adapter.set_expected_symbol("XAUUSD")
        self.adapter.inspect_account=MagicMock()
        self.adapter._form_window=MagicMock(
            return_value=(self.profile,SimpleNamespace(title="MT5 Demo order"))
        )
        self.adapter._verify_instrument=MagicMock()

    def check(self):
        self.adapter.verify_order_form("MT5","internal","BUY",Decimal("1"))

    def test_exact_original_mt5_sl_tp_still_allowed(self):
        self.check()
        self.windows.read_fill_snapshot.assert_called_once()

    def test_nonzero_wrong_mt5_sl_rejected(self):
        self.readback["values"]["sl_input"]="4050.01"
        with self.assertRaisesRegex(AutomationError,"被改動"):
            self.check()

    def test_nonzero_wrong_mt5_tp_rejected(self):
        self.readback["values"]["tp_input"]="4149.99"
        with self.assertRaisesRegex(AutomationError,"被改動"):
            self.check()

    def test_missing_mt5_fill_receipt_rejected(self):
        self.automation._last_verified_fills.clear()
        with self.assertRaises(AutomationError):
            self.check()


if __name__ == "__main__":
    unittest.main()

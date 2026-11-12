"""Offline tests: cTrader popup title collision cannot replace bound main window."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import (
    AutomationError, EmergencyController, WindowController, WindowInfo,
)


def make_window(hwnd, title, width, height):
    return WindowInfo(hwnd, title, 0, 0, width, height)


class CTraderWindowChoiceTests(unittest.TestCase):
    def setUp(self):
        self.popup = make_window(101, "cTrader", 1199, 772)
        self.main = make_window(202, "cTrader 5.10.20", 1938, 1038)
        self.windows = WindowController(EmergencyController(lambda: None))
        self.windows.list_windows = lambda: [self.popup, self.main]
        self.config = {
            "platforms": {
                "cTrader": {
                    "window_title": {"external": "cTrader"},
                    "points": {
                        "lot_input": {
                            "window_width": 1938, "window_height": 1038
                        }
                    },
                },
                "MT5": {
                    "window_title": {"internal": "MT5"}
                },
            }
        }
        self.port = DemoUiBrokerPort(
            SimpleNamespace(config=self.config, windows=self.windows),
            MagicMock(),
        )

    def test_popup_first_selects_native_main_by_title(self):
        _, selected = self.port._bound("cTrader", "external")
        self.assertEqual(selected.handle, self.main.handle)

    def test_smaller_main_is_maximized_and_rechecked_before_use(self):
        self.main = make_window(202, "cTrader 5.10.20", 1600, 900)
        def maximize(_handle):
            self.main = make_window(202, "cTrader 5.10.20", 1938, 1038)

        with patch.object(self.windows, "_is_maximized", return_value=False), \
             patch.object(self.windows, "_maximize_window", side_effect=maximize) as maximize_call:
            _, selected = self.port._bound("cTrader", "external")
        self.assertEqual(selected.handle, self.main.handle)
        maximize_call.assert_called_once_with(self.main.handle)

    def test_ambiguous_main_windows_are_never_maximized(self):
        self.windows.list_windows = lambda: [
            self.popup, self.main,
            make_window(303, "cTrader 5.11.0", 1600, 900),
        ]
        with patch.object(self.windows, "_maximize_window") as maximize:
            with self.assertRaisesRegex(AutomationError, "主交易視窗有"):
                self.port._bound("cTrader", "external")
        maximize.assert_not_called()

    def test_click_coordinates_still_reject_resized_main(self):
        self.main = make_window(202, "cTrader 5.10.20", 1600, 900)
        with self.assertRaisesRegex(AutomationError, "尺寸"):
            self.windows.screen_point(self.main, self.config["platforms"]["cTrader"]["points"]["lot_input"])

    def test_multiple_matching_main_windows_fails_closed(self):
        self.windows.list_windows = lambda: [
            self.popup, self.main,
            make_window(303, "cTrader 5.11.0", 1920, 1080)
        ]
        with self.assertRaisesRegex(AutomationError, "主交易視窗有"):
            self.port._bound("cTrader", "external")

    def test_no_native_main_window_fails_closed(self):
        self.windows.list_windows = lambda: [self.popup]
        with self.assertRaisesRegex(AutomationError, "主交易視窗有"):
            self.port._bound("cTrader", "external")

    def test_mt5_still_uses_original_direct_lookup(self):
        self.windows.find = lambda _pattern: self.main
        _, found = self.port._bound("MT5", "internal")
        self.assertEqual(found, self.main)


if __name__ == "__main__":
    unittest.main()

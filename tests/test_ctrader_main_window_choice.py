"""Offline tests: cTrader popup title collision cannot replace bound main window."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError, WindowInfo


def make_window(hwnd, width, height):
    return WindowInfo(hwnd, "cTrader", 0, 0, width, height)


class CTraderWindowChoiceTests(unittest.TestCase):
    def setUp(self):
        self.popup = make_window(101, 1199, 772)
        self.main = make_window(202, 1938, 1038)
        self.windows = MagicMock()
        self.windows.find.return_value = self.popup
        self.windows.find_all.return_value = [self.popup, self.main]
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

    def test_popup_first_selects_unique_calibrated_main(self):
        _, selected = self.port._bound("cTrader", "external")
        self.assertEqual(selected.handle, self.main.handle)
        self.windows.find_all.assert_called_once_with("cTrader")

    def test_main_first_does_not_enumerate_again(self):
        self.windows.find.return_value = self.main
        _, selected = self.port._bound("cTrader", "external")
        self.assertEqual(selected.handle, self.main.handle)
        self.windows.find_all.assert_not_called()

    def test_multiple_matching_main_windows_fails_closed(self):
        self.windows.find_all.return_value = [
            self.popup, self.main, make_window(303, 1938, 1038)
        ]
        with self.assertRaisesRegex(AutomationError, "無唯一主視窗"):
            self.port._bound("cTrader", "external")

    def test_no_calibrated_main_window_fails_closed(self):
        self.windows.find_all.return_value = [self.popup]
        with self.assertRaisesRegex(AutomationError, "無唯一主視窗"):
            self.port._bound("cTrader", "external")

    def test_mt5_still_uses_original_direct_lookup(self):
        self.windows.find.return_value = self.main
        _, found = self.port._bound("MT5", "internal")
        self.assertEqual(found, self.main)
        self.windows.find_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Offline checks for cTrader's native empty-grid placeholder. No broker actions."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError


def make_grid(rows, count=0):
    grid = MagicMock()
    grid.descendants.side_effect = (
        lambda control_type: rows if control_type == "DataItem" else []
    )
    grid.iface_grid.CurrentRowCount = count
    return grid


def make_ghost():
    row = MagicMock()
    row.is_visible.return_value = False
    row.rectangle.return_value = SimpleNamespace(
        left=0, top=0, right=0, bottom=0
    )
    row.descendants.return_value = []
    return row


class CTraderEmptyGridPlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.port = object.__new__(DemoUiBrokerPort)

    def scan(self, grid):
        with patch.object(DemoUiBrokerPort, "_ctrader_grid", return_value=grid):
            return self.port._ctrader_positions("cTrader", "external", None)

    def test_hidden_placeholder_and_native_zero_means_empty(self):
        self.assertEqual(self.scan(make_grid([make_ghost()])), ())

    def test_multiple_hidden_placeholders_and_zero_means_empty(self):
        self.assertEqual(self.scan(make_grid([make_ghost(), make_ghost()])), ())

    def test_placeholder_with_native_position_count_fails_closed(self):
        with self.assertRaisesRegex(AutomationError, "cannot prove"):
            self.scan(make_grid([make_ghost()], count=1))

    def test_hidden_placeholder_with_text_fails_closed(self):
        ghost = make_ghost()
        text_node = MagicMock()
        text_node.window_text.return_value = "XAUUSD"
        ghost.descendants.return_value = [text_node]
        with self.assertRaisesRegex(AutomationError, "cannot prove"):
            self.scan(make_grid([ghost]))

    def test_visible_row_not_confused_with_empty_placeholder(self):
        ghost = make_ghost()
        ghost.is_visible.return_value = True
        with self.assertRaises(AutomationError):
            self.scan(make_grid([ghost]))

    def test_native_grid_count_read_failure_fails_closed(self):
        grid = make_grid([make_ghost()])
        del grid.iface_grid.CurrentRowCount
        with self.assertRaises(AutomationError):
            self.scan(grid)

    def test_genuinely_no_data_items_keeps_existing_behavior(self):
        self.assertEqual(self.scan(make_grid([])), ())


if __name__ == "__main__":
    unittest.main()

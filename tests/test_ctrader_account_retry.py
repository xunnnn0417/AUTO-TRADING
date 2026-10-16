"""Offline fail-closed tests for transient cTrader account UIA gaps."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError


def node(aid, text):
    item = MagicMock()
    item.element_info.automation_id = aid
    item.is_visible.return_value = True
    item.window_text.return_value = text
    return item


def identity(number="1234567", kind="Demo"):
    return [
        node("CTraderAccountNumberTextBlock_AId", number),
        node("CTraderAccountTypeTextBlock_AId", kind),
        node("SomeBrokerNameShort", "DemoBroker"),
    ]


class CTraderAccountRetryTests(unittest.TestCase):
    def make_port(self):
        port = DemoUiBrokerPort(SimpleNamespace(), lambda message: None)
        port._bound = MagicMock(
            return_value=({}, SimpleNamespace(handle=112, title="cTrader"))
        )
        return port

    def run_with_snapshots(self, snapshots, verify):
        port = self.make_port()
        with patch("pywinauto.Desktop") as desktop, patch(
            "trading_helper.demo_broker_port.time.sleep"
        ) as sleep:
            window = desktop.return_value.window.return_value
            window.descendants.side_effect = snapshots
            verify(port, window, sleep)

    def test_zero_then_unique_account_recovers_without_changing_identity(self):
        def verify(port, window, sleep):
            acc = port.inspect_account("cTrader", "external")
            self.assertEqual(acc.account_id, "1234567")
            self.assertTrue(acc.is_demo)
            self.assertEqual(window.descendants.call_count, 2)
            sleep.assert_called_once_with(0.12)
        self.run_with_snapshots([[], identity()], verify)

    def test_persistent_missing_account_fails_closed_after_three_reads(self):
        def verify(port, window, sleep):
            with self.assertRaises(AutomationError):
                port.inspect_account("cTrader", "external")
            self.assertEqual(window.descendants.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
        self.run_with_snapshots([[], [], []], verify)

    def test_duplicate_account_never_retries_or_accepts_one(self):
        def verify(port, window, sleep):
            with self.assertRaises(AutomationError):
                port.inspect_account("cTrader", "external")
            self.assertEqual(window.descendants.call_count, 1)
            sleep.assert_not_called()
        self.run_with_snapshots([identity() + [node(
            "CTraderAccountNumberTextBlock_AId", "9999999"
        )]], verify)

    def test_live_account_identity_fails_immediately(self):
        def verify(port, window, sleep):
            with self.assertRaises(AutomationError):
                port.inspect_account("cTrader", "external")
            self.assertEqual(window.descendants.call_count, 1)
            sleep.assert_not_called()
        self.run_with_snapshots([identity(kind="Live")], verify)

    def test_account_switch_during_workflow_still_rejected(self):
        def verify(port, window, sleep):
            first = port.inspect_account("cTrader", "external")
            self.assertEqual(first.account_id, "1234567")
            with self.assertRaises(AutomationError):
                port.inspect_account("cTrader", "external")
            self.assertEqual(window.descendants.call_count, 2)
            sleep.assert_not_called()
        self.run_with_snapshots([identity(), identity(number="9999999")], verify)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from trading_helper.demo_broker_port import DemoUiBrokerPort


class Tab:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def select(self):
        self.calls.append(self.name)


class PositionsTabRefreshTests(unittest.TestCase):
    def setUp(self):
        DemoUiBrokerPort._ctrader_tabs.clear()
        self.calls, self.logs = [], []
        self.port = DemoUiBrokerPort(None, self.logs.append)
        tabs = (Tab("orders", self.calls), Tab("positions", self.calls))
        DemoUiBrokerPort._ctrader_tabs[7] = tabs
        self.patch_find = patch.object(
            DemoUiBrokerPort, "find_ctrader_tabs",
            classmethod(lambda cls, h: cls._ctrader_tabs.setdefault(int(h), tabs)),
        )
        self.patch_find.start()
        self.patch_sleep = patch("trading_helper.demo_broker_port.time.sleep")
        self.patch_sleep.start()

    def tearDown(self):
        self.patch_find.stop()
        self.patch_sleep.stop()
        DemoUiBrokerPort._ctrader_tabs.clear()

    def run_with(self, readable):
        with patch.object(DemoUiBrokerPort, "_ctrader_grid_readable",
                          side_effect=readable):
            self.port.refresh_ctrader_positions_tab(SimpleNamespace(handle=7))

    def test_readable_after_first_toggle_stops(self):
        self.run_with([True])
        self.assertEqual(self.calls, ["orders", "positions"])
        self.assertEqual(self.logs, [])

    def test_unreadable_list_is_toggled_again_with_longer_wait(self):
        with patch("trading_helper.demo_broker_port.time.sleep") as sleep:
            self.run_with([False, True])
        self.assertEqual(self.calls, ["orders", "positions"] * 2)
        self.assertIn(0.5, [c.args[0] for c in sleep.call_args_list])
        self.assertEqual(self.logs, [])

    def test_still_unreadable_warns_at_fill_stage(self):
        self.run_with([False, False])
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(len(self.logs), 1)
        self.assertIn("持倉表仍讀不到", self.logs[0])


if __name__ == "__main__":
    unittest.main()

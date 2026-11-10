"""The test menu's one-leg actions are exercised with an offline fake broker."""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from trading_helper.auto_entry import (
    AutoEntryJournal, AutoEntryWorkflow, DemoAccount, Position,
    RecoveryRequired,
)
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.gui import TradingHelperApp
from trading_helper.test_mode import effective_test_symbol, test_symbol_scope
from trading_helper.windows import AutomationError
from tests.test_auto_entry_state_machine import FakeBrokerPort, instruction


class SingleLegFakePort(FakeBrokerPort):
    def __init__(self, *, mt5_external=False):
        super().__init__(mt5_internal=False)
        points = {
            name: {"id": name, "x_px": 10, "y_px": 10,
                   "window_width": 800, "window_height": 600}
            for name in (
                "lot_input", "sl_input", "tp_input", "order_submit_button",
                "order_submit_buy", "order_submit_sell",
                "position_order_row", "position_sl_input",
                "position_tp_input", "position_modify_confirm",
            )
        }
        self.automation = SimpleNamespace(config={"platforms": {
            "cTrader": {"points": dict(points)},
            "MT5": {"points": dict(points)},
        }})
        self.closed = []

    def confirm_new_position(
        self, platform, role, before, direction, volume, account_id
    ):
        position = super().confirm_new_position(
            platform, role, before, direction, volume, account_id
        )
        position=Position(
            position.ticket,position.account_id,position.platform,
            effective_test_symbol(position.symbol),position.direction,
            position.volume,position.entry_price,position.sl,position.tp,
        )
        if direction=="BUY":
            position=Position(
                position.ticket,position.account_id,position.platform,
                position.symbol,position.direction,position.volume,
                position.entry_price,position.entry_price-D("10"),
                position.entry_price+D("20"),
            )
        else:
            position=Position(
                position.ticket,position.account_id,position.platform,
                position.symbol,position.direction,position.volume,
                position.entry_price,position.entry_price+D("10"),
                position.entry_price-D("20"),
            )
        self.open_positions[role] = (position,)
        return position

    def close_position_once(self, position, role):
        self.events.append(("close", role, position.ticket))
        self.closed.append((role, position.ticket))
        self.open_positions[role] = ()


class CloseWindowActions:
    def __init__(self, port):
        self.port=port
        self.clicks=[]
    def screen_point(self, window, point):
        return (int(point["x_px"]),int(point["y_px"]))
    def click(self, window, point):
        self.clicks.append((window,point))
        self.port.positions=()


class CloseBrokerPort(DemoUiBrokerPort):
    def __init__(self, positions):
        self.profile={"points":{
            "position_close_button":{
                "x_px":300,"y_px":200,
                "window_width":800,"window_height":600,
            },
        }}
        self.account=DemoAccount("cTrader","111111","broker-Demo",True,True)
        self.positions=positions
        self.window=SimpleNamespace(handle=1,title="cTrader")
        automation=SimpleNamespace(
            emergency=SimpleNamespace(guard=lambda:None),
            windows=CloseWindowActions(self),
        )
        super().__init__(automation,lambda _message:None)
    def inspect_account(self, platform, role):
        return self._bind_verified_account(platform,role,self.account)
    def snapshot_positions(self, platform, role):
        return self.positions
    def _bound(self, platform, role):
        return self.profile,self.window


def side_position(role, *, mt5_external=False):
    item = instruction()
    if role == "internal":
        platform = "cTrader"
        account_id = "111111"
        return Position(
            "OLD-I", account_id, platform, item.symbol, "BUY", D("0.4"),
            D("4101.45"), D("4091.45"), D("4121.45"),
        )
    return Position(
        "OLD-E", "222222", "MT5", item.symbol, "SELL", D("0.2"),
        D("4101.65"), D("4111.65"), D("4081.65"),
    )


class SingleLegTestModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.port = SingleLegFakePort()
        self.journal = AutoEntryJournal(Path(self.temp.name) / "journal.json")
        self.flow = AutoEntryWorkflow(
            self.port, self.journal, lambda: None, lambda _message: None
        )
        self.item = instruction()

    def run_reentry(self, role):
        return self.flow.run_single_leg_test(
            self.item, "cTrader", "MT5", "test", "sheet",
            role=role, sync_sl_tp=True,
        )

    def test_internal_reentry_sends_only_internal_and_syncs_external(self):
        self.port.open_positions["external"] = (side_position("external"),)
        internal, external = self.run_reentry("internal")
        self.assertEqual(internal.ticket, "T-internal")
        self.assertEqual(external.ticket, "OLD-E")
        self.assertEqual(
            [event[1] for event in self.port.events if event[0] == "submit"],
            ["internal"],
        )
        self.assertTrue(any(event[0] == "modify" and event[1] == "OLD-E"
                            for event in self.port.events))

    def test_external_reentry_sends_only_external_and_syncs_it(self):
        self.port.open_positions["internal"] = (side_position("internal"),)
        internal, external = self.run_reentry("external")
        self.assertEqual(internal.ticket, "OLD-I")
        self.assertEqual(external.ticket, "T-external")
        self.assertEqual(
            [event[1] for event in self.port.events if event[0] == "submit"],
            ["external"],
        )
        self.assertTrue(any(event[0] == "modify" and event[1] == "T-external"
                            for event in self.port.events))

    def test_user_approved_reentry_syncs_and_runs_enabled_followup(self):
        self.port.open_positions["external"] = (side_position("external"),)
        internal,external=self.flow.run_single_leg_test(
            self.item,"cTrader","MT5","test","sheet",
            role="internal",sync_sl_tp=True,
            expected_other_ticket="OLD-E",
            expected_account_ids={
                "internal":"111111","external":"222222",
            },draw_tv=True,operation="user",
        )
        self.assertEqual((internal.ticket,external.ticket),("T-internal","OLD-E"))
        self.assertTrue(any(event[0]=="tv" for event in self.port.events))
        self.assertTrue(self.flow.last_key.startswith("user-reentry-"))
        self.assertEqual(
            self.journal.entry(self.flow.last_key)["status"],
            "user_reentry_complete",
        )

    def test_full_internal_reentry_test_skips_then_enters_internal_once(self):
        result=self.flow.run_test_scenario(
            self.item,"cTrader","MT5","test","sheet",
            scenario="reentry:internal",test_run_id="case-internal",
        )
        self.assertEqual(result["outcome"],"reentry_confirmed")
        self.assertEqual(
            [event[1] for event in self.port.events if event[0]=="submit"],
            ["external","internal"],
        )
        entry=self.journal.entry(self.flow.last_key)
        self.assertEqual(entry["status"],"complete")
        self.assertTrue(any(event[0]=="modify" for event in self.port.events))

    def test_full_external_reentry_test_skips_then_enters_external_once(self):
        result=self.flow.run_test_scenario(
            self.item,"cTrader","MT5","test","sheet",
            scenario="reentry:external",test_run_id="case-external",
        )
        self.assertEqual(result["outcome"],"reentry_confirmed")
        self.assertEqual(
            [event[1] for event in self.port.events if event[0]=="submit"],
            ["internal","external"],
        )
        entry=self.journal.entry(self.flow.last_key)
        self.assertEqual(entry["status"],"complete")
        self.assertTrue(any(event[0]=="modify" for event in self.port.events))

    def test_weekend_test_uses_temporary_symbol_and_completes_both_legs(self):
        with test_symbol_scope("ETHUSD"):
            result=self.flow.run_test_scenario(
                self.item,"cTrader","MT5","test","sheet",
                scenario="weekend:ETHUSD",test_run_id="case-weekend-eth",
            )
        self.assertEqual(result["outcome"],"weekend_pair_confirmed")
        self.assertEqual(
            [event[1] for event in self.port.events if event[0]=="submit"],
            ["internal","external"],
        )
        self.assertEqual(
            [position.symbol for position in result["positions"]],
            ["ETHUSD","ETHUSD"],
        )

    def test_full_internal_close_test_closes_both_then_stops(self):
        result=self.flow.run_test_scenario(
            self.item,"cTrader","MT5","test","sheet",
            scenario="close:internal",test_run_id="case-close-internal",
        )
        self.assertEqual(result["outcome"],"both_closed_waiting_user")
        self.assertEqual(
            [(role,ticket) for role,ticket in self.port.closed],
            [("internal","T-internal"),("external","T-external")],
        )
        self.assertEqual(self.port.open_positions["internal"],())
        self.assertEqual(self.port.open_positions["external"],())

    def test_full_external_close_test_reenters_and_syncs(self):
        result=self.flow.run_test_scenario(
            self.item,"cTrader","MT5","test","sheet",
            scenario="close:external",test_run_id="case-close-external",
        )
        self.assertEqual(result["outcome"],"external_reentered")
        self.assertEqual(self.port.closed,[("external","T-external")])
        self.assertEqual(result["positions"][0].ticket,"T-internal")
        self.assertEqual(result["positions"][1].ticket,"T-external")
        self.assertTrue(any(
            event[0]=="modify" and event[1]=="T-external"
            for event in self.port.events
        ))

    def test_reentry_requires_exactly_one_opposite_demo_position(self):
        with self.assertRaisesRegex(RecoveryRequired, "恰有一筆"):
            self.run_reentry("internal")
        self.assertFalse(any(event[0] == "submit" for event in self.port.events))

    def test_reentry_stops_if_confirmed_counterpart_ticket_changed(self):
        self.port.open_positions["external"] = (side_position("external"),)
        with self.assertRaisesRegex(RecoveryRequired,"編號已改變"):
            self.flow.run_single_leg_test(
                self.item,"cTrader","MT5","test","sheet",
                role="internal",sync_sl_tp=True,
                expected_other_ticket="STALE-TICKET",
            )
        self.assertFalse(any(event[0]=="submit" for event in self.port.events))

    def test_reentry_stops_if_either_demo_account_changed(self):
        self.port.open_positions["external"] = (side_position("external"),)
        with self.assertRaisesRegex(RecoveryRequired,"帳戶已改變"):
            self.flow.run_single_leg_test(
                self.item,"cTrader","MT5","test","sheet",
                role="internal",sync_sl_tp=True,
                expected_other_ticket="OLD-E",
                expected_account_ids={
                    "internal":"WRONG","external":"222222",
                },
            )
        self.assertFalse(any(event[0]=="submit" for event in self.port.events))

    def test_expired_reentry_window_refuses_submit(self):
        import time
        account=self.port.accounts["internal"]
        with self.assertRaisesRegex(RecoveryRequired,"15 秒"):
            self.flow._submit_and_confirm(
                "cTrader","internal","BUY",D("0.4"),account,(),
                "XAUUSD","test-expired-window",
                submit_deadline=time.monotonic()-1,
            )
        self.assertFalse(any(event[0]=="submit" for event in self.port.events))

    def test_close_test_closes_only_the_selected_role(self):
        self.port.open_positions["internal"] = (side_position("internal"),)
        closed = self.flow.run_single_leg_close_test(
            self.item, "cTrader", "MT5", "test", "sheet", role="internal"
        )
        self.assertEqual(closed.ticket, "OLD-I")
        self.assertEqual(self.port.closed, [("internal", "OLD-I")])
        self.assertEqual(self.port.open_positions["external"], ())

    def test_close_test_refuses_ambiguous_target(self):
        original = side_position("internal")
        self.port.open_positions["internal"] = (
            original,
            Position(
                "OLD-I-2", original.account_id, original.platform,
                original.symbol, original.direction, original.volume,
                original.entry_price, original.sl, original.tp,
            ),
        )
        with self.assertRaisesRegex(RecoveryRequired, "不是唯一一筆"):
            self.flow.run_single_leg_close_test(
                self.item, "cTrader", "MT5", "test", "sheet", role="internal"
            )
        self.assertEqual(self.port.closed, [])

    def test_user_close_requires_exact_ticket_and_empty_counterpart(self):
        self.port.open_positions["internal"] = (side_position("internal"),)
        with self.assertRaisesRegex(RecoveryRequired,"編號已改變"):
            self.flow.run_single_leg_close_test(
                self.item,"cTrader","MT5","test","sheet",
                role="internal",expected_ticket="STALE-TICKET",
                expected_account_ids={
                    "internal":"111111","external":"222222",
                },require_other_empty=True,operation="user",
            )
        self.assertEqual(self.port.closed,[])

    def test_user_close_stops_if_counterpart_has_also_filled(self):
        self.port.open_positions["internal"] = (side_position("internal"),)
        self.port.open_positions["external"] = (side_position("external"),)
        with self.assertRaisesRegex(RecoveryRequired,"另一邊目前也有持倉"):
            self.flow.run_single_leg_close_test(
                self.item,"cTrader","MT5","test","sheet",
                role="internal",expected_ticket="OLD-I",
                expected_account_ids={
                    "internal":"111111","external":"222222",
                },require_other_empty=True,operation="user",
            )
        self.assertEqual(self.port.closed,[])

    def test_user_close_confirms_both_demo_legs_empty(self):
        self.port.open_positions["internal"] = (side_position("internal"),)
        closed=self.flow.run_single_leg_close_test(
            self.item,"cTrader","MT5","test","sheet",
            role="internal",expected_ticket="OLD-I",
            expected_account_ids={
                "internal":"111111","external":"222222",
            },require_other_empty=True,operation="user",
        )
        self.assertEqual(closed.ticket,"OLD-I")
        self.assertEqual(self.port.open_positions["internal"],())
        self.assertEqual(self.port.open_positions["external"],())
        self.assertEqual(
            self.journal.entry(self.flow.last_key)["status"],
            "user_close_confirmed",
        )

    def test_ui_routes_test_selection_only_from_fill_both(self):
        fake = SimpleNamespace(
            test_mode_checkbox=SimpleNamespace(isChecked=lambda: True),
            test_scenario_checkboxes={
                "reentry:internal": SimpleNamespace(isChecked=lambda: True),
            },
            test_asset_checkboxes={},
        )
        self.assertEqual(
            TradingHelperApp._selected_test_action(
                fake, ("internal", "external")
            ),
            "reentry:internal",
        )
        self.assertIsNone(
            TradingHelperApp._selected_test_symbol(fake, ("internal", "external"))
        )
        asset_fake = SimpleNamespace(
            test_mode_checkbox=SimpleNamespace(isChecked=lambda: True),
            test_scenario_checkboxes={},
            test_asset_checkboxes={
                "BTCUSD": SimpleNamespace(isChecked=lambda: True),
            },
        )
        self.assertEqual(
            TradingHelperApp._selected_test_action(
                asset_fake, ("internal", "external")
            ),
            "weekend:BTCUSD",
        )
        self.assertEqual(
            TradingHelperApp._selected_test_symbol(
                asset_fake, ("internal", "external")
            ),
            "BTCUSD",
        )
        self.assertEqual(
            TradingHelperApp._selected_test_action(fake, ("internal",)), ""
        )

    def test_test_checkbox_group_allows_only_one_action_but_can_be_empty(self):
        from PySide6.QtWidgets import QApplication, QCheckBox
        app = QApplication.instance() or QApplication([])
        first, second = QCheckBox(), QCheckBox()
        group = {"first": first, "second": second}
        first.toggled.connect(
            lambda checked: TradingHelperApp._exclusive_optional_checkbox(
                group, first, checked
            )
        )
        second.toggled.connect(
            lambda checked: TradingHelperApp._exclusive_optional_checkbox(
                group, second, checked
            )
        )
        first.setChecked(True)
        second.setChecked(True)
        self.assertFalse(first.isChecked())
        self.assertTrue(second.isChecked())
        second.setChecked(False)
        self.assertFalse(first.isChecked())
        self.assertFalse(second.isChecked())

    def test_weekend_override_scope_is_temporary(self):
        import os
        os.environ.pop("TRADING_HELPER_TEST_SYMBOL_OVERRIDE", None)
        os.environ.pop("TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK", None)
        with test_symbol_scope("BTCUSD"):
            self.assertEqual(
                os.environ["TRADING_HELPER_TEST_SYMBOL_OVERRIDE"], "BTCUSD"
            )
            self.assertEqual(
                os.environ["TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK"], "1"
            )
        self.assertNotIn("TRADING_HELPER_TEST_SYMBOL_OVERRIDE", os.environ)
        self.assertNotIn("TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK", os.environ)

    def test_calibrated_close_clicks_once_and_confirms_ticket_disappeared(self):
        position=side_position("internal")
        port=CloseBrokerPort((position,))
        port.close_position_once(position,"internal")
        self.assertEqual(len(port.automation.windows.clicks),1)
        self.assertEqual(port.positions,())

    def test_calibrated_close_refuses_multiple_positions_before_click(self):
        position=side_position("internal")
        duplicate=Position(
            "OTHER",position.account_id,position.platform,position.symbol,
            position.direction,position.volume,position.entry_price,
            position.sl,position.tp,
        )
        port=CloseBrokerPort((position,duplicate))
        with self.assertRaisesRegex(AutomationError,"唯一且相同"):
            port.close_position_once(position,"internal")
        self.assertEqual(port.automation.windows.clicks,[])


if __name__ == "__main__":
    unittest.main()

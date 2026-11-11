"""Offline-only full auto-entry flow: every broker interface is a mock."""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from dataclasses import replace
from unittest.mock import MagicMock, patch
from trading_helper.auto_entry import (
    AutoEntryWorkflow, AutoEntryJournal, DemoAccount,
    DuplicateEntryDecisionRequired,
    Position, RecoveryRequired,
)
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError
from trading_helper.models import TradeInstruction, SideValues


def instruction():
    return TradeInstruction(
        source_row=1,status="",symbol="XAUUSD",sheet_direction="BUY",
        internal=SideValues(D("0.4"),D("10"),D("20")),
        external=SideValues(D("0.2"),D("10"),D("20")),
        estimated_price=D("4100"),point_size=D("0.01"),
        price_digits=2,
    )

class FakeBrokerPort:
    def __init__(self, mt5_internal=False):
        self.events=[]
        self.accounts={
            "internal":DemoAccount("MT5" if mt5_internal else "cTrader",
                                   "111111","broker-Demo",True,True),
            "external":DemoAccount("cTrader" if mt5_internal else "MT5",
                                   "222222","broker-Demo",True,True),
        }
        self.open_positions={"internal":(),"external":()}
        self.bad_form=False
        self.fail_submit=None
        self.fail_confirm=None
        self.fail_amend=False
        self.fail_verify_protect=False

    def inspect_account(self,platform,role):
        self.events.append(("account",role))
        return self.accounts[role]
    def snapshot_positions(self,platform,role):
        self.events.append(("baseline",role))
        return self.open_positions[role]
    def verify_order_form(self,platform,role,direction,lot):
        self.events.append(("preflight",role))
        if self.bad_form:raise AutomationError("bad form")
    def submit_once(
        self,platform,role,direction,lot,key,submit_deadline=None
    ):
        if submit_deadline is not None:
            import time
            if time.monotonic()>=submit_deadline:
                raise AutomationError(
                    "15 秒補進時限已過；已在送單前停止。"
                )
        # Model the production adapter's mandatory fresh verification inside
        # the one-click submit call. Workflow code must not repeat this scan.
        self.verify_order_form(platform,role,direction,lot)
        self.events.append(("submit",role))
        if self.fail_submit==role:
            raise AutomationError("broker timeout after possible fill")
    def confirm_new_position(self,platform,role,before,direction,volume,account_id):
        self.events.append(("confirm",role))
        if self.fail_confirm==role:
            raise AutomationError("position missing after order click")
        return Position(
            ticket="T-"+role,account_id=account_id,platform=platform,
            symbol="XAUUSD",direction=direction,volume=volume,
            entry_price=D("4101.45") if role=="internal" else D("4101.65")
        )
    def verify_internal_protection(self,pos,sl_points,tp_points):
        self.events.append(("protected",pos.ticket))
        if self.fail_verify_protect:raise AutomationError("internal SL absent")
    def set_position_sl_tp(self,pos,sl,tp):
        self.events.append(("modify",pos.ticket,sl,tp))
        if self.fail_amend:raise AutomationError("modify timed out")
    def verify_position_sl_tp(self,pos,sl,tp):
        self.events.append(("verify_sl_tp",pos.ticket,sl,tp))
    def draw_tradingview(self,*args):
        self.events.append(("tv",))

class AutoEntryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=AutoEntryJournal(Path(self.temp.name)/"journal.json")
        self.port=FakeBrokerPort()
        self.logs=[]
        self.flow=AutoEntryWorkflow(
            self.port,self.journal,lambda:None,self.logs.append
        )
        self.item=instruction()
    def tearDown(self):
        self.temp.cleanup()
    def run_case(self,sync=True,draw=True):
        return self.flow.run(
            self.item,"cTrader","MT5","A","https://docs.google.com/a",
            sync_sl_tp=sync,draw_tv=draw
        )
    def test_completed_two_side_hedge_and_sync_and_tv_ordered(self):
        a,b=self.run_case()
        self.assertEqual((a.ticket,b.ticket),("T-internal","T-external"))
        ev=[x[0] for x in self.port.events]
        self.assertLess(ev.index("protected"),ev.index("submit",ev.index("submit")+1))
        self.assertLess(ev.index("verify_sl_tp"),ev.index("tv"))
        self.assertEqual(self.port.events[-1],("tv",))
        self.assertEqual(len([x for x in ev if x=="submit"]),2)

    def test_duplicate_journal_is_detected_by_read_only_prefill_check(self):
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        key=self.flow.fingerprint(
            "A","https://docs.google.com/a",accounts,self.item
        )
        self.journal.record(key,"both_confirmed","T-internal/T-external")
        with self.assertRaises(DuplicateEntryDecisionRequired) as caught:
            self.flow.preflight_duplicate_entry(
                self.item,"cTrader","MT5","A","https://docs.google.com/a"
            )
        self.assertEqual(caught.exception.key,key)
        self.assertEqual(
            [event for event in self.port.events if event[0]=="account"],
            [("account","external"),("account","internal")],
        )
        self.assertFalse(any(event[0] in ("baseline","submit")
                             for event in self.port.events))

    def test_prechecked_accounts_are_reused_for_key_without_second_scan(self):
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        result=self.flow.run(
            self.item,"cTrader","MT5","A","https://docs.google.com/a",
            sync_sl_tp=False,draw_tv=False,prechecked_accounts=accounts,
        )
        self.assertEqual(len(result),2)
        self.assertFalse(any(event[0]=="account" for event in self.port.events))
        self.assertTrue(any("帳戶確認 0ms" in line for line in self.logs))
    def test_pre_submit_check_favors_external_form_before_internal(self):
        self.run_case(sync=False,draw=False)
        preflight=[ev[1] for ev in self.port.events
                   if ev[0]=="preflight"]
        # First inspection uses the field last filled (external).
        self.assertEqual(preflight[:2],["external","internal"])
        self.assertEqual(preflight.count("internal"),2)
        self.assertEqual(preflight.count("external"),2)
        self.assertEqual(
            [ev[1] for ev in self.port.events if ev[0]=="submit"],
            ["internal","external"]
        )

    def test_optional_steps_off_submit_but_no_sync_no_tv(self):
        self.run_case(sync=False,draw=False)
        ev=[x[0] for x in self.port.events]
        self.assertEqual(ev.count("submit"),2)
        self.assertNotIn("modify",ev)
        self.assertNotIn("tv",ev)

    def test_user_approved_reentry_gets_a_distinct_journal_attempt(self):
        first=self.flow.run(
            self.item,"cTrader","MT5","A","https://docs.google.com/a",
            sync_sl_tp=True,draw_tv=False,
        )
        first_key=self.flow.last_key
        self.assertEqual(len(first),2)
        second=self.flow.run(
            self.item,"cTrader","MT5","A","https://docs.google.com/a",
            sync_sl_tp=True,draw_tv=False,
            authorized_reentry_id="user-confirmed-2",
        )
        second_key=self.flow.last_key
        self.assertEqual(len(second),2)
        self.assertNotEqual(first_key,second_key)
        self.assertEqual(
            [event[1] for event in self.port.events if event[0]=="submit"],
            ["internal","external","internal","external"],
        )
    def test_mt5_internal_protected_with_executed_not_estimated_price(self):
        self.port=FakeBrokerPort(mt5_internal=True)
        self.flow=AutoEntryWorkflow(self.port,self.journal,lambda:None,self.logs.append)
        a,b=self.flow.run(self.item,"MT5","cTrader","A","https://docs.google.com/a",
                          sync_sl_tp=True,draw_tv=False)
        actions=self.port.events
        modifying=[x for x in actions if x[0]=="modify"]
        self.assertEqual(modifying[0][1],"T-internal")
        sl,tp=self.item.estimated_prices("BUY",self.item.internal,a.entry_price)
        self.assertEqual(modifying[0][2:],(sl,tp))
        self.assertLess(actions.index(modifying[0]),
                        actions.index(("submit","external")))
    def test_same_account_prevents_any_submission(self):
        self.port.accounts["external"]=replace(
            self.port.accounts["external"],platform="MT5",
            account_id="111111",server="broker-Demo"
        )
        # Use both MT5 to really match the same full account fingerprint.
        self.port.accounts["internal"]=replace(
            self.port.accounts["internal"],platform="MT5"
        )
        with self.assertRaisesRegex(AutomationError,"同一交易帳戶"):
            self.flow.run(self.item,"MT5","MT5","A","url",
                          sync_sl_tp=False,draw_tv=False)
        self.assertNotIn(("submit","internal"),self.port.events)
    def test_verified_live_accounts_can_run_normal_paired_entry(self):
        self.port.accounts["internal"]=replace(
            self.port.accounts["internal"],server="broker-Live",is_demo=False
        )
        self.port.accounts["external"]=replace(
            self.port.accounts["external"],server="other-Live",is_demo=False
        )
        self.run_case(sync=False,draw=False)
        self.assertEqual(
            [event[1] for event in self.port.events if event[0]=="submit"],
            ["internal","external"],
        )

    def test_unverified_account_stops_before_any_submission(self):
        self.port.accounts["internal"]=replace(
            self.port.accounts["internal"],is_demo=False,verified=False,
            server="broker-Live",
        )
        with self.assertRaisesRegex(AutomationError,"帳戶身分"):
            self.run_case(sync=False,draw=False)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))

    def test_complete_fault_injection_scenarios_remain_demo_only(self):
        self.port.accounts["internal"]=replace(
            self.port.accounts["internal"],server="broker-Live",is_demo=False
        )
        with self.assertRaisesRegex(RecoveryRequired,"只允許已核對的 Demo"):
            self.flow.run_test_scenario(
                self.item,"cTrader","MT5","A","url",
                scenario="weekend:BTCUSD",test_run_id="live-not-allowed",
            )
        self.assertFalse(any(event[0]=="submit" for event in self.port.events))
    def test_existing_positions_stops(self):
        self.port.open_positions["external"]=(Position(
            "OLD","222222","MT5","XAUUSD","SELL",D("0.2"),D("4100")
        ),)
        with self.assertRaisesRegex(AutomationError,"帳戶存在持倉"):
            self.run_case()
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
    def test_direction_or_lot_mismatch_after_submit_is_uncertain(self):
        original=self.port.confirm_new_position
        def broken(*args):
            p=original(*args)
            return replace(p,volume=D("99"))
        self.port.confirm_new_position=broken
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        self.assertEqual([x[1] for x in self.port.events if x[0]=="submit"],
                         ["internal"])
        with self.assertRaisesRegex(RecoveryRequired,"重複下單"):
            self.run_case()
    def test_internal_protection_failure_never_sends_external(self):
        self.port.fail_verify_protect=True
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        self.assertNotIn(("submit","external"),self.port.events)
    def test_external_submission_timeout_never_retries_or_draws(self):
        self.port.fail_submit="external"
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        self.assertEqual([x for x in self.port.events if x[0]=="submit"],
                         [("submit","internal"),("submit","external")])
        self.assertFalse(any(x[0]=="tv" for x in self.port.events))
    def test_failed_fill_confirmation_logs_its_duration_phase(self):
        self.port.fail_confirm="internal"
        with self.assertRaises(RecoveryRequired):
            self.run_case(sync=False,draw=False)
        self.assertTrue(any(
            "internal cTrader 進場分段計時" in line
            and "成交確認" in line
            for line in self.logs
        ))
    def test_fast_pair_receipt_retains_the_unconfirmed_leg_read_reason(self):
        self.port.fail_confirm="internal"
        with self.assertRaises(RecoveryRequired) as caught:
            self.flow.run(
                self.item,"cTrader","MT5","A","https://docs.google.com/a",
                sync_sl_tp=False,draw_tv=False,fast_pair=True,
            )
        self.assertIn("場內（cTrader）",str(caught.exception))
        self.assertIn("position missing after order click",str(caught.exception))
        self.assertIn("不能推定拒單",str(caught.exception))
    def test_failed_preflight_never_clicks(self):
        self.port.bad_form=True
        with self.assertRaises(AutomationError):
            self.run_case()
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
    def test_journal_fails_closed_if_unreadable(self):
        self.journal.path.write_text("{broken",encoding="utf-8")
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
    def test_draw_requires_sync(self):
        with self.assertRaises(AutomationError):
            self.run_case(sync=False,draw=True)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
    def test_safety_adapter_never_sends_without_real_demo_ticket_reader(self):
        adapter=DemoUiBrokerPort(MagicMock(),lambda _:None)
        with self.assertRaises(AutomationError):
            adapter.submit_once("cTrader","internal","BUY",D("0.1"),"abc")
    def test_schema_sensitivity_for_trade_fingerprint(self):
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        k1=self.flow.fingerprint("A","sheet",accounts,self.item)
        k2=self.flow.fingerprint("B","sheet",accounts,self.item)
        k3=self.flow.fingerprint("A","sheet",accounts,
                replace(self.item,internal=replace(self.item.internal,lot=D("2"))))
        self.assertNotEqual(k1,k2)
        self.assertNotEqual(k1,k3)

if __name__=="__main__":
    unittest.main()

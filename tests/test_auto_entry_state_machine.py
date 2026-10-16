"""Offline-only full auto-entry flow: every broker interface is a mock."""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from dataclasses import replace
from unittest.mock import MagicMock, patch
from trading_helper.auto_entry import (
    AutoEntryWorkflow, AutoEntryJournal, DemoAccount,
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
    def submit_once(self,platform,role,direction,lot,key):
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
    def test_real_or_unverified_account_stops(self):
        self.port.accounts["internal"]=replace(
            self.port.accounts["internal"],is_demo=False
        )
        with self.assertRaisesRegex(AutomationError,"Demo"):
            self.run_case()
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
    def test_existing_positions_stops(self):
        self.port.open_positions["external"]=(Position(
            "OLD","222222","MT5","XAUUSD","SELL",D("0.2"),D("4100")
        ),)
        with self.assertRaisesRegex(AutomationError,"已存在持倉"):
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

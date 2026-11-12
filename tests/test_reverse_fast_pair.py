"""Offline-only MT5 internal / cTrader external rapid dual workflow tests."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from trading_helper.auto_entry import AutoEntryWorkflow, AutoEntryJournal, RecoveryRequired
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError
from test_auto_entry_state_machine import FakeBrokerPort, instruction
from test_demo_auto_entry_preflight import config, point
from types import SimpleNamespace

class ReverseFastPairTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port=FakeBrokerPort(mt5_internal=True)
        self.journal=AutoEntryJournal(Path(self.tmp.name)/"journal.json")
        self.logs=[]
        self.flow=AutoEntryWorkflow(
            self.port,self.journal,lambda:None,self.logs.append
        )
        self.item=instruction()

    def go(self, sync=True, draw=False):
        return self.flow.run(
            self.item,"MT5","cTrader","reverse","test-sheet",
            fast_pair=True,sync_sl_tp=sync,draw_tv=draw,
        )

    def test_reverse_both_orders_sent_before_fill_poll_and_amend(self):
        result=self.go(sync=True)
        event=self.port.events
        sent=[i for i,e in enumerate(event) if e[0]=="submit"]
        confirmed=[i for i,e in enumerate(event) if e[0]=="confirm"]
        self.assertEqual([event[i][1] for i in sent],["internal","external"])
        self.assertLess(max(sent),min(confirmed))
        amended=[(i,e) for i,e in enumerate(event) if e[0]=="modify"]
        self.assertEqual([x[1][1] for x in amended],["T-internal","T-external"])
        self.assertGreater(amended[0][0],max(confirmed))
        self.assertLess(amended[0][0],amended[1][0])
        sl_i,tp_i=self.item.estimated_prices(
            "BUY",self.item.internal,result[0].entry_price
        )
        sl_e,tp_e=self.item.estimated_prices(
            "SELL",self.item.external,result[0].entry_price
        )
        self.assertEqual(amended[0][1][2:],(sl_i,tp_i))
        self.assertEqual(amended[1][1][2:],(sl_e,tp_e))
        self.assertEqual(self.journal.status(self.flow.last_key),"complete")
        entry=self.journal.entry(self.flow.last_key)
        self.assertTrue(entry["internal_protected"])
        self.assertTrue(entry["sl_tp_synchronized"])
        self.assertEqual(
            [ev[1] for ev in event if ev[0]=="submit"],
            ["internal","external"],
        )

    def test_reverse_without_external_sync_still_corrects_mt5_internal(self):
        self.go(sync=False)
        updated=[e for e in self.port.events if e[0]=="modify"]
        self.assertEqual(len(updated),1)
        self.assertEqual(updated[0][1],"T-internal")
        self.assertNotIn("sl_tp_synchronized",
                         self.journal.entry(self.flow.last_key))

    def test_mt5_internal_amend_failure_never_claims_hedge_protected(self):
        self.port.fail_amend=True
        with self.assertRaises(RecoveryRequired):
            self.go()
        self.assertEqual(
            [e[1] for e in self.port.events if e[0]=="submit"],
            ["internal","external"],
        )
        self.assertEqual(self.journal.status(self.flow.last_key),
                         "attention_required")
        self.assertNotIn("internal_protected",
                         self.journal.entry(self.flow.last_key))
        self.assertFalse(any(
            e[0]=="modify" and e[1]=="T-external"
            for e in self.port.events
        ))

    def test_reverse_external_confirmation_unknown_stops_and_never_resends(self):
        self.port.fail_confirm="external"
        with self.assertRaises(RecoveryRequired):
            self.go()
        self.assertEqual(
            [e[1] for e in self.port.events if e[0]=="submit"],
            ["internal","external"],
        )
        self.assertNotIn("internal_protected",
                         self.journal.entry(self.flow.last_key))
        self.assertNotEqual(self.journal.status(self.flow.last_key),"complete")

    def test_reverse_internal_confirmation_unknown_still_checks_external(self):
        self.port.fail_confirm="internal"
        with self.assertRaises(RecoveryRequired):
            self.go()
        seen=[e[1] for e in self.port.events if e[0]=="confirm"]
        self.assertEqual(seen,["internal","external"])
        self.assertEqual(
            [e[1] for e in self.port.events if e[0]=="submit"],
            ["internal","external"],
        )

    def test_local_ticket_role_bookkeeping_works_for_both_brokers(self):
        from decimal import Decimal
        from trading_helper.auto_entry import DemoAccount, Position
        broker=DemoUiBrokerPort(SimpleNamespace(),lambda _:None)
        ct=DemoAccount("cTrader","101","broker-Demo",True,True)
        mt=DemoAccount("MT5","202","broker-Demo",True,True)
        broker._account_binding[("cTrader","external")]=ct
        broker._account_binding[("MT5","internal")]=mt
        for platform,role,account in (
            ("MT5","internal",mt),("cTrader","external",ct)
        ):
            position=Position(
                "SAME-LOCAL-TICKET",account.account_id,platform,
                "XAUUSD","BUY",Decimal("0.1"),Decimal("4000")
            )
            broker.remember_verified_position_role(platform,role,position)
            self.assertEqual(
                broker._ticket_role[(platform,position.ticket)],role
            )
        wrong=Position(
            "WRONG","not-verified","cTrader","XAUUSD",
            "SELL",Decimal("0.1"),Decimal("4000")
        )
        with self.assertRaises(AutomationError):
            broker.remember_verified_position_role(
                "cTrader","external",wrong
            )

    def test_reverse_wrong_demo_identity_prevents_both_clicks(self):
        self.port.accounts["internal"]=replace(
            self.port.accounts["internal"],verified=False
        )
        with self.assertRaises(AutomationError):
            self.go()
        self.assertFalse(any(e[0]=="submit" for e in self.port.events))

    def test_reverse_missing_internal_mt5_modify_calibration_stops_preclick(self):
        from test_demo_auto_entry_preflight import config
        cfg=config()
        cfg["platforms"]["MT5"]["points"].pop("position_modify_confirm")
        automation=SimpleNamespace(
            config=cfg,
            windows=SimpleNamespace(find=MagicMock(return_value="TV")),
        )
        real_preflight=DemoUiBrokerPort(automation,lambda _:None)
        self.port.validate_auto_entry_capabilities=(
            real_preflight.validate_auto_entry_capabilities
        )
        with self.assertRaisesRegex(AutomationError,"position_modify_confirm"):
            self.go()
        self.assertFalse(any(e[0]=="submit" for e in self.port.events))

if __name__=="__main__":
    unittest.main()

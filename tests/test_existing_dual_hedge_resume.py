"""Resuming one previously interrupted two-leg Demo hedge NEVER sends orders."""
import unittest
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from pathlib import Path
from trading_helper.auto_entry import AutoEntryJournal,AutoEntryWorkflow,Position,RecoveryRequired
from test_auto_entry_state_machine import FakeBrokerPort,instruction

class VerifiedExistingPairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port=FakeBrokerPort()
        self.journal=AutoEntryJournal(Path(self.tmp.name)/"journal.json")
        self.flow=AutoEntryWorkflow(self.port,self.journal,lambda:None,lambda s:None)
        self.item=instruction()
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        self.key=self.flow.fingerprint("A","sheet",accounts,self.item)
        self.journal.record(self.key,"attention_required",
                            "MT5 Trade owner-drawn list unreadable")
        self.ack=self.journal.entry(self.key)
        self.token=(self.key,self.ack["status"],self.ack["time"],self.ack["details"])
        def pos(role):
            account=self.port.accounts[role]
            direction=(self.item.internal_direction if role=="internal"
                       else self.item.external_direction)
            amount=self.item.internal.lot if role=="internal" else self.item.external.lot
            return Position(
                "existing-"+role,account.account_id,account.platform,
                "XAUUSD",direction,amount,D("4101.45"),
                D("4090") if direction=="BUY" else D("4120"),
                D("4120") if direction=="BUY" else D("4090")
            )
        self.port.open_positions={"internal":(pos("internal"),),
                                  "external":(pos("external"),)}
    def run_case(self,manual=True):
        return self.flow.run(
            self.item,"cTrader","MT5","A","sheet",
            sync_sl_tp=False,draw_tv=False,
            duplicate_confirmation=self.token,
            manual_reconciliation_confirmed=manual,
        )
    def test_approved_existing_pair_resumes_without_any_submit(self):
        first,second=self.run_case()
        self.assertEqual(first.ticket,"existing-internal")
        self.assertEqual(second.ticket,"existing-external")
        self.assertNotIn("submit",[e[0] for e in self.port.events])
        current=self.journal.entry(self.key)
        self.assertEqual(current["status"],"complete")
        self.assertEqual(current["confirmed_legs"],{
            "internal":"existing-internal","external":"existing-external"
        })
        self.assertEqual(current["history"][-1]["status"],"attention_required")
    def test_requires_explicit_manual_history_review(self):
        from trading_helper.auto_entry import DuplicateEntryDecisionRequired
        with self.assertRaises(DuplicateEntryDecisionRequired):
            self.run_case(manual=False)
        self.assertNotIn("submit",[e[0] for e in self.port.events])
    def test_missing_side_never_fabricates_or_sends(self):
        self.port.open_positions["external"]=()
        with self.assertRaisesRegex(RecoveryRequired,"唯一"):
            self.run_case()
        self.assertNotIn("submit",[e[0] for e in self.port.events])
    def test_bad_volume_prevents_resume(self):
        old=self.port.open_positions["external"][0]
        from dataclasses import replace
        self.port.open_positions["external"]=(replace(old,volume=D("9")),)
        with self.assertRaisesRegex(RecoveryRequired,"不一致"):
            self.run_case()
        self.assertNotIn("submit",[e[0] for e in self.port.events])
    def test_unprotected_existing_external_never_marked_done(self):
        from dataclasses import replace
        old=self.port.open_positions["external"][0]
        self.port.open_positions["external"]=(replace(old,sl=None),)
        with self.assertRaisesRegex(RecoveryRequired,"SL/TP"):
            self.run_case()
        self.assertNotIn("submit",[e[0] for e in self.port.events])

if __name__=="__main__":unittest.main()

"""Safe retry consent: synthetic broker only, never real orders."""
import unittest
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from pathlib import Path
from trading_helper.auto_entry import (
    AutoEntryJournal, AutoEntryWorkflow, DuplicateEntryDecisionRequired,
    RecoveryRequired,
)
from test_auto_entry_state_machine import FakeBrokerPort, instruction


class DuplicateConsentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal=AutoEntryJournal(Path(self.tmp.name)/"journal.json")
        self.port=FakeBrokerPort()
        self.flow=AutoEntryWorkflow(self.port,self.journal,lambda:None,lambda _:None)
        self.item=instruction()
        self.accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        self.key=self.flow.fingerprint("A","sheet",self.accounts,self.item)

    def run_flow(self, consent=None):
        kw={"duplicate_confirmation":consent} if consent is not None else {}
        return self.flow.run(
            self.item,"cTrader","MT5","A","sheet",
            sync_sl_tp=False,draw_tv=False,**kw,
        )

    def token(self, entry):
        return (
            self.key,entry["status"],
            str(entry.get("time","")),str(entry.get("details","")),
        )

    def test_first_success_marks_two_validated_tickets(self):
        self.run_flow()
        entry=self.journal.entry(self.key)
        self.assertEqual(entry["status"],"complete")
        self.assertEqual(entry["confirmed_both"],"T-internal/T-external")
        self.assertEqual(len([x for x in self.port.events if x[0]=="submit"]),2)

    def test_duplicate_completed_requires_consent_and_empty_positions(self):
        self.run_flow()
        self.port.events.clear()
        entry=self.journal.entry(self.key)
        with self.assertRaises(DuplicateEntryDecisionRequired) as cm:
            self.run_flow()
        self.assertTrue(cm.exception.retryable)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
        self.port.events.clear()
        self.run_flow(self.token(entry))
        self.assertEqual(
            [x[1] for x in self.port.events if x[0]=="submit"],
            ["internal","external"],
        )
        after=self.journal.entry(self.key)
        self.assertEqual(after["status"],"complete")
        self.assertEqual(after["history"][-1]["status"],"complete")

    def test_adjust_values_does_not_grant_approval(self):
        self.journal.record(self.key,"complete","two confirmed")
        with self.assertRaises(DuplicateEntryDecisionRequired):
            self.run_flow()
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
        self.assertEqual(self.journal.status(self.key),"complete")

    def test_known_preclick_failure_requires_consent(self):
        self.journal.record(
            self.key,"attention_required",
            "cTrader 找不到唯一 Place order 按鈕。"
        )
        with self.assertRaises(DuplicateEntryDecisionRequired) as cm:
            self.run_flow()
        self.assertTrue(cm.exception.retryable)
        self.run_flow(self.token(cm.exception.entry))
        self.assertEqual(self.journal.status(self.key),"complete")

    def test_unknown_send_result_is_not_rerunnable_even_with_yes(self):
        self.journal.record(
            self.key,"attention_required",
            "broker timeout after possible fill"
        )
        entry=self.journal.entry(self.key)
        with self.assertRaises(DuplicateEntryDecisionRequired) as cm:
            self.run_flow(self.token(entry))
        self.assertFalse(cm.exception.retryable)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))

    def test_current_existing_position_blocks_explicit_retry(self):
        self.journal.record(self.key,"complete","both filled")
        prior=self.journal.entry(self.key)
        self.port.open_positions["external"]=(
            self.port.confirm_new_position(
                "MT5","external",(),"SELL",D("0.2"),"222222"
            ),
        )
        with self.assertRaisesRegex(Exception,"已存在持倉"):
            self.run_flow(self.token(prior))
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
        self.assertEqual(self.journal.entry(self.key),prior)

    def test_changed_record_invalidates_approval(self):
        self.journal.record(self.key,"complete","older transaction")
        previous=self.token(self.journal.entry(self.key))
        self.journal.record(self.key,"attention_required","different error")
        with self.assertRaises(DuplicateEntryDecisionRequired):
            self.run_flow(previous)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))

    def test_unknown_status_does_not_offer_unsafe_continue(self):
        self.journal.record(self.key,"sending_internal","unknown")
        with self.assertRaises(DuplicateEntryDecisionRequired) as cm:
            self.run_flow()
        self.assertFalse(cm.exception.retryable)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))

    def test_first_leg_protection_failure_does_not_record_both(self):
        self.port.fail_verify_protect=True
        with self.assertRaises(RecoveryRequired):
            self.run_flow()
        entry=self.journal.entry(self.key)
        self.assertEqual(entry["status"],"attention_required")
        self.assertNotIn("confirmed_both",entry)

    def test_external_confirm_failure_does_not_record_both(self):
        self.port.fail_confirm="external"
        with self.assertRaises(RecoveryRequired):
            self.run_flow()
        self.assertNotIn("confirmed_both",self.journal.entry(self.key))


if __name__=="__main__":
    unittest.main()

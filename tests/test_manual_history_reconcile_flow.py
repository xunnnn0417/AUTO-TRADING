"""Offline tests for review-and-retry after uncertain prior Demo order click."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import unittest
from decimal import Decimal
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import MagicMock,patch
from PySide6.QtWidgets import QApplication

from trading_helper.auto_entry import (
    AutoEntryWorkflow,AutoEntryJournal,DuplicateEntryDecisionRequired,
)
from trading_helper.gui import TradingHelperApp
from test_auto_entry_state_machine import FakeBrokerPort,instruction


class UncertainRetryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal=AutoEntryJournal(Path(self.temp.name)/"journal.json")
        self.port=FakeBrokerPort()
        self.flow=AutoEntryWorkflow(
            self.port,self.journal,lambda:None,lambda m:None
        )
        self.item=instruction()
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        self.key=self.flow.fingerprint("A","url",accounts,self.item)
        self.journal.record(
            self.key,"attention_required",
            "Demo 持倉數值不可辨識：'0.74 Lots'"
        )
    def run_case(self, approved=None,manual=False):
        return self.flow.run(
            self.item,"cTrader","MT5","A","url",
            sync_sl_tp=False,draw_tv=False,
            duplicate_confirmation=approved,
            manual_reconciliation_confirmed=manual,
        )
    def approval(self):
        e=self.journal.entry(self.key)
        return (
            self.key,e["status"],
            str(e.get("time","")),str(e.get("details","")),
        )

    def test_exact_current_lots_error_presents_manual_review_choice(self):
        with self.assertRaises(DuplicateEntryDecisionRequired) as caught:
            self.run_case()
        self.assertFalse(caught.exception.retryable)
        self.assertTrue(caught.exception.manual_review_possible)
        self.assertFalse(any(evt[0]=="submit" for evt in self.port.events))

    def test_user_choice_without_history_review_never_sends(self):
        with self.assertRaises(DuplicateEntryDecisionRequired):
            self.run_case(self.approval())
        self.assertFalse(any(evt[0]=="submit" for evt in self.port.events))

    def test_manual_history_review_allows_new_attempt_after_empty_demo_checks(self):
        self.run_case(self.approval(),manual=True)
        events=self.port.events
        self.assertEqual(
            [e[1] for e in events if e[0]=="submit"],
            ["internal","external"]
        )
        self.assertLess(
            events.index(("baseline","internal")),
            events.index(("submit","internal"))
        )
        entry=self.journal.entry(self.key)
        self.assertEqual(entry["status"],"complete")
        self.assertTrue(entry["history"][-1]["details"].endswith("'0.74 Lots'"))
        self.assertTrue(entry["history"])
        self.assertTrue(entry["manual_reconciliation_confirmed"])

    def test_existing_position_blocks_even_with_reviewed_history(self):
        self.port.open_positions["internal"]=(
            self.port.confirm_new_position(
                "cTrader","internal",(),"BUY",Decimal(".4"),"111111"
            ),
        )
        self.port.events.clear()
        with self.assertRaisesRegex(Exception,"已存在持倉"):
            self.run_case(self.approval(),manual=True)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
        self.assertEqual(self.journal.entry(self.key)["status"],"attention_required")

    def test_changed_record_invalidates_prior_manual_consent(self):
        old=self.approval()
        self.journal.record(self.key,"attention_required","another failure")
        with self.assertRaises(DuplicateEntryDecisionRequired):
            self.run_case(old,manual=True)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))

    def test_sending_marker_needs_manual_history_review(self):
        self.journal.record(self.key,"sending_internal","not sure if clicked")
        with self.assertRaises(DuplicateEntryDecisionRequired) as caught:
            self.run_case()
        self.assertFalse(caught.exception.retryable)
        self.assertTrue(caught.exception.manual_review_possible)

class ManualHistoryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.item=object()
        self.ui=MagicMock()
        self.ui.profiles.active_name="A"
        self.ui.store.data={"sheet":{"spreadsheet_url":"sheet"}}
        self.ui.instruction=self.item
        self.ui.internal_platform.currentText.return_value="cTrader"
        self.ui.external_platform.currentText.return_value="MT5"
        self.data={
            "key":"key","retryable":False,"manual_review_possible":True,
            "entry":{
                "status":"attention_required",
                "time":"2026-10-16 06:02:55",
                "details":"Demo 持倉數值不可辨識：'0.74 Lots'",
            },
            "request":{
                "profile_name":"A","sheet_url":"sheet",
                "internal_platform":"cTrader","external_platform":"MT5",
                "item":self.item,"sync_sl_tp":False,
                "draw_tv":False,"draw_internal":False,
            },
        }

    def run_dialog(self,choice,checked):
        d=MagicMock()
        adjust=MagicMock()
        proceed=MagicMock()
        d.addButton.side_effect=[adjust,proceed]
        d.clickedButton.return_value=proceed if choice else adjust
        cb=MagicMock()
        cb.isChecked.return_value=checked
        with patch("trading_helper.gui.QMessageBox") as mb, patch(
            "trading_helper.gui.QCheckBox",return_value=cb
        ):
            mb.return_value=d
            mb.RejectRole=0
            mb.AcceptRole=1
            mb.Question=4
            TradingHelperApp._show_duplicate_entry_decision(self.ui,self.data)
            warnings=mb.warning.call_count
        return d,cb,proceed,warnings

    def test_shows_decision_with_explicit_history_check(self):
        d,cb,proceed,_=self.run_dialog(False,False)
        d.setCheckBox.assert_called_once_with(cb)
        proceed.setEnabled.assert_called_once_with(False)
        self.ui._start.assert_not_called()

    def test_cannot_continue_with_unchecked_histories(self):
        _,_,_,warnings=self.run_dialog(True,False)
        self.assertEqual(warnings,1)
        self.ui._start.assert_not_called()

    def test_explicit_manual_acknowledgement_starts_new_safety_checks(self):
        _,_,_,warnings=self.run_dialog(True,True)
        self.assertEqual(warnings,0)
        name,task=self.ui._start.call_args.args
        self.assertEqual(name,"重新確認進場")
        task()
        kw=self.ui._auto_entry_after_fill_both_pending.call_args.kwargs
        self.assertTrue(kw["manual_reconciliation_confirmed"])
        self.assertEqual(
            kw["duplicate_confirmation"],
            ("key","attention_required","2026-10-16 06:02:55",
             "Demo 持倉數值不可辨識：'0.74 Lots'")
        )

    def test_adjust_values_always_available(self):
        self.run_dialog(False,False)
        self.ui._start.assert_not_called()


if __name__=="__main__":
    unittest.main()

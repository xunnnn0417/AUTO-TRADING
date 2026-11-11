"""All P0 rescue tests are FAKE-broker only; no live connections or orders."""
import time
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch,MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication,QPushButton,QMessageBox
from trading_helper.auto_entry import AutoEntryWorkflow,AutoEntryJournal,RecoveryRequired
from trading_helper.recovery_policy import TerminalRejectionProof,validate_terminal_rejection
from trading_helper.windows import AutomationError
from trading_helper.entry_status_report import build_entry_status_report
from trading_helper.gui import TradingHelperApp
from test_auto_entry_state_machine import FakeBrokerPort,instruction

class CertifiedRejectionBroker(FakeBrokerPort):
    """Emulates authoritative terminal-order history, not a GUI assertion."""
    def __init__(self, reject_role="external", reliable=True):
        super().__init__()
        self.reject_role=reject_role
        self.reliable=reliable
        self.submit_counts={"internal":0,"external":0}
        self.cert_override=None
    def submit_once(
        self,platform,role,direction,lot,key,submit_deadline=None
    ):
        self.submit_counts[role]+=1
        return super().submit_once(
            platform,role,direction,lot,key,submit_deadline=submit_deadline
        )
    def confirm_new_position(self,platform,role,before,direction,volume,account_id):
        if role==self.reject_role and self.submit_counts[role]==1:
            self.events.append(("confirm",role))
            raise AutomationError("terminal rejection readback")
        result=super().confirm_new_position(platform,role,before,direction,volume,account_id)
        self.open_positions[role]=(result,)
        return result
    def prove_terminal_rejection(self,platform,role,key,account_id,symbol):
        self.events.append(("proof",role))
        if role!=self.reject_role or not self.reliable:
            return None
        proof=TerminalRejectionProof(
            attempt_key=key,platform=platform,role=role,account_id=account_id,
            symbol=symbol,original_broker_order_id="BROKER-REJECT-001",
            terminal_status="REJECTED",original_not_filled=True,
            no_pending_order=True,server_confirmed=True,
            captured_monotonic=time.monotonic()
        )
        return self.cert_override or proof

class RescueP0Test(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
    def make(self,role="external",reliable=True):
        port=CertifiedRejectionBroker(role,reliable)
        journal=AutoEntryJournal(Path(self.tmp.name)/"journal.json")
        flow=AutoEntryWorkflow(port,journal,lambda:None,lambda x:None)
        return port,journal,flow
    def run_entry(self,flow,fast=True,sync=True):
        return flow.run(instruction(),"cTrader","MT5","P0","sheet",
                        fast_pair=fast,sync_sl_tp=sync,draw_tv=False)
    def test_fast_pair_external_terminal_rejection_rescued_once(self):
        port,journal,flow=self.make()
        result=self.run_entry(flow)
        self.assertEqual(len(result),2)
        self.assertEqual(port.submit_counts,{"internal":1,"external":2})
        record=journal.entry(flow.last_key)
        self.assertEqual(record["status"],"complete")
        self.assertEqual(record["rescued_role"],"external")
        self.assertTrue(record["sl_tp_synchronized"])
        report=build_entry_status_report(
            record,success=True,sync_requested=True,tv_requested=False
        )
        self.assertIn("自動補進：場外已確認",report["message"])
    def test_fast_pair_internal_rejected_external_successful_rescues_internal(self):
        port,journal,flow=self.make(role="internal")
        self.run_entry(flow)
        self.assertEqual(port.submit_counts,{"internal":2,"external":1})
        self.assertEqual(journal.entry(flow.last_key)["rescued_role"],"internal")
        self.assertTrue(journal.entry(flow.last_key)["internal_protected"])
    def test_sequential_second_side_rejected_rescues_once(self):
        port,journal,flow=self.make()
        self.run_entry(flow,fast=False)
        self.assertEqual(port.submit_counts,{"internal":1,"external":2})
        self.assertEqual(journal.entry(flow.last_key)["rescued_role"],"external")
    def test_missing_proof_cannot_retry_even_if_other_side_filled(self):
        port,journal,flow=self.make(reliable=False)
        with self.assertRaises(RecoveryRequired):
            self.run_entry(flow)
        self.assertEqual(port.submit_counts,{"internal":1,"external":1})
        self.assertNotIn("rescue_attempted",journal.entry(flow.last_key))
    def test_wrong_order_or_stale_or_pending_proof_blocks_rescue(self):
        for update in (
            {"attempt_key":"different"},
            {"terminal_status":"UNKNOWN"},
            {"original_not_filled":False},
            {"no_pending_order":False},
            {"server_confirmed":False},
            {"captured_monotonic":time.monotonic()-60},
            {"account_id":"wrong"},
            {"original_broker_order_id":""},
        ):
            with self.subTest(update=update):
                with tempfile.TemporaryDirectory() as work:
                    port=CertifiedRejectionBroker()
                    journal=AutoEntryJournal(Path(work)/"j.json")
                    flow=AutoEntryWorkflow(port,journal,lambda:None,lambda _:None)
                    org=TerminalRejectionProof(
                        "placeholder","MT5","external","222222","XAUUSD",
                        "R-01","REJECTED",True,True,True,time.monotonic()
                    )
                    port.cert_override=replace(org,**{
                        "attempt_key":flow.fingerprint("P0","sheet",
                            (port.accounts["internal"],port.accounts["external"]),
                            instruction()), **update
                    })
                    with self.assertRaises(RecoveryRequired):
                        self.run_entry(flow)
                    self.assertEqual(port.submit_counts["external"],1)
    def test_proven_rejected_but_other_position_disappeared_no_retry(self):
        port,journal,flow=self.make()
        original=port.snapshot_positions
        def unreliable(platform,role):
            if role=="internal" and port.submit_counts["external"]>=1:
                return ()
            return original(platform,role)
        port.snapshot_positions=unreliable
        with self.assertRaises(RecoveryRequired):
            self.run_entry(flow)
        self.assertEqual(port.submit_counts["external"],1)
    def test_journal_rescue_gate_survives_restart(self):
        journal=AutoEntryJournal(Path(self.tmp.name)/"j.json")
        journal.record("fingerprint","prepared")
        journal.reserve_verified_rescue("fingerprint","external","R-011")
        other_process=AutoEntryJournal(journal.path)
        with self.assertRaises(RecoveryRequired):
            other_process.reserve_verified_rescue("fingerprint","external","R-011")
        self.assertTrue(other_process.entry("fingerprint")["rescue_attempted"])
    def test_uncertainty_with_one_sided_position_shows_manual_paths(self):
        journal=AutoEntryJournal(Path(self.tmp.name)/"j.json")
        journal.record("a","prepared")
        journal.record("a","filled_internal","ticket=T-01")
        report=build_entry_status_report(
            journal.entry("a"),success=False,sync_requested=True,
            tv_requested=False,internal_platform="cTrader",external_platform="MT5"
        )
        self.assertEqual(report["single_confirmed_role"],"internal")
        self.assertIn("未補進：還不能確認另一邊沒進場",report["message"])

class IncidentDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
    def test_incident_buttons_dispatch_the_user_selected_action(self):
        fake=SimpleNamespace(
            _auto_entry_receipt=None,
            _remember_successful_expected_sl=MagicMock(),
            _start_user_approved_incident_action=MagicMock(),
        )
        report={"title":"結果不明","message":"只確認到場內持倉",
                "single_confirmed_role":"internal",
                "internal_platform":"cTrader","external_platform":"MT5",
                "incident_action_request":{"confirmed_role":"internal",
                                            "confirmed_ticket":"T-01"}}
        TradingHelperApp._show_auto_entry_result(fake,report)
        box=fake._auto_entry_receipt
        try:
            first=box.findChild(QPushButton,"autoEntryIncidentCloseButton")
            second=box.findChild(QPushButton,"autoEntryIncidentReentryButton")
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            first.click()
            second.click()
            self.assertEqual(
                fake._start_user_approved_incident_action.call_args_list[0].args,
                ("close",report["incident_action_request"]),
            )
            self.assertEqual(
                fake._start_user_approved_incident_action.call_args_list[1].args,
                ("reenter",report["incident_action_request"]),
            )
        finally: box.close()

    def test_incident_without_verified_action_data_shows_no_active_buttons(self):
        fake=SimpleNamespace(
            _auto_entry_receipt=None,
            _remember_successful_expected_sl=MagicMock(),
        )
        report={"title":"結果不明","message":"只確認到場內持倉",
                "single_confirmed_role":"internal"}
        TradingHelperApp._show_auto_entry_result(fake,report)
        box=fake._auto_entry_receipt
        try:
            self.assertIsNone(
                box.findChild(QPushButton,"autoEntryIncidentCloseButton")
            )
            self.assertIsNone(
                box.findChild(QPushButton,"autoEntryIncidentReentryButton")
            )
        finally: box.close()

    def test_selected_incident_action_starts_one_locked_recovery_task(self):
        item=instruction()
        fake=SimpleNamespace(
            profiles=SimpleNamespace(active_name="exam"),
            store=SimpleNamespace(data={"sheet":{"spreadsheet_url":"sheet"}}),
            instruction=item,
            internal_platform=SimpleNamespace(currentText=lambda:"cTrader"),
            external_platform=SimpleNamespace(currentText=lambda:"MT5"),
            test_asset_checkboxes={},test_scenario_checkboxes={},
            _auto_entry_receipt=SimpleNamespace(close=MagicMock()),
            _start=MagicMock(),
        )
        request={
            "item":item,"profile_name":"exam","sheet_url":"sheet",
            "internal_platform":"cTrader","external_platform":"MT5",
            "confirmed_role":"internal","confirmed_ticket":"T-1",
            "account_ids":{"internal":"111111","external":"222222"},
            "symbol":item.symbol,
        }
        TradingHelperApp._start_user_approved_incident_action(
            fake,"close",request
        )
        fake._auto_entry_receipt.close.assert_called_once_with()
        self.assertEqual(fake._start.call_args.args[0],"異常後平倉")
        self.assertTrue(fake._start.call_args.kwargs["restore_after"])

    def test_incident_action_is_refused_after_profile_or_platform_changes(self):
        item=instruction()
        fake=SimpleNamespace(
            profiles=SimpleNamespace(active_name="another-profile"),
            store=SimpleNamespace(data={"sheet":{"spreadsheet_url":"sheet"}}),
            instruction=item,
            internal_platform=SimpleNamespace(currentText=lambda:"cTrader"),
            external_platform=SimpleNamespace(currentText=lambda:"MT5"),
            test_asset_checkboxes={},test_scenario_checkboxes={},
        )
        request={
            "item":item,"profile_name":"exam","sheet_url":"sheet",
            "internal_platform":"cTrader","external_platform":"MT5",
            "confirmed_role":"internal","confirmed_ticket":"T-1",
            "account_ids":{"internal":"111111","external":"222222"},
            "symbol":item.symbol,
        }
        with patch("trading_helper.gui.QMessageBox.warning") as warning:
            TradingHelperApp._start_user_approved_incident_action(
                fake,"close",request
            )
        warning.assert_called_once()
    def test_completed_dual_trade_offers_no_unneeded_manual_actions(self):
        fake=SimpleNamespace(
            _auto_entry_receipt=None,
            _remember_successful_expected_sl=MagicMock(),
        )
        TradingHelperApp._show_auto_entry_result(fake,{"title":"完成","message":"OK"})
        try:
            box=fake._auto_entry_receipt
            self.assertIsNone(box.findChild(QPushButton,"autoEntryIncidentCloseButton"))
            self.assertIsNone(box.findChild(QPushButton,"autoEntryIncidentReentryButton"))
        finally:fake._auto_entry_receipt.close()

if __name__=="__main__":unittest.main()

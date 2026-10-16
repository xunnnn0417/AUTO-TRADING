"""Offline receipt tests: no broker UI, no real transactions."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QDialog, QTextBrowser
from trading_helper.entry_status_report import build_entry_status_report
from trading_helper.auto_entry import AutoEntryWorkflow, AutoEntryJournal, RecoveryRequired
from trading_helper.gui import TradingHelperApp
from test_auto_entry_state_machine import FakeBrokerPort, instruction


class ReceiptDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.port = FakeBrokerPort()
        self.journal = AutoEntryJournal(Path(self.temp.name) / "journal.json")
        self.flow = AutoEntryWorkflow(self.port, self.journal, lambda:None, lambda m:None)

    def execute(self, *, sync, fast=True):
        return self.flow.run(
            instruction(), "cTrader", "MT5", "test", "sheet",
            fast_pair=fast, sync_sl_tp=sync, draw_tv=False
        )

    def receipt(self, successful, sync=True, reason=""):
        return build_entry_status_report(
            self.journal.entry(self.flow.last_key),
            success=successful, sync_requested=sync,
            tv_requested=False, reason=reason,
            internal_platform="cTrader", external_platform="MT5",
        )

    def test_two_verified_sides_and_sltp_readback_report_completion(self):
        self.execute(sync=True)
        entry = self.journal.entry(self.flow.last_key)
        self.assertEqual(set(entry.get("confirmed_legs",{})), {"internal","external"})
        self.assertTrue(entry["sl_tp_synchronized"])
        self.assertTrue(entry["internal_protected"])
        report = self.receipt(True)
        self.assertIn("雙邊開倉及 SL／TP 同步完成", report["title"])
        self.assertIn("修改並讀回核對成功", report["message"])
        self.assertIn("自動補開：未執行", report["message"])

    def test_both_filled_but_sync_failed_is_not_marked_complete(self):
        self.port.fail_amend = True
        with self.assertRaises(RecoveryRequired):
            self.execute(sync=True)
        report = self.receipt(False)
        self.assertIn("已有成交確認紀錄", report["message"])
        self.assertIn("場外止盈止損同步：未證實完成", report["message"])
        self.assertNotIn("雙邊開倉及 SL／TP 同步完成", report["title"])

    def test_one_unverified_leg_never_implies_rejection_or_rescue(self):
        self.port.fail_confirm = "external"
        with self.assertRaises(RecoveryRequired):
            self.execute(sync=True)
        report = self.receipt(False, reason="券商回覆不明")
        self.assertIn("場內（cTrader）：已有成交確認紀錄", report["message"])
        self.assertIn("場外（MT5）：尚未證實成交", report["message"])
        self.assertIn("自動補開：未執行", report["message"])
        self.assertIn("券商回覆不明", report["message"])
        self.assertEqual(len([x for x in self.port.events if x[0]=="submit"]),2)

    def test_sequential_first_side_report_survives_second_side_timeout(self):
        self.port.fail_submit = "external"
        with self.assertRaises(RecoveryRequired):
            self.execute(sync=True, fast=False)
        report=self.receipt(False)
        self.assertIn("場內（cTrader）：已有成交確認紀錄",report["message"])
        self.assertIn("場外（MT5）：尚未證實成交",report["message"])
        self.assertIn("自動補開：未執行",report["message"])
        entry=self.journal.entry(self.flow.last_key)
        self.assertIn("internal",entry["confirmed_legs"])
        self.assertNotIn("external",entry["confirmed_legs"])

    def test_sync_off_never_claims_synchronized(self):
        self.execute(sync=False)
        report = self.receipt(True,sync=False)
        self.assertEqual(report["title"],"雙邊開倉已確認")
        self.assertIn("沒有啟用",report["message"])
        self.assertNotIn("同步完成",report["title"])

    def test_old_journal_fields_cannot_falsely_complete_sync(self):
        report=build_entry_status_report(
            {"confirmed_both":"X/Y", "confirmed_legs":{"internal":"X","external":"Y"}},
            success=True,sync_requested=True,tv_requested=False
        )
        self.assertIn("未證實完成",report["message"])
        self.assertNotIn("同步完成",report["title"])


class ReceiptWorkflowSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port=FakeBrokerPort()
        self.signal=MagicMock()
        self.fake=SimpleNamespace(
            emergency=SimpleNamespace(guard=lambda:None),
            profiles=SimpleNamespace(active_name="test-profile"),
            store=SimpleNamespace(data={"sheet":{"spreadsheet_url":"fake-sheet"}}),
            log=MagicMock(),
            automation=MagicMock(),
            signals=SimpleNamespace(auto_entry_result=self.signal),
        )

    def run_gui_entry(self, sync=True):
        with patch("trading_helper.gui.DemoUiBrokerPort",return_value=self.port), \
             patch("trading_helper.gui.APP_DIR",Path(self.tmp.name)):
            return TradingHelperApp._auto_entry_after_fill_both_pending(
                self.fake,"cTrader","MT5",instruction(),
                sync_sl_tp=sync,draw_tv=False,fast_pair=True,
            )

    def test_both_filled_generates_single_success_receipt(self):
        self.run_gui_entry(sync=True)
        self.signal.emit.assert_called_once()
        message=self.signal.emit.call_args.args[0]
        self.assertTrue(message["success"])
        self.assertIn("SL／TP 同步完成",message["title"])

    def test_uncertain_external_emits_one_partial_receipt_and_keeps_error(self):
        self.port.fail_confirm="external"
        with self.assertRaises(RecoveryRequired) as err:
            self.run_gui_entry(sync=True)
        self.assertTrue(getattr(err.exception,"_auto_entry_result_emitted",False))
        self.signal.emit.assert_called_once()
        result=self.signal.emit.call_args.args[0]
        self.assertFalse(result["success"])
        self.assertIn("場內（cTrader）：已有成交確認紀錄",result["message"])
        self.assertIn("場外（MT5）：尚未證實成交",result["message"])

    def test_failed_preflight_does_not_claim_stale_existing_positions(self):
        from dataclasses import replace
        self.port.accounts["external"]=replace(
            self.port.accounts["external"],is_demo=False
        )
        with self.assertRaises(Exception):
            self.run_gui_entry(sync=True)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
        result=self.signal.emit.call_args.args[0]
        self.assertIn("尚未證實成交",result["message"])
        self.assertFalse(result["success"])


class ReceiptWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_result_stays_visible_after_parent_main_window_is_minimized(self):
        fake=SimpleNamespace(_auto_entry_receipt=None)
        receipt={"title":"開倉後續結果需要核對",
                 "message":"場內已確認\n場外尚未確認\n補單未執行"}
        TradingHelperApp._show_auto_entry_result(fake,receipt)
        dialog=fake._auto_entry_receipt
        self.qt.processEvents()
        try:
            self.assertTrue(dialog.isVisible())
            self.assertTrue(bool(dialog.windowFlags() & Qt.WindowStaysOnTopHint))
            self.assertEqual(dialog.objectName(),"autoEntryResultDialog")
            body=dialog.findChild(QTextBrowser,"autoEntryResultBody")
            self.assertIn("補單未執行",body.toPlainText())
            dialog.findChild(QPushButton,"autoEntryResultConfirmButton").click()
            self.assertFalse(dialog.isVisible())
        finally:
            dialog.close()

    def test_result_is_queued_after_operation_minimizes(self):
        fake=SimpleNamespace()
        payload={"title":"雙邊開倉已確認","message":"TEST"}
        with patch("trading_helper.gui.QTimer.singleShot") as q:
            TradingHelperApp._queue_auto_entry_result(fake,payload)
            self.assertEqual(q.call_args.args[0],450)
            self.assertTrue(callable(q.call_args.args[1]))


if __name__ == "__main__":
    unittest.main()
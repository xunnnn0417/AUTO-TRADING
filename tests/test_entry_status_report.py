"""Offline receipt tests: no broker UI, no real transactions."""
import os
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QDialog, QTextBrowser, QLabel
from trading_helper.entry_status_report import (
    build_entry_status_report, summarize_interruption_reason,
)
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
        self.assertIn("場外 SL／TP：已同步", report["message"])

    def test_both_filled_but_sync_failed_is_not_marked_complete(self):
        self.port.fail_amend = True
        with self.assertRaises(RecoveryRequired):
            self.execute(sync=True)
        report = self.receipt(False)
        self.assertIn("場內（cTrader）：已確認進場", report["message"])
        self.assertIn("場外（MT5）：已確認進場", report["message"])
        self.assertEqual(
            report["title"], "雙邊開倉已確認，場外 SL／TP 同步未完成"
        )
        self.assertIn("場外 SL／TP：未完成", report["message"])
        self.assertNotIn("雙邊開倉及 SL／TP 同步完成", report["title"])
        self.assertEqual(
            len([x for x in self.port.events if x[0] == "submit"]), 2
        )
        self.assertFalse(any(x[0] in {"close", "flatten"} for x in self.port.events))

    def test_two_leg_tickets_alone_prove_both_if_combined_marker_was_not_saved(self):
        report = build_entry_status_report(
            {
                "confirmed_legs": {"internal": "I-1", "external": "E-1"},
                "internal_protected": True,
            },
            success=False, sync_requested=True, tv_requested=False,
            reason="同步讀回失敗",
            internal_platform="cTrader", external_platform="MT5",
        )
        self.assertEqual(
            report["title"], "雙邊開倉已確認，場外 SL／TP 同步未完成"
        )
        self.assertIn("場內（cTrader）：已確認進場", report["message"])
        self.assertIn("場外（MT5）：已確認進場", report["message"])

    def test_one_unverified_leg_never_implies_rejection_or_rescue(self):
        self.port.fail_confirm = "external"
        with self.assertRaises(RecoveryRequired):
            self.execute(sync=True)
        report = self.receipt(False, reason="券商回覆不明")
        self.assertIn("場內（cTrader）：已確認進場", report["message"])
        self.assertIn("場外（MT5）：尚未確認進場", report["message"])
        self.assertIn("未補進：還不能確認另一邊沒進場", report["message"])
        self.assertIn("券商回覆不明", report["message"])
        self.assertEqual(len([x for x in self.port.events if x[0]=="submit"]),2)
        self.assertFalse(any(x[0] in {"close", "flatten"} for x in self.port.events))

    def test_sequential_first_side_report_survives_second_side_timeout(self):
        self.port.fail_submit = "external"
        with self.assertRaises(RecoveryRequired):
            self.execute(sync=True, fast=False)
        report=self.receipt(False)
        self.assertIn("場內（cTrader）：已確認進場",report["message"])
        self.assertIn("場外（MT5）：尚未確認進場",report["message"])
        self.assertIn("未補進：還不能確認另一邊沒進場",report["message"])
        entry=self.journal.entry(self.flow.last_key)
        self.assertIn("internal",entry["confirmed_legs"])
        self.assertNotIn("external",entry["confirmed_legs"])

    def test_sync_off_never_claims_synchronized(self):
        self.execute(sync=False)
        report = self.receipt(True,sync=False)
        self.assertEqual(report["title"],"雙邊開倉已確認")
        self.assertNotIn("場外 SL／TP",report["message"])
        self.assertNotIn("同步完成",report["title"])

    def test_old_journal_fields_cannot_falsely_complete_sync(self):
        report=build_entry_status_report(
            {"confirmed_both":"X/Y", "confirmed_legs":{"internal":"X","external":"Y"}},
            success=True,sync_requested=True,tv_requested=False
        )
        self.assertIn("場外 SL／TP：未完成",report["message"])
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

    def test_successful_test_scenario_remembers_expected_sl_for_next_fill(self):
        self.fake._expected_sl_repeat_signature=(
            TradingHelperApp._expected_sl_repeat_signature
        )
        item=replace(
            instruction(),original_sl_points=Decimal("-8.35"),
            expected_sl_points=Decimal("-8.59"),
        )
        positions=(SimpleNamespace(ticket="I-1"),SimpleNamespace(ticket="E-1"))
        with patch("trading_helper.gui.DemoUiBrokerPort",return_value=self.port), \
             patch("trading_helper.gui.APP_DIR",Path(self.tmp.name)), \
             patch.object(AutoEntryWorkflow,"run_test_scenario",return_value={
                 "scenario":"weekend:BTCUSD",
                 "outcome":"weekend_pair_confirmed",
                 "positions":positions,
             }):
            TradingHelperApp._auto_entry_after_fill_both_pending(
                self.fake,"cTrader","MT5",item,sync_sl_tp=True,
                draw_tv=False,fast_pair=False,test_scenario="weekend:BTCUSD",
            )
        self.signal.emit.assert_called_once()
        report=self.signal.emit.call_args.args[0]
        self.assertTrue(report["success"])
        self.assertEqual(
            report["_repeat_expected_sl"]["points"],"-8.59"
        )

    def test_interrupted_test_receipt_keeps_order_id_but_summarizes_details(self):
        initial={
            "internal":SimpleNamespace(ticket="I-01"),
            "external":SimpleNamespace(ticket="E-02"),
        }
        error=RecoveryRequired(
            "單邊平倉測試尚未確認完成；不會再次點擊。原因："
            "MT5 唯讀 API 回報 1 筆仍有效委託（查詢全部商品，這不是已成交持倉）；"
            "為避免重複送單，已停止：\n"
            "- XAUUSD | 市價買入委託 | 單號 TEST-ORDER-01 | 0.1 手 | 價格 0\n"
            "請在 MT5「交易」分頁用單號核對。若畫面找不到相同單號，"
            "請回傳這段明細；代表程式讀值與畫面不一致。"
        )
        error.test_initial_positions=initial
        error.test_closed_roles=("internal",)
        with patch.object(AutoEntryWorkflow,"run_test_scenario",side_effect=error):
            with self.assertRaises(RecoveryRequired):
                TradingHelperApp._auto_entry_after_fill_both_pending(
                    self.fake,"cTrader","MT5",instruction(),
                    sync_sl_tp=True,test_scenario="close:internal",
                )
        self.signal.emit.assert_called_once()
        report=self.signal.emit.call_args.args[0]
        self.assertEqual(report["title"],"測試中斷，請核對持倉")
        self.assertIn("單號 TEST-ORDER-01",report["message"])
        self.assertIn("不是持倉",report["message"])
        self.assertIn("不會重送或自行平倉",report["message"])
        self.assertNotIn("單邊平倉測試尚未確認完成",report["message"])


    def test_pending_mt5_order_summary_keeps_ticket_and_next_step(self):
        summary=summarize_interruption_reason(
            "原因：MT5 唯讀 API 回報 1 筆仍有效委託；已停止：\n"
            "- XAUUSD | 市價買入委託 | 單號 TEST-ORDER-01 | 0.1 手 | 價格 0\n"
            "請在 MT5「交易」分頁用單號核對。完整技術細節。"
        )
        self.assertIn("不是持倉",summary)
        self.assertIn("TEST-ORDER-01",summary)
        self.assertIn("MT5「交易」核對單號",summary)
        self.assertIn("XAUUSD 買入 0.1 手",summary)
        self.assertNotIn("價格 0",summary)
        self.assertNotIn("完整技術細節",summary)

    def test_uncertain_external_emits_one_partial_receipt_and_keeps_error(self):
        self.port.fail_confirm="external"
        with self.assertRaises(RecoveryRequired) as err:
            self.run_gui_entry(sync=True)
        self.assertTrue(getattr(err.exception,"_auto_entry_result_emitted",False))
        self.signal.emit.assert_called_once()
        result=self.signal.emit.call_args.args[0]
        self.assertFalse(result["success"])
        self.assertIn("場內（cTrader）：已確認進場",result["message"])
        self.assertIn("場外（MT5）：尚未確認進場",result["message"])
        request=result["incident_action_request"]
        self.assertEqual(request["confirmed_role"],"internal")
        self.assertEqual(request["confirmed_ticket"],"T-internal")
        self.assertEqual(request["account_ids"],{
            "internal":"111111","external":"222222",
        })

    def test_failed_preflight_does_not_claim_stale_existing_positions(self):
        from dataclasses import replace
        self.port.accounts["external"]=replace(
            self.port.accounts["external"],is_demo=False,verified=False
        )
        with self.assertRaises(Exception):
            self.run_gui_entry(sync=True)
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
        result=self.signal.emit.call_args.args[0]
        self.assertIn("尚未確認進場",result["message"])
        self.assertFalse(result["success"])
        self.assertNotIn("incident_action_request",result)


class ReceiptWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_result_stays_visible_after_parent_main_window_is_minimized(self):
        fake=SimpleNamespace(
            _auto_entry_receipt=None,
            _remember_successful_expected_sl=MagicMock(),
        )
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

    def test_internal_close_receipt_offers_reentry_with_exam_rule_reminder(self):
        fake=SimpleNamespace(
            _auto_entry_receipt=None,
            _remember_successful_expected_sl=MagicMock(),
            _start_user_approved_reentry=MagicMock(),
        )
        request={"internal_platform":"cTrader","external_platform":"MT5"}
        TradingHelperApp._show_auto_entry_result(fake,{
            "title":"場內快平已處理",
            "message":"兩邊均已確認關閉",
            "reentry_request":request,
        })
        dialog=fake._auto_entry_receipt
        try:
            reenter=dialog.findChild(QPushButton,"autoEntryReentryButton")
            reminder=dialog.findChild(QLabel,"autoEntryReentryReminder")
            self.assertIsNotNone(reenter)
            self.assertIn("考試商規則",reminder.text())
            self.assertIn("重新進場",reminder.text())
            reenter.click()
            fake._start_user_approved_reentry.assert_called_once_with(request)
            dialog.findChild(QPushButton,"autoEntryResultConfirmButton").click()
        finally:
            dialog.close()

    def test_approved_reentry_uses_normal_dual_entry_sync_and_selected_lines(self):
        item=instruction()
        fake=SimpleNamespace(
            profiles=SimpleNamespace(active_name="exam"),
            store=SimpleNamespace(data={"sheet":{"spreadsheet_url":"sheet"}}),
            instruction=item,
            _require_instruction=lambda:replace(item),
            auto_fast_pair=SimpleNamespace(isChecked=lambda:True),
            internal_platform=SimpleNamespace(currentText=lambda:"cTrader"),
            external_platform=SimpleNamespace(currentText=lambda:"MT5"),
            _auto_entry_receipt=SimpleNamespace(close=MagicMock()),
            _start=MagicMock(),
            _fill_both_task=MagicMock(),
        )
        request={
            "item":item,"profile_name":"exam","sheet_url":"sheet",
            "internal_platform":"cTrader","external_platform":"MT5",
            "draw_tv":True,"draw_internal":False,
        }
        TradingHelperApp._start_user_approved_reentry(fake,request)
        fake._auto_entry_receipt.close.assert_called_once_with()
        args=fake._start.call_args
        self.assertEqual(args.args[0],"重新進場")
        self.assertFalse(args.kwargs["restore_after"])
        args.args[1]()
        call=fake._fill_both_task.call_args
        self.assertEqual(call.args,("cTrader","MT5",True))
        self.assertTrue(call.kwargs["sync_sl_tp"])
        self.assertTrue(call.kwargs["draw_tv"])
        self.assertFalse(call.kwargs["draw_internal"])
        self.assertTrue(call.kwargs["authorized_reentry_id"])
        self.assertTrue(call.kwargs["fast_pair"])


if __name__ == "__main__":
    unittest.main()

"""GUI consent dialog routes choices without causing broker actions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication, QMessageBox
from trading_helper.gui import TradingHelperApp


class DuplicateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def setUp(self):
        self.item=object()
        self.ui=MagicMock()
        self.ui.profiles.active_name="A"
        self.ui.store.data={"sheet":{"spreadsheet_url":"sheet"}}
        self.ui.instruction=self.item
        self.ui._fill_both_task=MagicMock()
        self.ui._auto_entry_after_fill_both_pending=MagicMock()
        self.ui.internal_platform.currentText.return_value="cTrader"
        self.ui.external_platform.currentText.return_value="MT5"
        self.data={
            "key":"abc",
            "entry":{
                "status":"complete","time":"2025-01-01 05:25:00",
                "details":"T-1/T-2"
            },
            "retryable":True,
            "request":{
                "profile_name":"A", "sheet_url":"sheet",
                "internal_platform":"cTrader",
                "external_platform":"MT5",
                "item":self.item,
                "sync_sl_tp":True,"draw_tv":True,
                "draw_internal":False,
            },
        }

    def decision(self, choose_proceed):
        dialog=MagicMock()
        adjust=object(); proceed=object()
        dialog.addButton.side_effect=[adjust,proceed]
        dialog.clickedButton.return_value=proceed if choose_proceed else adjust
        with patch("trading_helper.gui.QMessageBox") as m:
            m.return_value=dialog
            m.RejectRole=0;m.AcceptRole=1;m.Question=4
            TradingHelperApp._show_duplicate_entry_decision(self.ui,self.data)
        return dialog

    def test_adjust_returns_main_without_retry(self):
        self.decision(False)
        self.ui._start.assert_not_called()
        self.ui.showNormal.assert_called_once()

    def test_explicit_continue_resumes_safety_workflow(self):
        dialog = self.decision(True)
        self.assertEqual(
            dialog.setWindowTitle.call_args.args[0],
            "發現上次進場紀錄",
        )
        self.assertIn("上次進場紀錄", dialog.setText.call_args.args[0])
        self.assertIn("2025-01-01 05:25:00", dialog.setInformativeText.call_args.args[0])
        self.assertIn("重新核對帳戶", dialog.setInformativeText.call_args.args[0])
        self.ui._start.assert_called_once()
        name,task=self.ui._start.call_args.args
        self.assertEqual(name,"重新確認進場")
        task()
        args=self.ui._fill_both_task.call_args
        self.assertEqual(args.args[:3],("cTrader","MT5",True))
        self.assertTrue(args.kwargs["sync_sl_tp"])
        self.assertEqual(
            args.kwargs["duplicate_confirmation"],
            ("abc","complete","2025-01-01 05:25:00","T-1/T-2"),
        )
        self.assertFalse(args.kwargs.get("manual_reconciliation_confirmed",False))

    def test_late_duplicate_confirmation_does_not_fill_forms_twice(self):
        self.data["request"]["fields_filled"]=True
        self.decision(True)
        _name,task=self.ui._start.call_args.args
        task()
        self.ui._auto_entry_after_fill_both_pending.assert_called_once()
        self.ui._fill_both_task.assert_not_called()

    def test_changed_trade_instruction_blocks_continuation(self):
        self.ui.instruction=object()
        self.decision(True)
        self.ui._start.assert_not_called()

    def test_unknown_previous_submission_disallows_continue(self):
        self.data["retryable"]=False
        self.decision(True)
        self.ui._start.assert_not_called()


if __name__=="__main__":
    unittest.main()

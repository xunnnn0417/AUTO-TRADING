"""Offline preflight/confirmation tests. Absolutely no broker windows used."""
import os
import tempfile
import threading
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch, MagicMock
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from trading_helper import gui
from trading_helper.models import SideValues, TradeInstruction
from trading_helper.automation import REQUIRED_POINTS


def sample():
    return TradeInstruction(
        source_row=2,status="",symbol="XAUUSD",sheet_direction="BUY",
        internal=SideValues(D(".4"),D("-6"),D("10")),
        external=SideValues(D(".3"),D("-8"),D("9")),
        estimated_price=D("4100"),point_size=D("0.01"),price_digits=2,
        internal_balance=D("50000"),daily_pnl=D("0"),
    )


class FillGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp=QApplication.instance() or QApplication([])
    def setUp(self):
        self.no_modal_warning = patch.object(
            gui.QMessageBox, "warning", return_value=QMessageBox.Ok
        )
        self.no_modal_warning.start()
        self.addCleanup(self.no_modal_warning.stop)
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        root=Path(t.name)
        config, profiles = gui.ConfigStore, gui.ProfileStore
        with patch.object(gui,"ConfigStore",side_effect=lambda:config(path=root/"cfg.json")),\
             patch.object(gui,"ProfileStore",side_effect=lambda data:profiles(data,path=root/"profiles.json")),\
             patch.object(gui.WindowController,"warm_ocr",return_value=None),\
             patch.object(gui.TradingHelperApp,"read_sheet",lambda self:None):
            self.w=gui.TradingHelperApp()
        self.w.instruction=sample()
        self.w._show_instruction(self.w.instruction)
        self.w.internal_platform.setCurrentText("cTrader")
        self.w.external_platform.setCurrentText("MT5")
        self.w.show()
        self.qtapp.processEvents()
    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
    def test_main_title_has_no_test_badge(self):
        self.assertEqual(self.w.windowTitle(), "對沖小幫手")
        labels = self.w.findChildren(QLabel)
        self.assertFalse(any(label.objectName() == "versionPill" for label in labels))
        self.assertFalse(any(label.text() == "TEST" for label in labels))

    def calibrated(self):
        w=self.w
        for platform in ("cTrader","MT5"):
            points=w.store.data["platforms"][platform].setdefault("points",{})
            for key in REQUIRED_POINTS[platform]:
                points[key]={"x_px":40,"y_px":40,"window_width":700,"window_height":500}
        w.store.data["platforms"]["cTrader"]["points"]["buy_button"]={"x_px":40}
        w.store.data["platforms"]["cTrader"]["points"]["sell_button"]={"x_px":40}
        w.store.data["platforms"]["MT5"]["points"]["new_order_button"]={"x_px":40}
    def test_missing_required_points_stop_before_window_interaction(self):
        w=self.w
        with patch.object(gui.QMessageBox,"warning") as warning,\
             patch.object(w,"_start") as start:
            w.fill_role("internal")
        start.assert_not_called()
        self.assertIn("手數",warning.call_args.args[2])
        self.assertIn("買入",warning.call_args.args[2])
    def test_missing_on_either_side_stops_both_preflight(self):
        self.calibrated()
        del self.w.store.data["platforms"]["MT5"]["points"]["tp_input"]
        with patch.object(gui.QMessageBox,"warning") as warning,\
             patch.object(self.w,"_start") as start:
            self.w.fill_both()
        start.assert_not_called()
        self.assertIn("場外 MT5",warning.call_args.args[2])

    def test_btc_test_preflight_requires_both_mt5_quote_points(self):
        self.calibrated()
        with patch.dict(os.environ, {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            with patch.object(gui.QMessageBox,"warning") as warning,\
                 patch.object(self.w,"_start") as start:
                self.w.fill_role("external")
        start.assert_not_called()
        message=warning.call_args.args[2]
        self.assertIn("左側報價 Bid",message)
        self.assertIn("右側報價 Ask",message)
    def test_confirmed_enter_allows_fill_when_calibrated(self):
        self.calibrated()
        w=self.w
        w.parameter_inputs["internal_balance"].setText("50500")
        with patch.object(w,"update_all_trade_parameters"):
            w.parameter_inputs["internal_balance"].returnPressed.emit()
        with patch.object(w,"_start") as start,\
             patch.object(gui.QMessageBox,"question") as question:
            w.fill_both()
        question.assert_not_called()
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0],"填入兩邊")
    def test_unconfirmed_draft_cancel_does_not_start(self):
        self.calibrated()
        w=self.w
        w.parameter_inputs["daily_pnl"].setText("123")
        with patch.object(gui.QMessageBox,"question",return_value=QMessageBox.No) as q,\
             patch.object(w,"_start") as start:
            w.fill_both()
        q.assert_called_once()
        start.assert_not_called()
        self.assertIsNone(w._fill_waiting_for_sheet)
    def test_confirm_yes_waits_for_validated_sheet_readback(self):
        self.calibrated()
        w=self.w
        w.parameter_inputs["internal_balance"].setText("50500")
        # Deliberately freeze the async write: the fill must NOT start yet.
        def fake_write():
            w._parameter_write_active=True
        with patch.object(gui.QMessageBox,"question",return_value=QMessageBox.Yes),\
             patch.object(w,"update_all_trade_parameters",side_effect=fake_write),\
             patch.object(w,"_start") as start:
            w.fill_both()
            self.assertFalse(start.called)
            self.assertIsNotNone(w._fill_waiting_for_sheet)
            # Reading stale source data is NOT enough to launch the fill.
            w._show_instruction(sample())
            w._parameter_write_active=False
            w._set_parameter_write_busy(False)
            self.qtapp.processEvents()
            self.assertFalse(start.called)
            self.assertIsNone(w._fill_waiting_for_sheet)
    def test_confirm_yes_resumes_only_after_matching_sheet_refresh(self):
        self.calibrated()
        w=self.w
        w.parameter_inputs["internal_balance"].setText("50500")
        def fake_write():
            w._parameter_write_active=True
        with patch.object(gui.QMessageBox,"question",return_value=QMessageBox.Yes),\
             patch.object(w,"update_all_trade_parameters",side_effect=fake_write),\
             patch.object(w,"_start") as start:
            w.fill_role("internal")
            self.assertFalse(start.called)
            w.instruction=gui.replace(sample(),internal_balance=D("50500"))
            w._show_instruction(w.instruction)
            self.assertFalse(start.called)
            w._parameter_write_active=False
            w._set_parameter_write_busy(False)
            self.qtapp.processEvents()
            start.assert_called_once()
            self.assertEqual(start.call_args.args[0],"填入場內")
            self.assertIsNone(w._fill_waiting_for_sheet)
    def test_confirm_matching_existing_value_does_not_stall(self):
        self.calibrated()
        w=self.w
        w.parameter_inputs["internal_balance"].setText("50000")
        with patch.object(gui.QMessageBox,"question",return_value=QMessageBox.Yes),\
             patch.object(w,"update_all_trade_parameters"),\
             patch.object(w,"_start") as start:
            w.fill_role("internal")
            self.qtapp.processEvents()
            start.assert_called_once()
            self.assertIsNone(w._fill_waiting_for_sheet)

    def test_parallel_fill_task_is_interlocked(self):
        w=self.w
        started=threading.Event()
        release=threading.Event()
        attempts=[]
        def task():
            attempts.append("started")
            started.set()
            release.wait(timeout=2.0)
        try:
            w._start("填入場內",task,hide_during=False)
            self.assertTrue(started.wait(timeout=2.0))
            w._start("填入兩邊",task,hide_during=False)
            self.assertEqual(attempts,["started"])
        finally:
            release.set()
        self.assertFalse(w._fill_task_lock.acquire(timeout=0.02) is False)
        w._fill_task_lock.release()


if __name__=="__main__":
    unittest.main()

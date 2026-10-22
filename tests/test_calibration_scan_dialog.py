"""P2 GUI entry-point checks; deliberately never touch trading-platform UI."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication,QMainWindow,QPushButton,QDialog,QComboBox,QTabWidget
from types import SimpleNamespace
from trading_helper.post_entry_scan import PostEntryReport
from trading_helper.gui import PostEntryCalibrationDialog
import trading_helper.gui as gui
from trading_helper.gui import CalibrationDialog
from trading_helper.calibration_scan import ScanReport,Candidate

class P2CalibrationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_platform_dialogs_expose_explicit_readonly_scan(self):
        for platform in ("cTrader", "MT5"):
            with self.subTest(platform=platform):
                parent=QMainWindow()
                dialog=CalibrationDialog(parent,platform)
                buttons={b.text():b for b in dialog.findChildren(QPushButton)}
                self.assertIn("自動尋找此階段欄位（唯讀）",buttons)
                self.assertIn("手動擷取所選欄位",buttons)
                self.assertIn("查看已校準位置",buttons)
                self.assertNotIn("滑鼠指向檢查＋框線預覽",buttons)
                self.assertNotIn("測試 UIA 自動辨識",buttons)
                self.assertIn("不儲存",buttons["自動尋找此階段欄位（唯讀）"].toolTip())
                self.assertFalse(dialog._inventory_running)
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_report_remains_preview_no_save_calls(self):
        report=ScanReport("cTrader",(("lot_input","手數"),("position_order_row","持倉列")))
        self.assertEqual(report.candidates,{})
        text=report.as_text()
        self.assertIn("手數",text)
        self.assertIn("持倉列",text)
        self.assertIn("未儲存",text)
        self.assertIn("不會覆寫既有校準",text)

    def test_preview_keeps_existing_report_and_never_saves(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"cTrader")
        details=QDialog(dialog)
        report=ScanReport("cTrader",(("lot_input","手數"),))
        report.candidates["lot_input"]=Candidate("lot_input",(614,431,702,447),"UIA candidate")
        original=dict(report.candidates)
        callbacks=[]
        with patch.object(gui.QTimer,"singleShot",side_effect=lambda ms,cb: callbacks.append((ms,cb))), \
                patch.object(dialog._hover_outline,"display") as outline_display, \
                patch.object(details,"showMinimized"), \
                patch.object(dialog,"showMinimized"), \
                patch.object(parent,"showMinimized"), \
                patch.object(details,"showNormal"), \
                patch.object(dialog,"showNormal"), \
                patch.object(parent,"showNormal"), \
                patch.object(details,"raise_"), \
                patch.object(details,"activateWindow"):
            dialog.preview_inventory_candidate(details,report,"lot_input")
            self.assertTrue(dialog._candidate_preview_running)
            self.assertEqual([delay for delay,_ in callbacks],[150,1850])
            callbacks[0][1]()
            outline_display.assert_called_once_with((614,431,702,447),1500)
            callbacks[1][1]()
            self.assertFalse(dialog._candidate_preview_running)
        self.assertEqual(report.candidates,original)
        dialog._hover_outline.close()
        details.close()
        dialog.close()
        parent.close()

    def test_preview_all_outlines_in_one_click_without_save(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"cTrader")
        details=QDialog(dialog)
        report=ScanReport("cTrader",(
            ("lot_input","手數"),("sl_input","止損點數"),("tp_input","止盈點數")
        ))
        for key,rect in (
            ("lot_input",(614,431,702,447)),
            ("sl_input",(596,502,711,525)),
            ("tp_input",(861,502,976,525)),
        ):
            report.candidates[key]=Candidate(key,rect,"UIA read-only")
        saved=dict(report.candidates)
        callbacks=[]
        with patch.object(gui.QTimer,"singleShot",side_effect=lambda ms,cb: callbacks.append((ms,cb))), \
                patch.object(details,"showMinimized"), \
                patch.object(dialog,"showMinimized"), \
                patch.object(parent,"showMinimized"), \
                patch.object(details,"showNormal"), \
                patch.object(dialog,"showNormal"), \
                patch.object(parent,"showNormal"), \
                patch.object(details,"raise_"), \
                patch.object(details,"activateWindow"), \
                patch.object(gui,"CandidateOutline") as overlay_constructor:
            dialog.preview_all_inventory_candidates(details,report)
            self.assertEqual([delay for delay,_ in callbacks],[150,1850])
            self.assertTrue(dialog._candidate_preview_running)
            callbacks[0][1]()
            self.assertEqual(overlay_constructor.call_count,3)
            rectangles=list(saved.values())
            calls=[args[0][0] for args in overlay_constructor.return_value.display.call_args_list]
            self.assertEqual(calls,[candidate.rect for candidate in rectangles])
            durations=[args[0][1] for args in overlay_constructor.return_value.display.call_args_list]
            self.assertEqual(durations,[1500]*3)
            callbacks[1][1]()
            self.assertFalse(dialog._candidate_preview_running)
            self.assertEqual(dialog._inventory_overlays,[])
        self.assertEqual(report.candidates,saved)
        dialog._hover_outline.close()
        details.close()
        dialog.close()
        parent.close()

    def test_scan_result_dialog_has_candidate_preview_control(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"cTrader")
        report=ScanReport("cTrader",(("lot_input","手數"),))
        report.candidates["lot_input"]=Candidate("lot_input",(614,431,702,447),"UIA candidate")
        observed={}
        def intercept_exec(instance):
            observed["buttons"]={b.text():b for b in instance.findChildren(QPushButton)}
            observed["options"]=[c.itemData(i) for c in instance.findChildren(QComboBox) for i in range(c.count())]
            return 0
        with patch.object(QDialog,"exec",intercept_exec):
            dialog._finish_inventory(report)
        self.assertNotIn("預覽所選黃色框（1.5 秒）",observed["buttons"])
        self.assertIn("① 一次預覽全部黃色框（1.5 秒）",observed["buttons"])
        self.assertIn("③ 儲存我已勾選的項目",observed["buttons"])
        self.assertFalse(observed["buttons"]["③ 儲存我已勾選的項目"].isEnabled())
        self.assertEqual(observed["options"],[])
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_same_simple_calibration_structure_across_platforms(self):
        for platform, expected_tabs, expected_items in (
            ("cTrader", 3, 16),
            ("MT5", 4, 16),
            ("TradingView", 1, 8),
        ):
            with self.subTest(platform=platform):
                parent=QMainWindow()
                dialog=CalibrationDialog(parent,platform)
                tabs=dialog.findChildren(QTabWidget)
                self.assertEqual(len(tabs),1)
                self.assertEqual(tabs[0].count(),expected_tabs)
                self.assertEqual(len(dialog.radios),expected_items)
                labels={b.text() for b in dialog.findChildren(QPushButton)}
                self.assertIn("手動擷取所選欄位",labels)
                self.assertIn("查看已校準位置",labels)
                self.assertNotIn("測試 UIA 自動辨識",labels)
                self.assertNotIn("滑鼠指向檢查＋框線預覽",labels)
                if platform in {"cTrader", "MT5"}:
                    self.assertEqual(
                        dialog.radios["position_close_button"].text(),
                        "已進場持倉的平倉按鈕（自動尋找不到時手動擷取）",
                    )
                    close_help=dialog.findChild(
                        gui.QLabel,"positionCloseCalibrationHelp"
                    )
                    self.assertIn("持倉列最右側",close_help.text())
                    self.assertIn("黃框核對",close_help.text())
                    self.assertIn("不會點擊或平倉",close_help.text())
                self.assertEqual(
                    "自動尋找此階段欄位（唯讀）" in labels,
                    platform!="TradingView",
                )
                self.assertNotIn(
                    "開始辨識進場後欄位（唯讀）", labels,
                )
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_mt5_order_stage_requires_existing_same_process_order_window(self):
        from unittest.mock import MagicMock, patch
        from trading_helper.windows import WindowInfo
        main=WindowInfo(123,"53099775 - ICMarketsSC-Demo - [XAUUSD,H1]",0,0,1400,960)
        order=WindowInfo(124,"Order",350,200,850,750)
        parent=QMainWindow()
        parent.internal_platform=SimpleNamespace(currentText=lambda:"cTrader")
        parent.store=SimpleNamespace(data={"platforms":{"MT5":{
            "window_title":{"external":"MetaTrader"},"points":{}
        }}})
        windows=SimpleNamespace(
            find=lambda pattern:main,
            list_windows=lambda:[main],
        )
        parent.windows=windows
        dialog=CalibrationDialog(parent,"MT5")
        dialog._calibration_tabs.setCurrentIndex(1)
        with patch.object(gui,"process_id_for_window",return_value=888), \
             patch.object(gui.QMessageBox,"warning") as warning, \
             patch.object(gui.threading,"Thread") as thread:
            dialog.scan_all_calibration()
            self.assertTrue(warning.called)
            self.assertFalse(dialog._inventory_running)
            thread.assert_not_called()
            windows.list_windows=lambda:[main,order]
            warning.reset_mock()
            dialog.scan_all_calibration()
            warning.assert_not_called()
            self.assertEqual(dialog._inventory_scan_context["window"].handle,124)
            self.assertTrue(dialog._inventory_running)
            thread.assert_called_once()
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_manual_capture_starts_hidden_on_brokers_and_is_reversible(self):
        for platform in ("cTrader", "MT5", "TradingView"):
            with self.subTest(platform=platform):
                parent=QMainWindow()
                dialog=CalibrationDialog(parent,platform)
                if platform == "TradingView":
                    self.assertFalse(dialog.manual_capture_button.isHidden())
                else:
                    self.assertTrue(dialog.manual_capture_button.isHidden())
                    self.assertTrue(dialog.manual_position_button.isHidden())
                dialog.manual_tools_toggle.setChecked(True)
                self.assertFalse(dialog.manual_capture_button.isHidden())
                self.assertFalse(dialog.manual_position_button.isHidden())
                dialog.manual_tools_toggle.setChecked(False)
                self.assertTrue(dialog.manual_capture_button.isHidden())
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_mt5_second_stage_selects_its_quote_and_order_items(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"MT5")
        self.assertEqual(len(dialog._stage_keys),4)
        self.assertEqual(tuple(dialog._stage_keys[0]),("new_order_button","trade_tab"))
        self.assertEqual(len(dialog._stage_keys[1]),7)
        self.assertEqual(set(dialog._stage_keys[2]),
                         {"positions_entry_price","position_order_lot","position_order_row",
                          "position_close_button"})
        self.assertEqual(set(dialog._stage_keys[3]),
                         {"position_sl_input","position_tp_input","position_modify_confirm"})
        tabs=dialog.findChildren(QTabWidget)[0]
        self.assertFalse(dialog.radios["positions_entry_price"].isChecked())
        tabs.setCurrentIndex(1)
        self.assertTrue(dialog.radios["lot_input"].isChecked())
        self.assertFalse(dialog.radios["new_order_button"].isChecked())
        tabs.setCurrentIndex(2)
        self.assertTrue(dialog.radios["positions_entry_price"].isChecked())
        close_capture=dialog.findChild(
            QPushButton,"capturePositionCloseButton"
        )
        self.assertIsNotNone(close_capture)
        close_help=dialog.findChild(gui.QLabel,"positionCloseCalibrationHelp")
        self.assertIsNotNone(close_help)
        self.assertIn("持倉列最右側",close_help.text())
        self.assertIn("黃框核對",close_help.text())
        with patch.object(dialog,"capture") as capture:
            close_capture.click()
        self.assertTrue(dialog.radios["position_close_button"].isChecked())
        capture.assert_called_once_with()
        tabs.setCurrentIndex(3)
        self.assertTrue(dialog.radios["position_modify_confirm"].isChecked()
                        or dialog.radios["position_sl_input"].isChecked())
        tabs.setCurrentIndex(0)
        self.assertTrue(dialog.radios["new_order_button"].isChecked())
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_no_disabled_preview_until_one_position_has_candidates(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"cTrader")
        wizard=PostEntryCalibrationDialog(dialog)
        buttons={b.text() for b in wizard.findChildren(QPushButton)}
        self.assertIn("開始辨識持倉欄位（唯讀）",buttons)
        self.assertNotIn("掃描目前持倉（唯讀）",buttons)
        self.assertNotIn("開始等待一筆持倉（唯讀）",buttons)
        self.assertTrue(wizard.preview_button.isHidden())
        self.assertIn("後出現",wizard.preview_note.text())
        empty=PostEntryReport(state="empty",count=0,scanned=80)
        wizard._finish_scan(empty)
        self.assertTrue(wizard.preview_button.isHidden())
        report=PostEntryReport(state="single",count=1,scanned=100)
        report.candidates["position_order_lot"]=Candidate(
            "position_order_lot",(100,200,150,230),"test"
        )
        wizard._finish_scan(report)
        self.assertFalse(wizard.preview_button.isHidden())
        self.assertIn("已找到候選",wizard.preview_note.text())
        wizard.close()
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_ctrader_has_two_distinct_tabs_and_post_entry_launch(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"cTrader")
        tabs=dialog.findChildren(QTabWidget)
        self.assertTrue(tabs)
        labels=[tabs[0].tabText(i) for i in range(tabs[0].count())]
        self.assertEqual(len(labels),3)
        self.assertIn("進場前",labels[0])
        self.assertIn("持倉列表",labels[1])
        self.assertIn("修改視窗",labels[2])
        self.assertEqual(len(dialog.radios),16)
        self.assertIn("position_close_button",dialog._stage_keys[1])
        wizard=[b for b in dialog.findChildren(QPushButton)
                if b.text()=="開始辨識進場後欄位（唯讀）"]
        self.assertEqual(len(wizard),0)
        self.assertEqual(dialog.radios["account_number"].isChecked(),True)
        tabs[0].setCurrentIndex(1)
        self.assertTrue(dialog.radios["positions_entry_price"].isChecked())
        self.assertFalse(dialog.radios["account_number"].isChecked())
        close_capture=dialog.findChild(QPushButton,"capturePositionCloseButton")
        self.assertIsNotNone(close_capture)
        self.assertIn("5 秒",close_capture.text())
        self.assertIn("黃框核對",close_capture.toolTip())
        self.assertIn("不會點擊或平倉",close_capture.toolTip())
        close_help=dialog.findChild(gui.QLabel,"positionCloseCalibrationHelp")
        self.assertIsNotNone(close_help)
        self.assertIn("cTrader 圖示會變色",close_help.text())
        with patch.object(dialog,"capture") as capture:
            close_capture.click()
        self.assertTrue(dialog.radios["position_close_button"].isChecked())
        capture.assert_called_once_with()
        tabs[0].setCurrentIndex(0)
        self.assertTrue(dialog.radios["account_number"].isChecked())
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_manual_close_capture_completion_requests_yellow_preview(self):
        for platform in ("cTrader", "MT5"):
            with self.subTest(platform=platform):
                parent=QMainWindow()
                dialog=CalibrationDialog(parent,platform)
                rect=(400,500,430,530)
                with patch.object(dialog,"_refresh_stage_progress"), \
                     patch.object(dialog,"_show_manual_capture_preview") as preview:
                    dialog._finish_capture({
                        "key":"position_close_button",
                        "preview_rect":rect,
                        "preview_source":"UI 控制項外框",
                    })
                preview.assert_called_once_with(rect,"UI 控制項外框")
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_manual_close_capture_outline_uses_small_uia_bounds_or_point_box(self):
        point_rect,point_source=gui.manual_capture_confirmation_rect(100,200,None)
        self.assertEqual(point_rect,(84,184,116,216))
        self.assertEqual(point_source,"手動擷取點")
        button_rect,button_source=gui.manual_capture_confirmation_rect(
            100,200,(90,190,110,210)
        )
        self.assertEqual(button_rect,(90,190,110,210))
        self.assertEqual(button_source,"UI 控制項外框")
        row_rect,row_source=gui.manual_capture_confirmation_rect(
            100,200,(0,190,1600,220)
        )
        self.assertEqual(row_rect,(84,184,116,216))
        self.assertEqual(row_source,"手動擷取點")

    def test_post_entry_watch_stops_on_multiple_but_keeps_waiting_on_empty(self):
        parent=QMainWindow()
        parent.store=SimpleNamespace(data={"platforms":{"cTrader":{
            "window_title":{"internal":"TEST_CTRADER","external":"TEST_CTRADER"}
        }}})
        parent.windows=SimpleNamespace(find=lambda _:SimpleNamespace(handle=991))
        parent.internal_platform=SimpleNamespace(currentText=lambda:"cTrader")
        dialog=CalibrationDialog(parent,"cTrader")
        wizard=PostEntryCalibrationDialog(dialog)
        empty=PostEntryReport(state="empty",count=0,scanned=25)
        multiple=PostEntryReport(state="multiple",count=2,scanned=100)
        with patch.object(gui,"process_id_for_window",return_value=17804), \
             patch.object(gui,"inspect_post_entry",return_value=empty) as scan:
            wizard.toggle_watch()
            import time
            deadline=time.monotonic()+2
            while wizard.last_report is None and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(scan.called)
            self.assertEqual(wizard.last_report.state,"empty")
            self.assertTrue(wizard.preview_button.isHidden())
            self.assertTrue(wizard._watching)
            self.assertTrue(wizard.watch_timer.isActive())
        wizard._finish_scan(multiple)
        self.assertFalse(wizard._watching)
        self.assertFalse(wizard.watch_timer.isActive())
        self.assertEqual(wizard.last_report.count,2)
        self.assertIn("停止自動辨識",wizard.status_label.text())
        self.assertTrue(wizard.preview_button.isHidden())
        with patch.object(wizard,"scan_once"):
            wizard.toggle_watch()
        self.assertTrue(wizard.watch_timer.isActive())
        wizard.accept()
        self.assertFalse(wizard.watch_timer.isActive())
        self.assertFalse(wizard._watching)
        wizard.close()
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

if __name__=="__main__":
    unittest.main()

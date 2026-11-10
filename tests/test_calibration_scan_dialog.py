"""P2 GUI entry-point checks; deliberately never touch trading-platform UI."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication,QMainWindow,QPushButton,QDialog,QComboBox,QTabWidget
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
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
                self.assertIn("自動尋找欄位",buttons)
                self.assertNotIn("手動擷取所選欄位",buttons)
                clear=dialog.findChild(QComboBox,"clearSelectedCalibration")
                self.assertIsNotNone(clear)
                self.assertEqual(
                    [clear.itemText(i) for i in range(clear.count())],
                    ["清除目前欄位","清除此階段全部欄位"],
                )
                self.assertEqual(clear.placeholderText(),"清除欄位")
                viewer=dialog.findChild(QComboBox,"calibratedPositionViewer")
                self.assertIsNotNone(viewer)
                self.assertIsInstance(viewer,gui.ChevronCombo)
                self.assertIsInstance(clear,gui.ChevronCombo)
                self.assertEqual(
                    [viewer.itemText(i) for i in range(viewer.count())],
                    ["查看此欄位","顯示本階段全部欄位"],
                )
                self.assertEqual(viewer.placeholderText(),"查看已校準位置")
                self.assertFalse(hasattr(dialog,"manual_tools_toggle"))
                self.assertNotIn("滑鼠指向檢查＋框線預覽",buttons)
                self.assertNotIn("測試 UIA 自動辨識",buttons)
                self.assertIn("不儲存",buttons["自動尋找欄位"].toolTip())
                self.assertFalse(dialog._inventory_running)
                self.assertTrue(dialog.windowFlags() & gui.Qt.FramelessWindowHint)
                self.assertIsNotNone(dialog.findChild(gui.QFrame,"compactTitleBar"))
                self.assertIsNone(dialog.findChild(gui.QToolButton,"chrome_minimize"))
                self.assertIsNone(dialog.findChild(gui.QToolButton,"chrome_maximize"))
                close_control=dialog.findChild(gui.QToolButton,"chrome_close")
                self.assertIsInstance(close_control,gui.WindowChromeButton)
                self.assertFalse(dialog.title_bar.allow_maximize)
                title=dialog.findChild(gui.QLabel,"dialogTitle")
                self.assertTrue(title.alignment() & gui.Qt.AlignLeft)
                self.assertTrue(title.alignment() & gui.Qt.AlignVCenter)
                self.assertFalse(title.alignment() & gui.Qt.AlignTop)
                chrome_margins=dialog.title_bar.layout().contentsMargins()
                self.assertEqual(
                    (chrome_margins.left(),chrome_margins.top(),
                     chrome_margins.right(),chrome_margins.bottom()),
                    (10,2,3,2),
                )
                outer_margins=dialog.layout().contentsMargins()
                self.assertEqual((outer_margins.left(),outer_margins.right()),(0,0))
                body_margins=dialog._calibration_content_layout.contentsMargins()
                self.assertEqual((body_margins.left(),body_margins.right()),(9,9))
                self.assertIsNotNone(
                    dialog._calibration_tabs.findChild(gui.QFrame,"calibrationStageCard")
                )
                self.assertIs(dialog.result.parent(),dialog._calibration_tabs)
                self.assertIn("#101014",dialog.styleSheet())
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_calibration_outer_stage_area_keeps_one_height_when_switching_tabs(self):
        for platform in ("cTrader", "MT5", "TradingView"):
            with self.subTest(platform=platform):
                parent=QMainWindow()
                with patch.object(gui.QTimer,"singleShot"):
                    dialog=CalibrationDialog(parent,platform)
                    tabs=dialog._calibration_tabs
                    observed_heights=[]
                    for index in range(tabs.count()):
                        tabs.setCurrentIndex(index)
                        dialog._fit_calibration_dialog_to_current_stage()
                        observed_heights.append(
                            (tabs.minimumHeight(),tabs.maximumHeight())
                        )
                    self.assertGreater(len(set(observed_heights)),0)
                    self.assertEqual(
                        len(set(observed_heights)),1,
                        f"stage area height changed across {platform} stages: {observed_heights}",
                    )
                self.assertGreaterEqual(
                    dialog.result.y() + dialog.result.height(),
                    tabs.height() - 8,
                )
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
        with patch.object(dialog._hover_outline,"display") as outline_display, \
                patch.object(details,"setWindowOpacity") as opacity_details, \
                patch.object(dialog,"setWindowOpacity") as opacity_dialog, \
                patch.object(dialog,"_begin_calibration_operation") as begin_operation, \
                patch.object(dialog,"_start_preview_countdown") as countdown, \
                patch.object(dialog,"showMinimized") as minimize_dialog, \
                patch.object(parent,"showMinimized") as minimize_parent, \
                patch.object(details,"showNormal"), \
                patch.object(dialog,"showNormal"), \
                patch.object(parent,"showNormal"), \
                patch.object(details,"raise_"), \
                patch.object(details,"activateWindow"), \
                patch.object(gui,"CandidateOutline") as overlay_constructor:
            dialog.preview_inventory_candidate(details,report,"lot_input")
            self.assertTrue(dialog._candidate_preview_running)
            opacity_dialog.assert_any_call(0.0)
            begin_operation.assert_called_once_with(
                "正在預覽候選欄位｜按 ESC 或右鍵取消"
            )
            countdown.assert_called_once_with(
                2,inventory_details=details,
                inventory_rectangles=((614,431,702,447),),
            )
            minimize_dialog.assert_not_called()
            minimize_parent.assert_not_called()
            outline_display.assert_not_called()
            overlay_constructor.assert_not_called()
            dialog._show_inventory_preview_outlines({
                "rectangles":((614,431,702,447),),
            })
            self.assertEqual(overlay_constructor.call_count,1)
            overlay_constructor.return_value.display.assert_called_once_with(
                (614,431,702,447),1500
            )
            dialog._finish_saved_preview({
                "inventory_details":details,"cancelled":False,
            })
            self.assertFalse(dialog._candidate_preview_running)
            self.assertIn(((1.0,), {}), opacity_dialog.call_args_list)
            self.assertIn(((1.0,), {}), opacity_details.call_args_list)
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
        with patch.object(details,"setWindowOpacity") as opacity_details, \
                patch.object(dialog,"setWindowOpacity") as opacity_dialog, \
                patch.object(dialog,"_begin_calibration_operation") as begin_operation, \
                patch.object(dialog,"_start_preview_countdown") as countdown, \
                patch.object(dialog,"showMinimized") as minimize_dialog, \
                patch.object(parent,"showMinimized") as minimize_parent, \
                patch.object(details,"showNormal"), \
                patch.object(dialog,"showNormal"), \
                patch.object(parent,"showNormal"), \
                patch.object(details,"raise_"), \
                patch.object(details,"activateWindow"), \
                patch.object(gui,"CandidateOutline") as overlay_constructor:
            dialog.preview_all_inventory_candidates(details,report)
            opacity_dialog.assert_any_call(0.0)
            begin_operation.assert_called_once_with(
                "正在預覽全部候選欄位｜按 ESC 或右鍵取消"
            )
            countdown.assert_called_once_with(
                2,inventory_details=details,
                inventory_rectangles=tuple(candidate.rect for candidate in saved.values()),
            )
            minimize_dialog.assert_not_called()
            minimize_parent.assert_not_called()
            self.assertTrue(dialog._candidate_preview_running)
            dialog._show_inventory_preview_outlines({
                "rectangles":tuple(candidate.rect for candidate in saved.values()),
            })
            self.assertEqual(overlay_constructor.call_count,3)
            rectangles=list(saved.values())
            calls=[args[0][0] for args in overlay_constructor.return_value.display.call_args_list]
            self.assertEqual(calls,[candidate.rect for candidate in rectangles])
            durations=[args[0][1] for args in overlay_constructor.return_value.display.call_args_list]
            self.assertEqual(durations,[1500]*3)
            dialog._finish_saved_preview({
                "inventory_details":details,"cancelled":False,
            })
            self.assertFalse(dialog._candidate_preview_running)
            self.assertIn(((1.0,), {}), opacity_dialog.call_args_list)
            self.assertIn(((1.0,), {}), opacity_details.call_args_list)
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
        self.assertIn("② 全選並儲存",observed["buttons"])
        self.assertIn("關閉結果（不儲存）",observed["buttons"])
        self.assertNotIn("全選",observed["buttons"])
        self.assertNotIn("清除勾選",observed["buttons"])
        self.assertFalse(observed["buttons"]["② 全選並儲存"].isEnabled())
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
                self.assertNotIn("手動擷取所選欄位",labels)
                self.assertIsNotNone(
                    dialog.findChild(QComboBox,"clearSelectedCalibration")
                )
                if platform == "TradingView":
                    self.assertEqual(len(dialog._field_capture_buttons),expected_items)
                else:
                    self.assertIn("手動擷取欄位",labels)
                viewer=dialog.findChild(QComboBox,"calibratedPositionViewer")
                self.assertIsNotNone(viewer)
                self.assertNotIn("測試 UIA 自動辨識",labels)
                self.assertNotIn("滑鼠指向檢查＋框線預覽",labels)
                if platform in {"cTrader", "MT5"}:
                    self.assertEqual(
                        dialog.radios["position_close_button"].text(),
                        "已進場持倉的平倉按鈕",
                    )
                    close_help=dialog.findChild(
                        gui.QLabel,"positionCloseCalibrationHelp"
                    )
                    self.assertIn("持倉列最右側",close_help.text())
                    self.assertIn("黃框核對",close_help.text())
                    self.assertIn("不會點擊或平倉",close_help.text())
                self.assertEqual(
                    "自動尋找欄位" in labels,
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
        main=WindowInfo(123,"11111111 - Example-Demo - [XAUUSD,H1]",0,0,1400,960)
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

    def test_footer_has_view_and_clear_but_no_standalone_manual_capture(self):
        for platform in ("cTrader", "MT5", "TradingView"):
            with self.subTest(platform=platform):
                parent=QMainWindow()
                dialog=CalibrationDialog(parent,platform)
                self.assertFalse(dialog.findChild(QComboBox,"clearSelectedCalibration").isHidden())
                self.assertFalse(dialog.manual_position_button.isHidden())
                self.assertFalse(hasattr(dialog,"manual_capture_button"))
                if platform == "TradingView":
                    self.assertEqual(len(dialog._field_capture_buttons),8)
                    self.assertEqual(len(dialog._field_capture_dots),8)
                else:
                    self.assertEqual(dialog._field_capture_buttons,{})
                self.assertFalse(hasattr(dialog,"manual_tools_toggle"))
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_missing_close_field_has_inline_red_dot_and_saved_field_clears_it(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"MT5")
        self.assertFalse(dialog.position_close_missing_dot.isHidden())
        parent.store=SimpleNamespace(data={"ui":{"show_calibration_badges":True},
            "platforms":{"MT5":{"points":{"position_close_button":{"x":0.5}}}}})
        dialog._refresh_position_close_badge()
        self.assertTrue(dialog.position_close_missing_dot.isHidden())
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_clear_selected_calibration_confirms_and_shows_missing_badge(self):
        parent=QMainWindow()
        data={"ui":{"show_calibration_badges":True},"platforms":{"MT5":{
            "points":{"new_order_button":{"x":0.3,"y":0.4}},
            "window_title":{"internal":"MT5","external":"MT5"},
        }}}
        parent.store=SimpleNamespace(data=data,save=Mock())
        profiles=SimpleNamespace(
            clear_calibration_point=Mock(
                side_effect=lambda platform,key:data["platforms"][platform]["points"].pop(key)
            ),
            load_profile=Mock(return_value=data),
        )
        parent.profiles=profiles
        parent.automation=SimpleNamespace(config=data)
        dialog=CalibrationDialog(parent,"MT5")
        self.assertTrue(dialog.clear_calibration_button.isEnabled())
        with patch.object(gui.QMessageBox,"question",return_value=gui.QMessageBox.No):
            dialog.clear_selected_calibration()
        profiles.clear_calibration_point.assert_not_called()
        with patch.object(gui.QMessageBox,"question",return_value=gui.QMessageBox.Yes):
            dialog.clear_selected_calibration()
        profiles.clear_calibration_point.assert_called_once_with("MT5","new_order_button")
        self.assertFalse(dialog.clear_calibration_button.isEnabled())
        self.assertFalse(dialog._stage_dots[0].isHidden())
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_clear_stage_confirmation_clears_only_selected_stage(self):
        parent=QMainWindow()
        data={"ui":{"show_calibration_badges":True},"platforms":{"MT5":{
            "points":{"new_order_button":{"x":0.3,"y":0.4}},
        }}}
        parent.store=SimpleNamespace(data=data,save=Mock())
        parent.profiles=SimpleNamespace(
            clear_calibration_stage=Mock(
                return_value=("new_order_button","trade_tab")
            ),
            load_profile=Mock(return_value=data),
        )
        parent.automation=SimpleNamespace(config=data)
        dialog=CalibrationDialog(parent,"MT5")
        with patch.object(gui.QMessageBox,"question",return_value=gui.QMessageBox.No):
            dialog._clear_all_calibrations()
        parent.profiles.clear_calibration_stage.assert_not_called()
        with patch.object(gui.QMessageBox,"question",return_value=gui.QMessageBox.Yes):
            dialog._clear_all_calibrations()
        parent.profiles.clear_calibration_stage.assert_called_once_with(
            "MT5", dialog._stage_keys[0]
        )
        self.assertIn("2 個欄位",dialog.result.text())
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_display_all_preview_is_limited_to_current_stage(self):
        parent=QMainWindow()
        parent.store=SimpleNamespace(data={"platforms":{"MT5":{"points":{}}}})
        dialog=CalibrationDialog(parent,"MT5")
        dialog._calibration_tabs.setCurrentIndex(2)
        with patch.object(dialog,"_saved_point_rectangles",return_value=([(1,2,3,4)],[],[])) as saved, \
             patch.object(dialog,"_preview_saved_calibration"):
            dialog.show_position(show_all=True)
        saved.assert_called_once_with(dialog._stage_keys[2])
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_calibration_footer_combos_open_from_the_text_area(self):
        parent=QMainWindow()
        parent.store=SimpleNamespace(data={"platforms":{"MT5":{
            "points":{"new_order_button":{"x":0.3,"y":0.4}},
        }}})
        parent.profiles=SimpleNamespace(data={"profiles":{"預設方案":{
            "platforms":{"MT5":{"points":{"new_order_button":{"x":0.3}}}}
        }}})
        dialog=CalibrationDialog(parent,"MT5")
        dialog.show()
        QApplication.processEvents()
        for name in ("calibratedPositionViewer","clearSelectedCalibration"):
            combo=dialog.findChild(QComboBox,name)
            point=QPoint(12,combo.height()//2)
            QTest.mouseClick(combo,gui.Qt.LeftButton,pos=point)
            QApplication.processEvents()
            self.assertTrue(combo.view().isVisible(),name)
            combo.hidePopup()
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_calibration_cancel_marks_only_local_task(self):
        parent=QMainWindow()
        parent.operation_hint=SimpleNamespace(setText=Mock())
        parent._hide_for_operation=Mock()
        parent._restore_after_operation=Mock()
        dialog=CalibrationDialog(parent,"MT5")
        dialog._begin_calibration_operation("正在尋找；按 ESC 或右鍵取消")
        abort=dialog._calibration_abort
        self.assertFalse(abort.event.is_set())
        dialog.cancel_calibration_operation()
        self.assertTrue(abort.event.is_set())
        self.assertFalse(parent.emergency.event.is_set()) if hasattr(parent,"emergency") else None
        dialog._restore_calibration_operation()
        parent._restore_after_operation.assert_called_once_with()
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_saved_position_viewer_uses_yellow_box_without_emergency_guard(self):
        parent=QMainWindow()
        win=gui.WindowInfo(52,"cTrader 5.10.20",100,200,900,800)
        parent.store=SimpleNamespace(data={"platforms":{"cTrader":{
            "window_title":{"internal":"cTrader","external":"cTrader"},
            "points":{"lot_input":{"x":0.5,"y":0.5,
                "bounds_width":90,"bounds_height":20,
                "window_title":"cTrader","calibration_window_title":"cTrader"}},
        }}})
        parent.internal_platform=SimpleNamespace(currentText=lambda:"cTrader")
        parent.windows=SimpleNamespace(
            find_all=lambda _pattern:[win], list_windows=lambda:[win],
            screen_point_for_display=lambda _win,_point:(500,600),
        )
        parent.automation=SimpleNamespace(
            _window_for_point=Mock(side_effect=gui.EmergencyStopped(
                "緊急停止目前生效中。"
            ))
        )
        parent.log=lambda _message:None
        dialog=CalibrationDialog(parent,"cTrader")
        dialog.radios["lot_input"].setChecked(True)
        with patch.object(gui,"process_id_for_window",return_value=73), \
                patch.object(dialog,"_preview_saved_calibration") as preview, \
                patch.object(gui.QMessageBox,"warning") as warning:
            dialog.show_position()
        warning.assert_not_called()
        preview.assert_called_once_with([(455,590,545,610)],[])
        parent.automation._window_for_point.assert_not_called()
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_saved_main_window_points_prefer_current_binding_to_old_capture_title(self):
        parent=QMainWindow()
        win=gui.WindowInfo(91,"Terminal - BTCUSD,H1",0,0,1500,900)
        parent.store=SimpleNamespace(data={"platforms":{"MT5":{
            "window_title":{"internal":"current-main-binding","external":"other"},
            "points":{"trade_tab":{"x":0.2,"y":0.8,
                "calibration_window_title":"stale-old-chart-title"}},
        }}})
        parent.internal_platform=SimpleNamespace(currentText=lambda:"MT5")
        parent.windows=SimpleNamespace(
            find_all=Mock(return_value=[win]),list_windows=Mock(return_value=[win])
        )
        dialog=CalibrationDialog(parent,"MT5")
        with patch.object(gui,"select_broker_main_window",return_value=win) as select, \
             patch.object(gui,"process_id_for_window",return_value=44):
            result=dialog._display_window_for_saved_point(
                "trade_tab",parent.store.data["platforms"]["MT5"]["points"]["trade_tab"]
            )
        self.assertIs(result,win)
        parent.windows.find_all.assert_called_once_with("current-main-binding")
        select.assert_called_once()
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_show_all_reports_each_unavailable_saved_point_instead_of_silent_skip(self):
        parent=QMainWindow()
        parent.store=SimpleNamespace(data={"platforms":{"MT5":{"points":{}}}})
        dialog=CalibrationDialog(parent,"MT5")
        _rectangles, _markers, unavailable=dialog._saved_point_rectangles(
            ("new_order_button","trade_tab")
        )
        self.assertEqual(len(unavailable),2)
        self.assertTrue(all("未校準" in item for item in unavailable))
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
        self.assertEqual("手動擷取欄位",close_capture.text())
        close_help=dialog.findChild(gui.QLabel,"positionCloseCalibrationHelp")
        self.assertIsNotNone(close_help)
        self.assertIn("黃框核對",close_help.text())
        self.assertIn("不會點擊或平倉",close_capture.toolTip())
        self.assertIn("最右側",close_help.text())
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
                preview.assert_called_once_with(
                    rect,"UI 控制項外框",point=None
                )
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_manual_capture_requires_real_bounds_for_a_full_yellow_frame(self):
        point_rect,point_source=gui.manual_capture_confirmation_rect(100,200,None)
        self.assertIsNone(point_rect)
        self.assertEqual(point_source,"無法取得完整控件外框")
        button_rect,button_source=gui.manual_capture_confirmation_rect(
            100,200,(90,190,110,210)
        )
        self.assertEqual(button_rect,(90,190,110,210))
        self.assertEqual(button_source,"UI 控制項外框")
        row_rect,row_source=gui.manual_capture_confirmation_rect(
            100,200,(0,190,1600,220)
        )
        self.assertIsNone(row_rect)
        self.assertEqual(row_source,"無法取得完整控件外框")

    def test_manual_close_without_uia_bounds_saves_and_previews_the_point(self):
        parent=QMainWindow()
        dialog=CalibrationDialog(parent,"MT5")
        point=(420,530)
        with patch.object(dialog,"_refresh_stage_progress"), \
             patch.object(dialog,"_show_manual_capture_preview") as preview:
            dialog._finish_capture({
                "key":"position_close_button",
                "preview_rect":None,
                "preview_source":"只有座標",
                "preview_point":point,
            })
        preview.assert_called_once_with(
            None,"只有座標",point=point
        )
        self.assertFalse(dialog._capture_running)
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_point_only_saved_position_is_previewed_as_a_marker(self):
        parent=QMainWindow()
        win=gui.WindowInfo(52,"Terminal - BTCUSD,H1",0,0,1500,900)
        parent.store=SimpleNamespace(data={"platforms":{"MT5":{
            "window_title":{"internal":"Terminal","external":"Terminal"},
            "points":{"position_close_button":{
                "x":0.5,"y":0.5,"bounds_source":"point_only",
                "window_title":"Terminal",
            }},
        }}})
        parent.internal_platform=SimpleNamespace(currentText=lambda:"MT5")
        parent.windows=SimpleNamespace(
            find_all=lambda _pattern:[win],list_windows=lambda:[win],
            screen_point_for_display=lambda _win,_point:(420,530),
        )
        parent.log=lambda _message:None
        dialog=CalibrationDialog(parent,"MT5")
        dialog._calibration_tabs.setCurrentIndex(2)
        dialog.radios["position_close_button"].setChecked(True)
        with patch.object(gui,"select_broker_main_window",return_value=win), \
             patch.object(gui,"process_id_for_window",return_value=73), \
             patch.object(dialog,"_preview_saved_calibration") as preview, \
             patch.object(gui.QMessageBox,"warning") as warning:
            dialog.show_position()
        warning.assert_not_called()
        preview.assert_called_once_with([] ,[(420,530)])
        self.assertIn("黃色校準點",dialog.result.text())
        self.assertIn("並非完整欄位框",dialog.result.text())
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_capture_disables_buttons_and_ignores_a_second_click_until_finished(self):
        parent=QMainWindow()
        parent.operation_hint=gui.QLabel(parent)
        parent._hide_for_operation=Mock()
        parent._restore_after_operation=Mock()
        dialog=CalibrationDialog(parent,"MT5")
        buttons=dialog._capture_buttons
        self.assertTrue(buttons)
        with patch.object(gui.threading,"Thread") as thread:
            dialog.capture()
            dialog.capture()
            thread.assert_called_once()
            self.assertTrue(dialog._capture_running)
            self.assertTrue(all(not button.isEnabled() for button in buttons))
            dialog._finish_capture({"cancelled":True})
            self.assertFalse(dialog._capture_running)
            self.assertTrue(all(button.isEnabled() for button in buttons))
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

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

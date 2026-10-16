"""Conservative follow-up preferences, hover help, and hidden feature audit."""
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QPushButton

from trading_helper import gui
from trading_helper.config import DEFAULT_CONFIG


class CompactFollowUpControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp=QApplication.instance() or QApplication([])

    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder=Path(tmp.name)
        real_config=gui.ConfigStore
        real_profiles=gui.ProfileStore
        with patch.object(gui,"ConfigStore",side_effect=lambda:real_config(path=folder/"cfg.json")),\
             patch.object(gui,"ProfileStore",side_effect=lambda x:real_profiles(x,path=folder/"profiles.json")),\
             patch.object(gui.WindowController,"warm_ocr",return_value=None),\
             patch.object(gui.TradingHelperApp,"read_sheet",lambda _self:None):
            self.w=gui.TradingHelperApp()
        self.w.show()
        self.qtapp.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.qtapp.processEvents()

    def test_three_toggles_visible_off_by_default_with_two_second_help(self):
        self.w.switch_workspace("交易")
        for name in (
            "auto_entry_on_fill_both",
            "auto_sync_sl_tp_after_entry",
            "auto_draw_tv_after_entry",
        ):
            checkbox=getattr(self.w,name)
            self.assertIsInstance(checkbox,QCheckBox)
            self.assertTrue(checkbox.isVisible())
            self.assertFalse(checkbox.isChecked())
            self.assertTrue(checkbox.toolTip())
            self.assertIn(checkbox,self.w._hover_help._details)
            self.assertTrue(self.w._hover_help.eventFilter(
                checkbox,QEvent(QEvent.ToolTip)
            ))
        self.assertEqual(self.w._hover_help._timer.interval(),2000)
        self.assertTrue(self.w.auto_entry_on_fill_both.isEnabled())
        self.assertFalse(self.w.auto_sync_sl_tp_after_entry.isEnabled())
        self.assertFalse(self.w.auto_draw_tv_after_entry.isEnabled())
        for key in (
            "auto_entry_on_fill_both",
            "auto_sync_sl_tp_after_entry",
            "auto_draw_tv_after_entry",
        ):
            self.assertFalse(DEFAULT_CONFIG["ui"][key])

    def test_future_options_are_opt_in_and_saved_per_profile(self):
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes):
            self.w.auto_entry_on_fill_both.setChecked(True)
        self.assertTrue(self.w.auto_sync_sl_tp_after_entry.isEnabled())
        self.assertFalse(self.w.auto_draw_tv_after_entry.isEnabled())
        for checkbox in (
            self.w.auto_sync_sl_tp_after_entry,
            self.w.auto_draw_tv_after_entry,
        ):
            with patch("trading_helper.gui.QMessageBox.question",
                       return_value=QMessageBox.No) as dialog:
                checkbox.setChecked(True)
                self.assertFalse(checkbox.isChecked())
                dialog.assert_called_once()
            with patch("trading_helper.gui.QMessageBox.question",
                       return_value=QMessageBox.Yes) as dialog:
                checkbox.setChecked(True)
                self.assertTrue(checkbox.isChecked())
                dialog.assert_called_once()
        self.assertTrue(self.w.store.data["ui"]["auto_sync_sl_tp_after_entry"])
        self.assertTrue(self.w.store.data["ui"]["auto_draw_tv_after_entry"])
        self.assertTrue(self.w.profiles.load_profile()[
            "ui"]["auto_sync_sl_tp_after_entry"])
        self.assertTrue(self.w.profiles.load_profile()[
            "ui"]["auto_draw_tv_after_entry"])
        # Remember individually confirmed options, without another prompt
        # or firing any fill/order workflow on profile restore.
        with patch("trading_helper.gui.QMessageBox.question") as question:
            self.w._apply_profile_ui()
            question.assert_not_called()
        self.assertTrue(self.w.auto_entry_on_fill_both.isChecked())
        self.assertTrue(self.w.auto_sync_sl_tp_after_entry.isChecked())
        self.assertTrue(self.w.auto_draw_tv_after_entry.isChecked())
        self.w.auto_sync_sl_tp_after_entry.setChecked(False)
        self.assertFalse(self.w.store.data["ui"]["auto_sync_sl_tp_after_entry"])
        self.assertFalse(self.w.auto_draw_tv_after_entry.isChecked())
        self.assertFalse(self.w.auto_draw_tv_after_entry.isEnabled())
        self.assertFalse(self.w.store.data["ui"]["auto_draw_tv_after_entry"])

    def test_new_scheme_starts_disabled_and_old_scheme_remembers(self):
        original=self.w.profiles.active_name
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes):
            self.w.auto_entry_on_fill_both.setChecked(True)
            self.w.auto_fast_pair.setChecked(True)
            self.w.auto_sync_sl_tp_after_entry.setChecked(True)
            self.w.auto_draw_tv_after_entry.setChecked(True)
        self.assertTrue(self.w.auto_fast_pair.isChecked())
        with patch("trading_helper.gui.QInputDialog.getText",
                   return_value=("新的空白方案",True)), \
             patch("trading_helper.gui.QMessageBox.question") as dialogs:
            self.w.create_profile()
            dialogs.assert_not_called()
        self.assertEqual(self.w.profiles.active_name,"新的空白方案")
        for key in ("auto_entry_on_fill_both","auto_fast_pair",
                    "auto_sync_sl_tp_after_entry","auto_draw_tv_after_entry"):
            self.assertFalse(getattr(self.w,key).isChecked(),key)
            self.assertFalse(self.w.profiles.load_profile()["ui"][key])
            self.assertTrue(self.w.profiles.load_profile(original)["ui"][key])
        with patch("trading_helper.gui.QMessageBox.question") as dialogs, \
             patch.object(self.w, "read_sheet",return_value=None):
            self.w.switch_profile(original)
            dialogs.assert_not_called()
        for key in ("auto_entry_on_fill_both","auto_fast_pair",
                    "auto_sync_sl_tp_after_entry","auto_draw_tv_after_entry"):
            self.assertTrue(getattr(self.w,key).isChecked(),key)
        with patch.object(self.w,"read_sheet",return_value=None):
            self.w.switch_profile("新的空白方案")
        self.assertFalse(self.w.auto_entry_on_fill_both.isChecked())
        self.assertFalse(self.w.auto_fast_pair.isChecked())

    def test_bound_window_one_panel_no_double_questions(self):
        self.w._save_bound_window("MT5","external","old-bound-regex")
        with patch.object(gui.QMessageBox,"information") as info, \
             patch.object(gui.QMessageBox,"question") as ask:
            self.assertTrue(self.w.bind_role_window("external"))
            info.assert_not_called()
            ask.assert_not_called()
        box=self.w._window_binding_dialog
        self.assertEqual(box.objectName(),"singleWindowBindingDialog")
        self.assertIn("old-bound-regex",box.layout().itemAt(0).widget().text())
        self.assertEqual(box.findChild(QPushButton,"windowBindingChangeButton").text(),
                         "更改綁定")
        box.close()

    def test_binding_success_receipt_in_same_panel(self):
        from PySide6.QtWidgets import QLabel
        self.w._save_bound_window("MT5","external","old-bound-regex")
        self.w.bind_role_window("external")
        box=self.w._window_binding_dialog
        self.w._on_window_binding_result({
            "role":"external","platform":"MT5","ok":True,
            "old":"old-bound-regex","new":"new-bound-regex",
            "title":"Demo Terminal - XAUUSD"})
        receipt=box.findChild(QLabel,"windowBindingResultLabel").text()
        for part in ("已更改完成","old-bound-regex","new-bound-regex","Demo Terminal"):
            self.assertIn(part,receipt)
        self.assertIn("\n",receipt)
        self.assertTrue(box.findChild(QPushButton,"windowBindingChangeButton").isEnabled())
        box.close()

    def test_binding_result_is_topmost_and_reopens_if_broker_hides_it(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        self.w._save_bound_window("MT5","external","old-bound-regex")
        self.w.bind_role_window("external")
        box=self.w._window_binding_dialog
        self.assertFalse(bool(box.windowFlags() & Qt.WindowStaysOnTopHint))
        box.hide()
        self.w._on_window_binding_result({
            "role":"external","platform":"MT5","ok":True,
            "old":"old-bound-regex","new":"new-bound-regex",
            "title":"MT5 Demo Terminal"
        })
        self.qtapp.processEvents()
        self.assertTrue(bool(box.windowFlags() & Qt.WindowStaysOnTopHint))
        self.assertTrue(box.isVisible())
        self.assertIn("完成",box.windowTitle())
        self.assertIn("new-bound-regex",
                      box.findChild(QLabel,"windowBindingResultLabel").text())
        # A repeated capture disables topmost during the 3-second cursor
        # selection; its final receipt must become topmost again.
        with patch.object(self.w.windows,"window_at_cursor",
                          side_effect=RuntimeError("模擬擷取失敗")), \
             patch.object(gui.time,"sleep",return_value=None), \
             patch.object(self.w,"_start",side_effect=lambda name,task,**kw:task()):
            box.findChild(QPushButton,"windowBindingChangeButton").click()
            self.qtapp.processEvents()
        self.assertTrue(bool(box.windowFlags() & Qt.WindowStaysOnTopHint))
        self.assertIn("未完成",box.windowTitle())
        self.assertIn("未更改",box.findChild(QLabel,"windowBindingResultLabel").text())
        box.close()

    def test_simulated_window_capture_changes_binding_only(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QLabel
        self.w._save_bound_window("MT5","external","old-bound-regex")
        self.w.bind_role_window("external")
        box=self.w._window_binding_dialog
        with patch.object(self.w.windows,"window_at_cursor",
                          return_value=SimpleNamespace(title="ICMarkets Terminal - 7777")), \
             patch.object(gui.time,"sleep",return_value=None), \
             patch.object(self.w,"_start",side_effect=lambda name,task,**kw:task()), \
             patch.object(gui.QMessageBox,"question") as ask:
            box.findChild(QPushButton,"windowBindingChangeButton").click()
            self.qtapp.processEvents()
            ask.assert_not_called()
        self.assertIn(
            "ICMarkets",self.w.store.data["platforms"]["MT5"]["window_title"]["external"]
        )
        self.assertIn(
            "已更改完成",box.findChild(QLabel,"windowBindingResultLabel").text()
        )
        box.close()

    def test_failed_capture_keeps_existing_binding_and_shows_error_inline(self):
        from PySide6.QtWidgets import QLabel
        self.w._save_bound_window("MT5","external","old-bound-regex")
        self.w.bind_role_window("external")
        box=self.w._window_binding_dialog
        with patch.object(self.w.windows,"window_at_cursor",
                          side_effect=RuntimeError("無效視窗")), \
             patch.object(gui.time,"sleep",return_value=None), \
             patch.object(self.w,"_start",side_effect=lambda name,task,**kw:task()):
            box.findChild(QPushButton,"windowBindingChangeButton").click()
            self.qtapp.processEvents()
        self.assertEqual(
            self.w.store.data["platforms"]["MT5"]["window_title"]["external"],
            "old-bound-regex"
        )
        self.assertIn("未更改",box.findChild(QLabel,"windowBindingResultLabel").text())
        box.close()

    def test_confirmed_fast_pair_preference_persists_without_repeat_prompt(self):
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes):
            self.w.auto_entry_on_fill_both.setChecked(True)
            self.w.auto_fast_pair.setChecked(True)
            self.w.auto_sync_sl_tp_after_entry.setChecked(True)
        self.assertTrue(self.w.store.data["ui"]["auto_fast_pair"])
        self.assertTrue(self.w.profiles.load_profile()["ui"]["auto_fast_pair"])
        with patch("trading_helper.gui.QMessageBox.question") as prompt:
            self.w._apply_profile_ui()
            prompt.assert_not_called()
        self.assertTrue(self.w.auto_entry_on_fill_both.isChecked())
        self.assertTrue(self.w.auto_fast_pair.isChecked())
        self.assertTrue(self.w.auto_sync_sl_tp_after_entry.isChecked())
        self.assertFalse(self.w.auto_draw_tv_after_entry.isChecked())
        self.w.auto_fast_pair.setChecked(False)
        self.assertFalse(self.w.profiles.load_profile()["ui"]["auto_fast_pair"])

    def test_tradingview_main_badge_follows_saved_points_and_display_switch(self):
        from trading_helper.calibration_status import completion
        targets=gui.CALIBRATION_TARGETS
        def saved():
            return {"x":.4,"y":.5}
        platforms=self.w.store.data["platforms"]
        for plat in ("cTrader","MT5","TradingView"):
            platforms[plat]["points"]={k:saved() for k,_ in targets[plat]}
        platforms["TradingView"]["points"].pop(targets["TradingView"][0][0])
        self.w.switch_workspace("編輯")
        self.w.show_calibration_badges.setChecked(True)
        self.w._refresh_calibration_badges()
        self.qtapp.processEvents()
        dots=self.w._calibration_badge_labels
        tv=dots[self.w.action_buttons["校準 TradingView"]]
        edit=dots[self.w.page_nav["編輯"]]
        self.assertTrue(tv.isVisible())
        self.assertTrue(edit.isVisible())
        self.assertFalse(dots[self.w.action_buttons["校準 cTrader"]].isVisible())
        self.assertFalse(dots[self.w.action_buttons["校準 MT5"]].isVisible())
        self.assertEqual(
            completion(platforms["TradingView"]["points"],
                       [k for k,_ in targets["TradingView"]]),(7,8))
        self.w.show_calibration_badges.setChecked(False)
        self.qtapp.processEvents()
        self.assertFalse(tv.isVisible())
        self.assertFalse(edit.isVisible())

    def test_unchecking_first_cascades_and_can_restore_sequentially(self):
        first=self.w.auto_entry_on_fill_both
        second=self.w.auto_sync_sl_tp_after_entry
        third=self.w.auto_draw_tv_after_entry
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes):
            first.setChecked(True)
            second.setChecked(True)
            third.setChecked(True)
        self.assertTrue(all(c.isChecked() for c in (first, second, third)))
        self.assertTrue(all(c.isEnabled() for c in (first, second, third)))
        first.setChecked(False)
        self.assertFalse(any(c.isChecked() for c in (first, second, third)))
        self.assertFalse(second.isEnabled())
        self.assertFalse(third.isEnabled())
        self.assertFalse(any(self.w.store.data["ui"].get(k)
                             for k in (
                                 "auto_entry_on_fill_both",
                                 "auto_sync_sl_tp_after_entry",
                                 "auto_draw_tv_after_entry"
                             )))
        with patch("trading_helper.gui.QMessageBox.question") as prompt:
            third.setChecked(True)
            second.setChecked(True)
            prompt.assert_not_called()
        self.assertFalse(second.isChecked())
        self.assertFalse(third.isChecked())
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes):
            first.setChecked(True)
            second.setChecked(True)
            third.setChecked(True)
        second.setChecked(False)
        self.assertTrue(first.isChecked())
        self.assertFalse(second.isChecked())
        self.assertFalse(third.isChecked())
        self.assertTrue(second.isEnabled())
        self.assertFalse(third.isEnabled())

    def test_invalid_saved_options_are_normalized_on_profile_restore(self):
        ui=self.w.store.data["ui"]
        ui.update({
            "auto_entry_on_fill_both":False,
            "auto_sync_sl_tp_after_entry":True,
            "auto_draw_tv_after_entry":True,
        })
        with patch("trading_helper.gui.QMessageBox.question") as prompt:
            self.w._apply_profile_ui()
            prompt.assert_not_called()
        self.assertFalse(self.w.auto_entry_on_fill_both.isChecked())
        self.assertFalse(self.w.auto_sync_sl_tp_after_entry.isChecked())
        self.assertFalse(self.w.auto_draw_tv_after_entry.isChecked())
        self.assertFalse(ui["auto_sync_sl_tp_after_entry"])
        self.assertFalse(ui["auto_draw_tv_after_entry"])
        ui.update({
            "auto_entry_on_fill_both":True,
            "auto_sync_sl_tp_after_entry":False,
            "auto_draw_tv_after_entry":True,
        })
        self.w._apply_profile_ui()
        self.assertTrue(self.w.auto_entry_on_fill_both.isChecked())
        self.assertTrue(self.w.auto_sync_sl_tp_after_entry.isEnabled())
        self.assertFalse(self.w.auto_sync_sl_tp_after_entry.isChecked())
        self.assertFalse(self.w.auto_draw_tv_after_entry.isEnabled())
        self.assertFalse(self.w.auto_draw_tv_after_entry.isChecked())
        self.assertFalse(ui["auto_draw_tv_after_entry"])

    def test_manual_buttons_remain_independent_of_auto_preferences(self):
        self.w.switch_workspace("交易")
        names={"manualSyncSlTp":"手動同步場外 SL/TP",
               "manualDrawTv":"手動繪製 TV"}
        for object_name,text in names.items():
            btn=self.w.findChild(QPushButton,object_name)
            self.assertIsNotNone(btn)
            self.assertEqual(btn.text(),text)
            self.assertTrue(btn.isVisible())
            self.assertTrue(btn.isEnabled())
            self.assertIn(btn,self.w._hover_help._details)
        self.assertIn("self.sync_external_sl_tp",
                      inspect.getsource(gui.TradingHelperApp._build))
        self.assertIn("self.draw_tradingview",
                      inspect.getsource(gui.TradingHelperApp._build))

    def test_future_options_never_trigger_trade_actions(self):
        fill_code=inspect.getsource(gui.TradingHelperApp.fill_both)
        task_code=inspect.getsource(gui.TradingHelperApp._fill_both_task)
        for keyword in ("auto_sync_sl_tp_after_entry","auto_draw_tv_after_entry"):
            self.assertNotIn(keyword,fill_code)
            self.assertNotIn(keyword,task_code)
        operations=SimpleNamespace(fill=MagicMock())
        pending=MagicMock()
        fake=SimpleNamespace(
            _require_instruction=lambda:"sample-no-broker",
            automation=operations,
            _auto_entry_after_fill_both_pending=pending,
        )
        gui.TradingHelperApp._fill_both_task(fake,"cTrader","MT5",False)
        self.assertEqual(operations.fill.call_count,2)
        pending.assert_not_called()

    def test_no_missing_manual_entry_price_or_history_access(self):
        self.w.switch_workspace("編輯")
        self.assertFalse(self.w.entry_price_input.isVisible())
        button=self.w.findChild(QPushButton,"applyManualEntryPrice")
        self.assertIsNotNone(button)
        self.assertFalse(button.isVisible())
        self.assertFalse(self.w.entry_price_value.isVisible())
        self.w.switch_workspace("紀錄")
        self.assertFalse(self.w.daily_pnl_history_button.isVisible())
        self.assertTrue(self.w.log_text.isVisible())
        self.w.switch_workspace("交易")
        self.assertTrue(self.w.parameter_inputs["internal_entry_price"].isVisible())
        self.assertFalse(self.w.log_text.isVisible())
        self.assertTrue(self.w.recent_status.isVisible())

    def test_no_scroll_and_information_combined(self):
        self.assertEqual(len(self.w.data_labels),11)
        self.assertEqual(len(self.w.parameter_inputs),4)
        from PySide6.QtWidgets import QScrollArea, QGroupBox, QWidget
        self.assertFalse(self.w.main_pages.findChildren(QScrollArea))
        self.assertIsNotNone(self.w.trade_page.findChild(QGroupBox,"dataCard"))
        self.assertIsNotNone(self.w.trade_page.findChild(QWidget,"platformSelectorRow"))
        self.assertIsNotNone(self.w.trade_page.findChild(QWidget,"sheetDataValues"))
        self.assertFalse(self.w.trade_page.findChildren(QGroupBox,"platformCard"))
        self.assertTrue(self.w.profile_combo.isVisible())
        self.assertEqual(self.w.profile_combo.toolTip(),
                         self.w.profile_combo.currentText())
        group=self.w.trade_page.findChild(QGroupBox,"afterEntryCard")
        self.assertIsNotNone(group)
        self.assertLessEqual(group.maximumHeight(),90)
        for control_name in ("manualSyncSlTp","manualDrawTv"):
            button=self.w.findChild(QPushButton,control_name)
            self.assertTrue(button.isVisible())
            self.assertTrue(group.isAncestorOf(button))

if __name__=="__main__":
    unittest.main()
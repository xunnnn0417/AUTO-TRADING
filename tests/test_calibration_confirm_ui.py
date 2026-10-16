"""Qt opt-in workflow tests; no broker interaction and only temp config files."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication, QMainWindow, QDialog, QMessageBox

import trading_helper.gui as gui
from trading_helper.gui import CalibrationDialog
from trading_helper.calibration_scan import ScanReport, Candidate
from trading_helper.windows import WindowInfo


class ConfirmSaveQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp=QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent=QMainWindow()
        self.dialog=CalibrationDialog(self.parent,"cTrader")
        self.win=WindowInfo(500,"cTrader",100,200,1100,800)
        self.report=ScanReport("cTrader",(
            ("lot_input","手數"),("sl_input","止損點數")
        ))
        self.report.candidates={
            "lot_input":Candidate("lot_input",(505,320,595,340),"UIA"),
            "sl_input":Candidate("sl_input",(610,350,730,370),"低信度 UIA"),
        }
        self.dialog._inventory_scan_context={
            "window":self.win,"pid":7788,"platform":"cTrader","role":"internal"
        }
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder=Path(self.tmp.name)
        data={"platforms":{
            "cTrader":{"points":{"tp_input":{"x_px":999}},
                       "window_title":{"internal":"cTrader","external":"cTrader"}},
            "GooeyTrade":{"points":{}},
            "MT5":{"points":{"lot_input":{"x_px":333}}},
        }}
        profiles={"active":"One","profiles":{"One":copy.deepcopy(data),"Two":copy.deepcopy(data)}}
        (folder/"config.json").write_text(json.dumps(data),encoding="utf-8")
        (folder/"profiles.json").write_text(json.dumps(profiles),encoding="utf-8")
        self.parent.store=SimpleNamespace(data=data,path=folder/"config.json")
        self.parent.profiles=SimpleNamespace(data=profiles,path=folder/"profiles.json",active_name="One")
        self.parent.automation=SimpleNamespace(config=data)
        self.parent.windows=SimpleNamespace(list_windows=lambda:[self.win])
        self.parent.log=lambda _:None

    def tearDown(self):
        self.dialog._hover_outline.close()
        self.dialog.close()
        self.parent.close()

    def _preview(self,instance,report):
        callbacks=[]
        with patch.object(gui.QTimer,"singleShot",side_effect=lambda ms,cb:callbacks.append(cb)), \
             patch.object(gui,"CandidateOutline") as overlays, \
             patch.object(instance,"showMinimized"), \
             patch.object(self.dialog,"showMinimized"), \
             patch.object(self.parent,"showMinimized"), \
             patch.object(instance,"showNormal"), \
             patch.object(self.dialog,"showNormal"), \
             patch.object(self.parent,"showNormal"), \
             patch.object(instance,"raise_"), \
             patch.object(instance,"activateWindow"):
            self.dialog.preview_all_inventory_candidates(instance,report)
            self.assertEqual(len(callbacks),2)
            callbacks[0]()
            self.assertEqual(overlays.call_count,2)
            callbacks[1]()

    def test_unchecked_after_preview_select_all_clear_and_cancel(self):
        def inspect(instance):
            state=self.dialog._inventory_save_preview
            self.assertFalse(state["save_button"].isEnabled())
            self.assertTrue(all(not cb.isChecked() for cb in state["checkboxes"].values()))
            self.assertTrue(all(not cb.isEnabled() for cb in state["checkboxes"].values()))
            self.assertFalse(state["select_all_button"].isEnabled())
            self._preview(instance,self.report)
            self.assertTrue(state["previewed"])
            self.assertTrue(all(cb.isEnabled() for cb in state["checkboxes"].values()))
            self.assertFalse(state["save_button"].isEnabled())
            state["select_all_button"].click()
            self.assertTrue(all(cb.isChecked() for cb in state["checkboxes"].values()))
            self.assertTrue(state["save_button"].isEnabled())
            state["clear_button"].click()
            self.assertFalse(state["save_button"].isEnabled())
            state["checkboxes"]["lot_input"].setChecked(True)
            self.assertTrue(state["save_button"].isEnabled())
            # User chooses No: not a single file update is requested.
            with patch.object(gui.QMessageBox,"question",return_value=QMessageBox.No), \
                 patch.object(gui,"save_confirmed_points") as persist:
                state["save_button"].click()
                persist.assert_not_called()
            return 0
        with patch.object(gui.QDialog,"exec",inspect):
            self.dialog._finish_inventory(self.report)
        self.assertIsNone(self.dialog._inventory_save_preview)
        self.assertIsNone(self.dialog._inventory_scan_context)

    def test_explicit_yes_saves_only_checked_not_low_confidence(self):
        def inspect(instance):
            state=self.dialog._inventory_save_preview
            self._preview(instance,self.report)
            state["checkboxes"]["lot_input"].setChecked(True)
            self.assertFalse(state["checkboxes"]["sl_input"].isChecked())
            with patch.object(gui.QMessageBox,"question",return_value=QMessageBox.Yes), \
                 patch.object(gui,"inspect_all_targets",return_value=self.report), \
                 patch.object(gui,"process_id_for_window",return_value=7788):
                state["save_button"].click()
            self.assertTrue(state["saved"])
            self.assertFalse(state["save_button"].isEnabled())
            self.assertIn("已儲存 1 個",state["status"].text())
            self.assertEqual(instance.result(), QDialog.Accepted)
            return 0
        with patch.object(gui.QDialog,"exec",inspect):
            self.dialog._finish_inventory(self.report)
        self.assertEqual(QDialog.result(self.dialog), QDialog.Accepted)
        updated=json.loads(self.parent.store.path.read_text(encoding="utf-8"))
        self.assertEqual(updated["platforms"]["cTrader"]["points"]["lot_input"]["x_px"],450)
        self.assertEqual(updated["platforms"]["cTrader"]["points"]["tp_input"]["x_px"],999)
        self.assertNotIn("sl_input",updated["platforms"]["cTrader"]["points"])
        self.assertEqual(updated["platforms"]["MT5"]["points"]["lot_input"]["x_px"],333)

    def test_visual_low_confidence_is_selectable_after_preview(self):
        # "Low confidence" is an acknowledgement requirement, not an error.
        # Previously the visual fallback added an informational warning,
        # which unintentionally kept these checkboxes disabled forever.
        self.report.candidates["sl_input"]=Candidate(
            "sl_input",(610,350,730,370),
            "低信度：MT5 畫面色塊候選；請人工核對黃色框",
        )
        self.assertFalse(self.report.warnings)
        def inspect(instance):
            state=self.dialog._inventory_save_preview
            self.assertFalse(state["checkboxes"]["sl_input"].isEnabled())
            self._preview(instance,self.report)
            low=state["checkboxes"]["sl_input"]
            self.assertTrue(low.isEnabled())
            self.assertFalse(low.isChecked())
            low.click()
            self.assertTrue(low.isChecked())
            self.assertTrue(state["save_button"].isEnabled())
            with patch.object(gui.QMessageBox,"question",
                              return_value=QMessageBox.Yes), \
                 patch.object(gui,"inspect_all_targets",
                              return_value=self.report), \
                 patch.object(gui,"process_id_for_window",return_value=7788):
                state["save_button"].click()
            self.assertTrue(state["saved"])
            return 0
        with patch.object(gui.QDialog,"exec",inspect):
            self.dialog._finish_inventory(self.report)
        self.assertEqual(QDialog.result(self.dialog),QDialog.Accepted)

    def test_moved_candidates_are_rejected_without_writing(self):
        original=self.parent.store.path.read_bytes()
        def inspect(instance):
            state=self.dialog._inventory_save_preview
            self._preview(instance,self.report)
            state["checkboxes"]["lot_input"].setChecked(True)
            moved=ScanReport("cTrader",self.report.targets)
            moved.candidates=dict(self.report.candidates)
            moved.candidates["lot_input"]=Candidate(
                "lot_input",(510,320,600,340),"UIA"
            )
            with patch.object(gui.QMessageBox,"question",return_value=QMessageBox.Yes), \
                 patch.object(gui,"inspect_all_targets",return_value=moved), \
                 patch.object(gui.QMessageBox,"warning") as alert:
                state["save_button"].click()
                self.assertTrue(alert.called)
            self.assertFalse(state["saved"])
            return 0
        with patch.object(gui.QDialog,"exec",inspect):
            self.dialog._finish_inventory(self.report)
        self.assertEqual(self.parent.store.path.read_bytes(),original)

    def test_ctrader_position_stage_uses_same_native_scanner_when_saving(self):
        report=ScanReport("cTrader",tuple((k,k) for k in gui.POSITION_GRID_KEYS))
        report.candidates={
            "positions_entry_price":Candidate(
                "positions_entry_price",(410,310,490,338),"native header"
            ),
            "position_order_lot":Candidate(
                "position_order_lot",(510,310,590,338),"native header"
            ),
            "position_order_row":Candidate(
                "position_order_row",(610,310,700,338),"native TP column"
            ),
        }
        def inspect(instance):
            state=self.dialog._inventory_save_preview
            state["previewed"]=True
            for cb in state["checkboxes"].values():
                cb.setEnabled(True)
            state["checkboxes"]["positions_entry_price"].setChecked(True)
            with patch.object(gui.QMessageBox,"question",
                              return_value=QMessageBox.Yes), \
                 patch.object(gui,"scan_position_grid",return_value=report) as grid, \
                 patch.object(gui,"inspect_all_targets") as generic, \
                 patch.object(gui,"process_id_for_window",return_value=7788):
                state["save_button"].click()
            grid.assert_called_once_with(self.win.handle,"cTrader",report.targets)
            generic.assert_not_called()
            self.assertTrue(state["saved"])
            self.assertEqual(instance.result(),QDialog.Accepted)
            return 0
        with patch.object(gui.QDialog,"exec",inspect):
            self.dialog._finish_inventory(report)
        stored=json.loads(self.parent.store.path.read_text(encoding="utf-8"))
        self.assertIn("positions_entry_price",stored["platforms"]["cTrader"]["points"])

    def test_mt5_position_edit_stage_uses_same_native_scanner_when_saving(self):
        parent=QMainWindow()
        parent.log=lambda _message:None
        dialog=CalibrationDialog(parent,"MT5")
        win=WindowInfo(700,"持倉: #8765432101 buy 0.16 XAUUSD",200,200,1400,850)
        report=ScanReport("MT5",tuple((k,k) for k in gui.POSITION_EDIT_KEYS))
        report.candidates={
            "position_sl_input":Candidate(
                "position_sl_input",(510,350,600,376),"10334 native Edit"
            ),
            "position_tp_input":Candidate(
                "position_tp_input",(510,385,600,411),"10336 native Edit"
            ),
            "position_modify_confirm":Candidate(
                "position_modify_confirm",(700,690,1000,720),"10351 native Button"
            ),
        }
        dialog._inventory_scan_context={
            "window":win,"pid":8888,"platform":"MT5","role":"external",
        }
        parent.windows=SimpleNamespace(list_windows=lambda:[win])
        def inspect(instance):
            state=dialog._inventory_save_preview
            state["previewed"]=True
            for cb in state["checkboxes"].values():
                cb.setEnabled(True)
            state["checkboxes"]["position_sl_input"].setChecked(True)
            state["checkboxes"]["position_modify_confirm"].setChecked(True)
            with patch.object(gui.QMessageBox,"question",
                              return_value=QMessageBox.Yes), \
                 patch.object(gui,"scan_open_modify_dialog",return_value=report) as modify, \
                 patch.object(gui,"inspect_all_targets") as generic, \
                 patch.object(gui,"process_id_for_window",return_value=8888), \
                 patch.object(gui,"save_confirmed_points") as saved, \
                 patch.object(gui.QMessageBox,"warning") as warning:
                state["save_button"].click()
            self.assertFalse(warning.called, str(warning.call_args))
            modify.assert_called_once_with(win.handle,"MT5",report.targets)
            generic.assert_not_called()
            saved.assert_called_once()
            self.assertTrue(state["saved"])
            return 0
        try:
            with patch.object(gui.QDialog,"exec",inspect):
                dialog._finish_inventory(report)
        finally:
            dialog._hover_outline.close()
            dialog.close()
            parent.close()

    def test_native_recheck_changed_rectangle_blocks_all_writes(self):
        report=ScanReport("cTrader",tuple((k,k) for k in gui.POSITION_GRID_KEYS))
        report.candidates={
            key:Candidate(key,(400+idx*100,320,490+idx*100,346),"native")
            for idx,key in enumerate(gui.POSITION_GRID_KEYS)
        }
        changed=ScanReport("cTrader",report.targets)
        changed.candidates=dict(report.candidates)
        changed.candidates["positions_entry_price"]=Candidate(
            "positions_entry_price",(404,320,494,346),"moved"
        )
        original=self.parent.store.path.read_bytes()
        def inspect(instance):
            state=self.dialog._inventory_save_preview
            state["previewed"]=True
            for cb in state["checkboxes"].values():
                cb.setEnabled(True)
            state["checkboxes"]["positions_entry_price"].setChecked(True)
            with patch.object(gui.QMessageBox,"question",
                              return_value=QMessageBox.Yes), \
                 patch.object(gui,"scan_position_grid",return_value=changed), \
                 patch.object(gui,"save_confirmed_points") as saved, \
                 patch.object(gui.QMessageBox,"warning") as warning:
                state["save_button"].click()
                self.assertTrue(warning.called)
                saved.assert_not_called()
            self.assertFalse(state["saved"])
            return 0
        with patch.object(gui.QDialog,"exec",inspect):
            self.dialog._finish_inventory(report)
        self.assertEqual(self.parent.store.path.read_bytes(),original)

if __name__=="__main__":
    unittest.main()

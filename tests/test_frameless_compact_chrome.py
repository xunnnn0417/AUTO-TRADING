"""Frameless compact header regression. All GUI data isolated and offscreen."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QCheckBox
from trading_helper import gui
from trading_helper.window_chrome import CompactTitleBar, WindowChromeButton, edge_hit_test


class EdgeHitTest(unittest.TestCase):
    def test_corners_edges_center(self):
        rect=(50,60,450,360)
        expected={
            (50,60):13, (449,60):14,
            (50,359):16, (449,359):17,
            (50,200):10, (449,200):11,
            (200,60):12, (200,359):15,
            (200,200):1,(12,200):1
        }
        for (x,y),value in expected.items():
            self.assertEqual(edge_hit_test(x,y,rect),value)


class FramelessHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config=Path(tmp.name)/"config.json"
        profiles=Path(tmp.name)/"profiles.json"
        config_type=gui.ConfigStore
        profiles_type=gui.ProfileStore
        with patch.object(gui,"ConfigStore",side_effect=lambda:config_type(path=config)),\
             patch.object(gui,"ProfileStore",side_effect=lambda x:profiles_type(x,path=profiles)),\
             patch.object(gui.WindowController,"warm_ocr",return_value=None),\
             patch.object(gui.TradingHelperApp,"read_sheet",lambda _:None):
            self.w=gui.TradingHelperApp()
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def test_one_row_and_original_controls(self):
        w=self.w
        self.assertTrue(w.windowFlags() & Qt.FramelessWindowHint)
        self.assertIs(w.menuWidget(),w.title_bar)
        self.assertIsInstance(w.title_bar,CompactTitleBar)
        self.assertEqual(w.title_bar.height(),39)
        # Compact trade page must fit the ruler with reduced empty footer.
        self.assertEqual(w.minimumHeight(),630)
        self.assertGreaterEqual(w.height(),630)
        self.assertLessEqual(w.width(),1150)
        for role in ("minimize","maximize","close"):
            button=getattr(w,"chrome_"+role)
            self.assertIsInstance(button,WindowChromeButton)
            self.assertEqual(button.objectName(),"chrome_"+role)
            self.assertTrue(button.isVisible())
        self.assertEqual(w.auto_entry_on_fill_both.text(),"自動進場")
        self.assertFalse(w.auto_entry_on_fill_both.isChecked())
        self.assertEqual(w.auto_entry_on_fill_both.parent().objectName(),"automationOptionRow")
        self.assertTrue(w.profile_combo.isVisible())
        self.assertTrue(w.sheet_note_indicator.isVisible())
        self.assertTrue(w.profile_manage_button.isVisible())
        self.assertTrue(w.display_settings_button.isVisible())
        self.assertEqual(len([
            b for b in w.findChildren(QPushButton) if b.text()=="打開試算表"
        ]),1)
        self.assertNotIn("送單流程待設定",[x.text() for x in w.findChildren(gui.QLabel)])
        self.assertIn("可能真的",w.auto_entry_on_fill_both.toolTip())
        self.assertIn("不會重複送單",w.auto_entry_on_fill_both.toolTip())
        # Content follows the single titlebar row; there is no second full
        # height settings strip in the main scroll area.
        self.assertIsNone(w.findChild(gui.QFrame,"headerCard"))

    def test_window_controls_minimize_restore_maximize_and_restore(self):
        w=self.w
        normal=w.geometry()
        w.chrome_maximize.click()
        self.app.processEvents()
        self.assertTrue(w.isMaximized())
        w.chrome_maximize.click()
        self.app.processEvents()
        self.assertFalse(w.isMaximized())
        w.chrome_minimize.click()
        self.app.processEvents()
        self.assertTrue(w.isMinimized())
        w.showNormal()
        self.app.processEvents()
        self.assertFalse(w.isMinimized())
        self.assertFalse(w.isMaximized())
        self.assertTrue(w.isVisible())

    def test_always_on_top_does_not_replace_frameless_chrome(self):
        w=self.w
        original=w.geometry()
        w.set_always_on_top(True)
        self.app.processEvents()
        self.assertTrue(w.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(w.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(w.geometry().size(),original.size())
        self.assertTrue(w.title_bar.isVisible())
        w.set_always_on_top(False)
        self.app.processEvents()
        self.assertFalse(w.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(w.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(w.geometry().size(),original.size())

    def test_sheet_note_popup_retained_across_paints(self):
        note=self.w.sheet_note_indicator
        note.set_note("QA synthetic reminder")
        popup=note._popup
        text_widget=note._popup_text
        self.assertEqual(text_widget.toPlainText(),"QA synthetic reminder")
        note.repaint()
        note.repaint()
        self.app.processEvents()
        self.assertIs(note._popup,popup)
        self.assertIs(note._popup_text,text_widget)


if __name__=="__main__":
    unittest.main()

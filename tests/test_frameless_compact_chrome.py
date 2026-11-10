"""Frameless compact header regression. All GUI data isolated and offscreen."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QPushButton, QCheckBox, QToolButton
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
        self.temp_dir=Path(tmp.name)
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
        self.assertEqual(w.minimumHeight(),660)
        self.assertGreaterEqual(w.height(),660)
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
        self.assertEqual(w.geometry(),normal)
        w.chrome_minimize.click()
        self.app.processEvents()
        self.assertTrue(w.isMinimized())
        w.showNormal()
        self.app.processEvents()
        self.assertFalse(w.isMinimized())
        self.assertFalse(w.isMaximized())
        self.assertTrue(w.isVisible())

    def test_message_box_uses_shared_titlebar_and_surface(self):
        box=gui.QMessageBox(self.w)
        box.setWindowTitle("校準提醒")
        box.setIcon(gui.QMessageBox.Warning)
        box.setText("請確認平台視窗。")
        box.show()
        self.app.processEvents()
        title=box.findChild(gui.QLabel,"dialogTitle")
        icon=box.findChild(gui.QLabel,"messageIcon")
        title_bar=box.findChild(gui.QFrame,"compactTitleBar")
        self.assertIsNotNone(title)
        self.assertEqual(title.text(),"校準提醒")
        self.assertEqual(icon.property("severity"),"warning")
        self.assertIsNotNone(title_bar)
        self.assertEqual(title_bar.geometry().x(),0)
        self.assertEqual(title_bar.geometry().width(),box.width())
        margins=box.layout().contentsMargins()
        self.assertEqual(
            (margins.left(),margins.top(),margins.right(),margins.bottom()),
            (18,14,18,12),
        )
        self.assertIsNotNone(box.findChild(WindowChromeButton,"chrome_close"))
        self.assertIsNone(box.findChild(WindowChromeButton,"chrome_minimize"))
        self.assertIsNone(box.findChild(WindowChromeButton,"chrome_maximize"))
        self.assertIn("#101014",box.styleSheet())
        box.close()

    def test_settings_dialog_matches_calibration_chrome_and_hides_fixed_options(self):
        dialog=gui.SettingsDialog(self.w)
        dialog.show()
        self.app.processEvents()
        tabs=dialog.findChild(gui.QTabWidget,"settingsTabs")
        self.assertEqual(tabs.count(),2)
        self.assertEqual(
            [tabs.tabText(i) for i in range(tabs.count())],
            ["Google 試算表","預設設定"],
        )
        self.assertEqual(dialog.windowTitle(),"試算表設定")
        title_label=dialog.findChild(gui.QLabel,"dialogTitle")
        self.assertIsNotNone(title_label)
        self.assertEqual(title_label.text(),"試算表設定")
        dialog.setWindowTitle("更新標題測試")
        self.assertEqual(title_label.text(),"更新標題測試")
        dialog.setWindowTitle("試算表設定")
        self.assertIsNotNone(dialog.findChild(WindowChromeButton,"chrome_close"))
        self.assertIsNone(dialog.findChild(WindowChromeButton,"chrome_minimize"))
        self.assertIsNone(dialog.findChild(WindowChromeButton,"chrome_maximize"))
        self.assertFalse(dialog.windowFlags() & Qt.WindowMinimizeButtonHint)
        self.assertNotIn("mode",dialog.sheet_fields)
        self.assertNotIn("data_layout",dialog.sheet_fields)
        self.assertNotIn("worksheet",dialog.sheet_fields)
        self.assertNotIn("gid",dialog.sheet_fields)
        self.assertNotIn("row_number",dialog.sheet_fields)
        self.assertNotIn("status_value",dialog.sheet_fields)
        self.assertIsNotNone(dialog.findChild(gui.QGroupBox,"sheetColumnsDefaults"))
        self.assertIsNotNone(dialog.findChild(gui.QGroupBox,"windowDefaults"))
        self.assertIsNotNone(dialog.findChild(gui.QGroupBox,"ctraderSlTpDefaults"))
        self.assertTrue(dialog.sheet_tab_badge.isVisible())
        self.assertEqual(
            tabs.tabBar().tabButton(0, gui.QTabBar.RightSide),
            dialog.sheet_tab_badge,
        )
        self.assertEqual(
            (dialog.sheet_tab_badge.width(), dialog.sheet_tab_badge.height()),
            (6, 6),
        )
        self.assertIn("尚未填入網址", tabs.tabToolTip(0))
        self.assertIsNone(dialog.findChild(QToolButton,"sheetSetupHelpBadge"))
        url=dialog.sheet_fields["spreadsheet_url"]
        clear_button=url.findChild(QToolButton,"lineEditClearButton")
        self.assertIsNotNone(clear_button)
        self.assertFalse(clear_button.isVisible())
        url.setText("https://docs.google.com/spreadsheets/d/example")
        self.app.processEvents()
        self.assertFalse(dialog.sheet_tab_badge.isVisible())
        self.assertNotIn("尚未填入網址", tabs.tabToolTip(0))
        self.assertTrue(clear_button.isVisible())
        self.assertLessEqual(
            abs(clear_button.y() * 2 + clear_button.height() - url.height()), 1
        )
        image = QImage(clear_button.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        clear_button.render(image)
        drawn = [
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        ]
        self.assertTrue(drawn)
        self.assertLessEqual(
            abs(min(x for x, _ in drawn) + max(x for x, _ in drawn)
                - (image.width() - 1)),
            2,
        )
        self.assertLessEqual(
            abs(min(y for _, y in drawn) + max(y for _, y in drawn)
                - (image.height() - 1)),
            2,
        )
        clear_button.click()
        self.assertEqual(url.text(),"")
        self.assertFalse(clear_button.isVisible())
        self.assertTrue(dialog.sheet_tab_badge.isVisible())
        url.setText(
            "https://docs.google.com/spreadsheets/d/example/edit#gid=11111111"
        )
        self.assertIn("11111111",dialog.gid_preview.text())
        key_file=self.temp_dir/"service-account.json"
        key_file.write_text(
            '{"client_email":"synthetic-service@example.invalid"}',
            encoding="utf-8",
        )
        dialog.sheet_fields["service_account_file"].setText(str(key_file))
        self.assertIn(
            "synthetic-service@example.invalid",
            dialog.credential_email.text(),
        )
        self.assertFalse(dialog.sheet_tab_badge.isVisible())
        dialog.close()

    def test_service_account_picker_uses_shared_popup_chrome(self):
        settings=gui.SettingsDialog(self.w)
        dialog,picker=settings._create_service_account_file_dialog()
        self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(dialog.windowTitle(),"選擇服務帳戶 JSON")
        self.assertIsNotNone(dialog.findChild(gui.QLabel,"dialogTitle"))
        self.assertIsNotNone(dialog.findChild(WindowChromeButton,"chrome_close"))
        self.assertTrue(picker.testOption(gui.QFileDialog.DontUseNativeDialog))
        self.assertFalse(picker.isWindow())
        self.assertIs(picker.parentWidget(),dialog)
        dialog.close()
        dialog.deleteLater()
        settings.close()

    def test_open_calibration_hides_main_and_restores_its_geometry(self):
        w=self.w
        original=w.geometry()
        dialog_class=gui.CalibrationDialog
        opened=[]

        def create_dialog(parent,platform):
            self.assertTrue(parent.isHidden())
            self.assertEqual(platform,"MT5")
            dialog=dialog_class(parent,platform)
            opened.append(dialog)
            def finish():
                self.assertTrue(dialog.isVisible())
                self.assertTrue(parent.isHidden())
                dialog.accept()
            QTimer.singleShot(0,finish)
            return dialog

        with patch.object(gui,"CalibrationDialog",side_effect=create_dialog):
            w.open_calibration("MT5")
        self.app.processEvents()
        self.assertTrue(w.isVisible())
        self.assertFalse(w.isMinimized())
        self.assertEqual(w.geometry(),original)
        self.assertFalse(w._calibration_dialog_active)
        self.assertEqual(len(opened),1)
        opened[0]._hover_outline.close()

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

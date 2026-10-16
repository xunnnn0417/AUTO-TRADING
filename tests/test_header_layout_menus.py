"""Two-row test interface: menu wiring and display controls, using temp configs only."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication, QToolButton, QWidgetAction

import trading_helper.gui as gui


class HeaderMenuLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config=Path(self.tmp.name)/"ui-config.json"
        self.profiles=Path(self.tmp.name)/"ui-profiles.json"
        self.events=[]
        config_type=gui.ConfigStore
        profile_type=gui.ProfileStore
        with patch.object(gui,"ConfigStore",side_effect=lambda:config_type(path=self.config)), \
             patch.object(gui,"ProfileStore",side_effect=lambda x:profile_type(x,path=self.profiles)), \
             patch.object(gui.WindowController,"warm_ocr",return_value=None), \
             patch.object(gui.TradingHelperApp,"read_sheet",lambda _:None), \
             patch.object(gui.TradingHelperApp,"create_profile",lambda _:self.events.append("create")), \
             patch.object(gui.TradingHelperApp,"save_current_profile",lambda _:self.events.append("save")), \
             patch.object(gui.TradingHelperApp,"rename_profile",lambda _:self.events.append("rename")), \
             patch.object(gui.TradingHelperApp,"delete_profile",lambda _:self.events.append("delete")):
            self.window=gui.TradingHelperApp()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_management_menu_all_four_actions_still_work(self):
        manage=self.window.profile_manage_button
        self.assertIsInstance(manage,QToolButton)
        self.assertEqual(manage.popupMode(),QToolButton.InstantPopup)
        menu=manage.menu()
        self.assertIs(menu,self.window.profile_manage_menu)
        labels=[a.text() for a in menu.actions() if not a.isSeparator()]
        self.assertEqual(labels,[
            "建立新方案","儲存目前方案","重新命名目前方案","刪除目前方案"
        ])
        for action in menu.actions():
            if not action.isSeparator():
                action.trigger()
        self.assertEqual(self.events,["create","save","rename","delete"])

    def test_phase1_flat_toolbar_preserves_actions_and_native_window_chrome(self):
        from PySide6.QtWidgets import QPushButton, QToolButton, QFrame
        from trading_helper.gui import ToolbarMenuButton, DraggableProfileCombo
        from PySide6.QtCore import Qt
        w=self.window
        self.assertIsInstance(w.profile_manage_button, ToolbarMenuButton)
        self.assertIsInstance(w.display_settings_button, ToolbarMenuButton)
        self.assertIsInstance(w.profile_combo, DraggableProfileCombo)
        self.assertEqual(w.profile_combo.objectName(),"headerProfileCombo")
        self.assertIsNotNone(w.findChild(QFrame,"compactTitleBar"))
        help_buttons=[b for b in w.findChildren(QPushButton)
                      if b.objectName()=="headerHelpButton"]
        sheet_buttons=[b for b in w.findChildren(QPushButton)
                       if b.objectName()=="headerSheetButton"]
        self.assertEqual([b.text() for b in help_buttons],["Help"])
        self.assertEqual([b.text() for b in sheet_buttons],["打開試算表"])
        for marker in (
            "QFrame#headerCard QComboBox#headerProfileCombo",
            "QToolButton#profile_manage_button::menu-indicator",
            "QMainWindow#tradingHelperMain QPushButton#headerHelpButton",
            "QMainWindow#tradingHelperMain QPushButton#headerSheetButton",
        ):
            self.assertIn(marker,w.styleSheet())
        # Phase 3: the custom titlebar integrates the window controls.
        self.assertTrue(w.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(w.title_bar.height(),39)
        self.assertEqual(
            (w.chrome_minimize.role,w.chrome_maximize.role,w.chrome_close.role),
            ("minimize","maximize","close")
        )
        self.assertEqual(
            w.profile_manage_button.popupMode(),QToolButton.InstantPopup
        )
        self.assertEqual(
            w.display_settings_button.popupMode(),QToolButton.InstantPopup
        )

    def test_display_preferences_are_in_menu_and_tv_persists_to_temp_config(self):
        button=self.window.display_settings_button
        self.assertIsInstance(button,QToolButton)
        self.assertEqual(button.popupMode(),QToolButton.InstantPopup)
        actions=button.menu().actions()
        self.assertEqual(len(actions),1)
        self.assertIsInstance(actions[0],QWidgetAction)
        box=actions[0].defaultWidget()
        self.assertIsNotNone(box)
        self.assertIs(self.window.tv_draw_internal.parent(),box)
        self.assertIs(self.window.always_on_top.parent(),box)
        self.assertFalse(self.window.tv_draw_internal.isChecked())
        self.window.tv_draw_internal.setChecked(True)
        self.assertTrue(self.window.store.data["ui"]["tv_draw_internal"])
        self.assertTrue(self.window.profiles.load_profile()["ui"]["tv_draw_internal"])
        self.window.tv_draw_internal.setChecked(False)
        self.assertFalse(self.window.store.data["ui"]["tv_draw_internal"])

    def test_auto_entry_remains_visible_and_not_in_display_menu(self):
        self.assertEqual(self.window.auto_entry_on_fill_both.text(),"自動進場")
        self.assertIsNone(self.window.auto_entry_on_fill_both.parent() if
                          self.window.auto_entry_on_fill_both.parent() is
                          self.window.display_settings_button.menu() else None)
        self.assertFalse(self.window.auto_entry_on_fill_both.isChecked())
        self.assertEqual(self.window.profile_manage_button.objectName(),"profile_manage_button")
        self.assertEqual(self.window.display_settings_button.objectName(),"display_settings_button")


if __name__=="__main__":
    unittest.main()

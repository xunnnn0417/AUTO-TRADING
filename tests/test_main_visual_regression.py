"""Main-screen feature manifest for safe visual-only redesign.

Tests build an isolated PySide6 helper in offscreen mode. Never use a real
trading account, open broker windows, or mutate the user's live configuration.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QToolButton

import trading_helper.gui as gui
from trading_helper.ui_theme import themed_icon

MAIN_BUTTONS = (
    "重新讀取", "試算表設定",
    "綁定場內視窗", "綁定場外視窗",
    "校準 cTrader", "校準 MT5", "校準 TradingView",
    "填入場內", "填入場外", "填入兩邊",
    "手動同步場外 SL/TP", "手動繪製 TV",
    "更新", "盈虧紀錄", "查看止盈/損",
    "Help", "打開試算表",
)
DATA_KEYS = {
    "symbol", "sheet_direction", "internal_direction", "external_direction",
    "internal_lot", "external_lot", "internal_tp", "external_tp",
    "internal_sl", "external_sl", "original_sl_points",
}
PARAM_KEYS = {"internal_balance", "daily_pnl", "expected_sl_combined", "internal_entry_price"}
CARD_NAMES = {"dataCard", "parameterCard", "actionsCard", "afterEntryCard", "activityCard"}


class MainVisualRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Path(tmp.name) / "test-config.json"
        profiles = Path(tmp.name) / "test-profiles.json"
        real_config = gui.ConfigStore
        real_profiles = gui.ProfileStore
        with patch.object(gui, "ConfigStore", side_effect=lambda: real_config(path=cfg)), \
             patch.object(gui, "ProfileStore", side_effect=lambda x: real_profiles(x, path=profiles)), \
             patch.object(gui.WindowController, "warm_ocr", return_value=None), \
             patch.object(gui.TradingHelperApp, "read_sheet", lambda _: None):
            self.window = gui.TradingHelperApp()
        self.window.show()
        self.qtapp.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_every_preexisting_main_action_remains_accessible(self):
        controls = self.window.findChildren(QPushButton)
        target_page = {
            "試算表設定":"編輯", "綁定場內視窗":"編輯",
            "綁定場外視窗":"編輯", "校準 cTrader":"編輯",
            "校準 MT5":"編輯", "校準 TradingView":"編輯",
            "盈虧紀錄":"紀錄",
        }
        for label in MAIN_BUTTONS:
            with self.subTest(label=label):
                page=target_page.get(label,"交易")
                self.window.switch_workspace(page)
                self.qtapp.processEvents()
                matches = [b for b in controls if b.text() == label]
                self.assertEqual(len(matches), 1)
                # 盈虧歷史入口已依新需求暫藏，保留原按鈕與函式。
                if label == "盈虧紀錄":
                    self.assertFalse(matches[0].isVisible())
                else:
                    self.assertTrue(matches[0].isVisible())
                self.assertTrue(matches[0].isEnabled())
        self.window.switch_workspace("交易")

    def test_data_and_parameter_fields_are_complete(self):
        self.assertEqual(set(self.window.data_labels), DATA_KEYS)
        self.assertEqual(set(self.window.parameter_inputs), PARAM_KEYS)
        for widget in (*self.window.data_labels.values(), *self.window.parameter_inputs.values()):
            self.assertTrue(widget.isVisible())
        self.assertEqual(self.window.internal_direction_input.count(), 2)
        self.assertEqual(self.window.internal_platform.count(), 2)
        self.assertEqual(self.window.external_platform.count(), 2)

    def test_all_old_ui_controls_stay_accessible(self):
        self.assertEqual(
            [a.text() for a in self.window.profile_manage_menu.actions() if not a.isSeparator()],
            ["建立新方案", "儲存目前方案", "重新命名目前方案", "刪除目前方案"],
        )
        self.assertTrue(self.window.profile_combo.isVisible())
        self.assertTrue(self.window.auto_entry_on_fill_both.isVisible())
        self.assertFalse(self.window.auto_entry_on_fill_both.isChecked())
        self.assertIsNotNone(self.window.tv_draw_internal.parent())
        self.assertIsNotNone(self.window.always_on_top.parent())
        self.assertIsInstance(self.window.profile_manage_button, QToolButton)
        self.assertIsInstance(self.window.display_settings_button, QToolButton)

    def test_dark_terminal_style_and_important_primary_action(self):
        self.assertIn("QGroupBox#actionsCard", self.window.styleSheet())
        self.assertIn("QPushButton#fillBothPrimary", self.window.styleSheet())
        self.assertEqual(self.window.objectName(), "tradingHelperMain")
        cards = {c.objectName() for c in self.window.findChildren(QGroupBox)}
        self.assertTrue(CARD_NAMES.issubset(cards))
        matches = [b for b in self.window.findChildren(QPushButton) if b.text()=="填入兩邊"]
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0].objectName(),"fillBothPrimary")
        self.assertFalse(matches[0].icon().isNull())
        for icon_name in ("database","crosshair","sliders","history","refresh","chart"):
            self.assertFalse(themed_icon(icon_name).isNull())

    def test_minimal_black_theme_dropdowns_and_sheet_button(self):
        from PySide6.QtGui import QShortcut
        from trading_helper.gui import ChevronCombo, SheetNoteIndicator
        for combo in (
            self.window.profile_combo,
            self.window.internal_platform,
            self.window.external_platform,
            self.window.internal_direction_input,
        ):
            self.assertIsInstance(combo, ChevronCombo)
            self.assertGreaterEqual(combo.width(), 80)
            self.assertTrue(combo.isVisible())
            self.assertGreater(combo.count(), 0)
        self.assertIsInstance(self.window.sheet_note_indicator, SheetNoteIndicator)
        self.assertEqual(self.window.sheet_note_indicator.width(), 22)
        self.assertEqual(self.window.sheet_note_indicator.height(), 22)
        sheet_btns = [b for b in self.window.findChildren(QPushButton)
                      if b.text() == "打開試算表"]
        self.assertEqual(len(sheet_btns), 1)
        # This is a strictly visual/name edit: original URL-open callback remains.
        self.assertIn("sheet_url_button.clicked.connect(self.open_sheet_url)",
                      __import__("inspect").getsource(gui.TradingHelperApp._build))
        self.assertNotIn("ESC  緊急停止",
                         [c.text() for c in self.window.findChildren(gui.QLabel)])
        shortcuts = [s.key().toString() for s in self.window.findChildren(QShortcut)]
        self.assertIn("Esc", shortcuts)
        style = self.window.styleSheet()
        self.assertIn("#0c0c0e", style)
        self.assertIn("#aa91b9", style)
        self.assertIn("QComboBox::down-arrow", style)

    def test_trade_page_has_no_scrollbar_and_records_are_separate(self):
        from PySide6.QtWidgets import QScrollArea
        self.assertEqual(self.window.main_pages.count(),3)
        self.assertIs(self.window.main_pages.widget(0),self.window.trade_page)
        self.assertFalse(self.window.trade_page.findChildren(QScrollArea))
        self.window.switch_workspace("交易")
        self.assertTrue(self.window.recent_status.isVisible())
        self.assertTrue(self.window.auto_entry_on_fill_both.isVisible())
        self.window.switch_workspace("紀錄")
        self.assertTrue(self.window.log_text.isVisible())
        self.assertTrue(self.window.log_text.isReadOnly())
        self.assertFalse(self.window.daily_pnl_history_button.isVisible())
        self.window.switch_workspace("編輯")
        self.assertTrue(self.window.action_buttons["試算表設定"].isVisible())
        self.assertTrue(self.window.action_buttons["校準 MT5"].isVisible())
        self.window.switch_workspace("交易")

    def test_manual_fill_and_emergency_existing_wiring_unchanged(self):
        self.assertTrue(all(btn.isEnabled() for btn in self.window.parameter_locked_buttons))
        self.assertTrue(self.window.log_text.isReadOnly())
        self.assertEqual(self.window.auto_entry_on_fill_both.isChecked(),False)
        # Demo-only broker execution must require native account identity
        # and a unique position readback before any GUI order submit.
        self.assertIn("unverified broker UI fails",
                      self.window._auto_entry_after_fill_both_pending.__doc__ or "")
        self.assertIn("Demo 帳戶",
                      self.window.auto_entry_on_fill_both.toolTip())
        self.assertIn("不會重複送單",
                      self.window.auto_entry_on_fill_both.toolTip())


if __name__=="__main__":
    unittest.main()

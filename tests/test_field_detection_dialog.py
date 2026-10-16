"""Smoke test for the experimental read-only detection entry point."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton
from trading_helper.gui import CalibrationDialog


class CalibrationInspectorSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_ctrader_hides_dev_inspection_entry_points(self):
        parent = QMainWindow()
        dialog = CalibrationDialog(parent, "cTrader")
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        self.assertNotIn("測試 UIA 自動辨識", buttons)
        self.assertNotIn("滑鼠指向檢查＋框線預覽", buttons)
        self.assertIn("自動尋找此階段欄位（唯讀）", buttons)
        self.assertIn("手動擷取所選欄位", buttons)
        self.assertFalse(dialog._inspection_running)
        self.assertTrue(callable(dialog.inspect_fields))
        self.assertTrue(callable(dialog.inspect_hover))
        dialog._hover_outline.close()
        dialog.close()
        parent.close()


if __name__ == "__main__":
    unittest.main()

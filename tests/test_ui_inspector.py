"""P1-1/P1-2 safeguards: all hover inspection remains strictly read-only."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

from trading_helper import ui_inspector
from trading_helper.gui import CalibrationDialog


class UIInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_valid_rectangle_encloses_hover_position(self):
        self.assertTrue(ui_inspector.valid_target_rectangle((20, 30, 220, 62), (50, 45)))
        self.assertFalse(ui_inspector.valid_target_rectangle((20, 30, 220, 62), (300, 45)))
        self.assertFalse(ui_inspector.valid_target_rectangle((-32000, -32000, -31900, -31900), (50, 45)))
        self.assertFalse(ui_inspector.valid_target_rectangle((20, 30, 20, 62), (20, 45)))

    def test_other_process_is_rejected_before_accessing_uia(self):
        with patch.object(ui_inspector, "_get_cursor", return_value=(120, 140)), \
                patch.object(ui_inspector, "_window_process_at", return_value=45):
            snapshot = ui_inspector.hover_snapshot(123)
        self.assertFalse(snapshot.is_candidate)
        self.assertIsNone(snapshot.rectangle)
        self.assertIn("不在所選交易平台", snapshot.note)

    def test_invalid_pid_is_rejected(self):
        with self.assertRaises(ValueError):
            ui_inspector.hover_snapshot(0)

    def test_sensitive_digits_are_hidden(self):
        self.assertNotIn("123456789", ui_inspector.safe_display_name("Account 123456789"))
        self.assertIn("帳", ui_inspector.safe_display_name("帳號"))

    def test_outline_is_clickthrough_and_translucent(self):
        outline = ui_inspector.CandidateOutline()
        self.assertTrue(outline.testAttribute(ui_inspector.Qt.WA_TransparentForMouseEvents))
        self.assertTrue(outline.testAttribute(ui_inspector.Qt.WA_TranslucentBackground))
        self.assertTrue(bool(outline.windowFlags() & ui_inspector.Qt.WindowTransparentForInput))
        # Offscreen Qt tests don't expose the real Windows monitor DPI.
        with patch.object(ui_inspector, "qt_rect_for_physical", return_value=ui_inspector.QRect(100, 200, 170, 50)):
            outline.display((100, 200, 270, 250), 1500)
        self.assertTrue(outline.isVisible())
        self.assertEqual((outline.geometry().width(), outline.geometry().height()), (170, 50))
        outline.hide()
        outline.close()

    def test_outline_rejects_empty_geometry(self):
        outline = ui_inspector.CandidateOutline()
        with self.assertRaises(ValueError):
            outline.display((50, 40, 49, 60))
        outline.close()

    def test_calibration_hides_hover_diagnostic_buttons_but_preserves_helpers(self):
        parent = QMainWindow()
        dialog = CalibrationDialog(parent, "cTrader")
        labels = {button.text() for button in dialog.findChildren(QPushButton)}
        self.assertNotIn("滑鼠指向檢查＋框線預覽", labels)
        self.assertNotIn("測試 UIA 自動辨識", labels)
        self.assertIn("手動擷取所選欄位", labels)
        self.assertIn("查看已校準位置", labels)
        self.assertFalse(dialog._hover_running)
        self.assertTrue(callable(dialog.inspect_hover))
        dialog._hover_outline.close()
        dialog.close()
        parent.close()


if __name__ == "__main__":
    unittest.main()

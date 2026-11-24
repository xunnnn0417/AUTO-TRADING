"""0.1.79 UI polish: QR size, triangles, disabled look, phone device list, test push."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication


class UiPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_qr_has_thin_border_bigger_code_and_still_decodes(self):
        import cv2
        import numpy as np
        from trading_helper.remote_qr import phone_qr_image
        url = "https://xun-laptop.tail03b05e.ts.net:8443"
        image = phone_qr_image(url)
        pixels = np.array(image.constBits()).reshape(image.height(), image.bytesPerLine())[:, :image.width()]
        self.assertEqual(cv2.QRCodeDetector().detectAndDecode(pixels)[0], url)
        dark = np.argwhere(pixels < 128)
        border = int(dark[:, 1].min())
        self.assertLessEqual(border, 21)            # was 30 px of light margin
        code_width = int(dark[:, 1].max()) - border + 1
        self.assertGreaterEqual(code_width, 170)    # black code area was 145 px

    def test_triangles_are_small_and_equilateral(self):
        from trading_helper.ui_theme import triangle_icon
        for direction in ("up", "down", "left", "right"):
            pixmap = triangle_icon(direction).pixmap(12, 12)
            self.assertFalse(pixmap.isNull())

    def test_dialog_disabled_buttons_look_unavailable(self):
        from trading_helper.ui_theme import DIALOG_THEME
        self.assertIn("QDialog QPushButton:disabled", DIALOG_THEME)


class PhoneDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        import test_mobile_remote as fixtures
        self.case = fixtures.MobileDesktopAdapterTests("test_phone_settings_show_fixed_setup_and_only_offer_revoke_after_selection")
        self.case.qtapp = self.qtapp
        self.case.setUp()
        self.addCleanup(self.case.tearDown)

    def open(self):
        from PySide6.QtWidgets import QListWidget
        controller = self.case.controller
        controller.show_settings()
        self.qtapp.processEvents()
        dialog = controller.settings_dialog
        self.addCleanup(dialog.close)
        return controller, dialog, dialog.findChild(QListWidget, "pairedDevices")

    def test_device_rows_draw_the_name_once_and_fit_the_list(self):
        controller, dialog, devices = self.open()
        self.assertIsNotNone(devices)
        self.assertEqual(devices.item(0).text(), "")  # name is drawn only by the row widget
        self.assertIn("background", devices.styleSheet())
        self.assertLessEqual(devices.height(), 3 * 38 + 12)

    def test_desktop_can_send_a_test_notification(self):
        from PySide6.QtWidgets import QPushButton
        controller, dialog, _ = self.open()
        button = dialog.findChild(QPushButton, "phoneTestNotification")
        self.assertIsNotNone(button)
        controller.server.public_origin = "https://phone.example"
        notifications = controller.server.notifications
        with patch.object(notifications, "subscribed", return_value=True), \
             patch.object(notifications, "test", return_value={"queued": True}) as test, \
             patch("trading_helper.gui.QMessageBox.information") as info:
            button.click()
        test.assert_called()
        self.assertIn("已傳送", info.call_args.args[2])


if __name__ == "__main__":
    unittest.main()

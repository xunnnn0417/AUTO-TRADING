"""Hover help never treats programmatic focus as pointer input."""
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from trading_helper.delayed_help import DelayedHoverHelp


class DelayedHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.button = QPushButton('重新讀取', self.window)
        self.button.setGeometry(20, 20, 100, 34)
        self.help = DelayedHoverHelp(self.window)
        self.help.register(self.button, '只讀取資料')
        self.window.show()
        self.app.processEvents()
        self.help.eventFilter(self.button, QEvent(QEvent.Leave))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_focus_alone_does_not_schedule_help(self):
        self.help.eventFilter(self.button, QEvent(QEvent.FocusIn))
        self.assertFalse(self.help._timer.isActive())
        self.assertIsNone(self.help._active)

    def test_hover_retains_delay_and_does_not_show_after_pointer_moves_away(self):
        self.help.eventFilter(self.button, QEvent(QEvent.Enter))
        self.assertTrue(self.help._timer.isActive())
        self.assertEqual(self.help._timer.interval(), 2000)
        inside = self.button.mapToGlobal(self.button.rect().center())
        outside = self.button.mapToGlobal(QPoint(-20, -20))
        with patch('trading_helper.delayed_help.QCursor.pos', return_value=inside), \
             patch('trading_helper.delayed_help.QToolTip.showText') as show:
            self.help._show_active()
            show.assert_called_once()
            self.assertEqual(show.call_args.args[1], '只讀取資料')
        with patch('trading_helper.delayed_help.QCursor.pos', return_value=outside), \
             patch('trading_helper.delayed_help.QToolTip.showText') as show:
            self.help._show_active()
            show.assert_not_called()
        self.help.eventFilter(self.button, QEvent(QEvent.Leave))
        self.assertFalse(self.help._timer.isActive())
        self.assertIsNone(self.help._active)

"""Foreground switching only; no real windows, typing or trading clicks."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.windows import WindowController, WindowInfo, AutomationError


class FocusRetryTests(unittest.TestCase):
    def setUp(self):
        self.guard = MagicMock()
        self.controller = WindowController(SimpleNamespace(guard=self.guard))
        self.window = WindowInfo(123, 'isolated platform', 0, 0, 800, 600)
        self.controller._refresh = MagicMock(return_value=self.window)
        # Replace the controller's reference; the shared time module is also
        # used by workers that may still be running from earlier suite cases.
        self.clock = SimpleNamespace(monotonic=MagicMock(), sleep=MagicMock())

    def test_delayed_first_attempt_gets_exactly_one_retry_then_returns_current_window(self):
        with patch('trading_helper.windows.user32') as api, \
             patch('trading_helper.windows.time', self.clock):
            self.clock.monotonic.side_effect = [0, .23, .24]
            api.IsIconic.return_value = 0
            api.GetForegroundWindow.side_effect = [5, 5, self.window.handle]
            self.assertEqual(self.controller.focus(self.window), self.window)
            self.assertEqual(api.SetForegroundWindow.call_count, 2)
            self.assertEqual(self.controller._refresh.call_count, 2)
            self.clock.sleep.assert_not_called()

    def test_both_attempts_denied_stop_without_issuing_input(self):
        with patch('trading_helper.windows.user32') as api, \
             patch('trading_helper.windows.time', self.clock):
            self.clock.monotonic.side_effect = [0, .23, .24, .47]
            api.IsIconic.return_value = 0
            api.GetForegroundWindow.return_value = 5
            with self.assertRaisesRegex(AutomationError, '重試後仍無法取得焦點'):
                self.controller.focus(self.window)
            self.assertEqual(api.SetForegroundWindow.call_count, 2)
            api.SendInput.assert_not_called()
            api.AttachThreadInput.assert_not_called()

    def test_closed_target_stops_before_second_foreground_request(self):
        self.controller._refresh.side_effect = AutomationError('目標視窗已關閉')
        with patch('trading_helper.windows.user32') as api, \
             patch('trading_helper.windows.time', self.clock):
            self.clock.monotonic.side_effect = [0, .23]
            api.IsIconic.return_value = 0
            api.GetForegroundWindow.return_value = 5
            with self.assertRaisesRegex(AutomationError, '已關閉'):
                self.controller.focus(self.window)
            self.assertEqual(api.SetForegroundWindow.call_count, 1)

    def test_emergency_stop_prevents_retry(self):
        self.guard.side_effect = [None, None, None, AutomationError('緊急停止')]
        with patch('trading_helper.windows.user32') as api, \
             patch('trading_helper.windows.time', self.clock):
            self.clock.monotonic.side_effect = [0, .23]
            api.IsIconic.return_value = 0
            api.GetForegroundWindow.return_value = 5
            with self.assertRaisesRegex(AutomationError, '緊急停止'):
                self.controller.focus(self.window)
            self.assertEqual(api.SetForegroundWindow.call_count, 1)

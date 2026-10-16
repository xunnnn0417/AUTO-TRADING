"""Offline tests for LAB physical-mouse isolation. Never hook real input."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.mouse_guard import (
    PhysicalMouseGuard, should_block_physical_mouse,
)
from trading_helper.windows import AutomationError


class MouseGuardTests(unittest.TestCase):
    def test_physical_mouse_blocked_during_active_task(self):
        self.assertTrue(should_block_physical_mouse(0, True, False))

    def test_injected_automation_mouse_always_allowed(self):
        self.assertFalse(should_block_physical_mouse(1, True, False))
        self.assertFalse(should_block_physical_mouse(3, True, False))

    def test_emergency_escape_disables_mouse_suppression(self):
        self.assertFalse(should_block_physical_mouse(0, True, True))

    def test_after_release_mouse_is_free(self):
        self.assertFalse(should_block_physical_mouse(0, False, False))

    def test_context_releases_even_when_task_raises(self):
        emergency = SimpleNamespace(
            event=threading.Event(), stop=MagicMock()
        )
        guard = PhysicalMouseGuard(emergency, maximum_seconds=10.0)

        def fake_loop():
            guard._ready.set()
            while guard._active.is_set():
                time.sleep(0.01)
        with patch.object(guard, "_hook_loop", side_effect=fake_loop):
            with self.assertRaisesRegex(ValueError, "simulated"):
                with guard:
                    self.assertTrue(guard._active.is_set())
                    raise ValueError("simulated")
        self.assertFalse(guard._active.is_set())
        emergency.stop.assert_not_called()

    def test_hook_failure_stops_before_task_begins(self):
        emergency = SimpleNamespace(
            event=threading.Event(), stop=MagicMock()
        )
        guard = PhysicalMouseGuard(emergency)

        def fake_failure():
            guard._startup_error = OSError("permission denied")
            guard._ready.set()
        with patch.object(guard, "_hook_loop", side_effect=fake_failure):
            with self.assertRaisesRegex(AutomationError, "permission denied"):
                with guard:
                    self.fail("task should not run if mouse hook cannot arm")

    def test_watchdog_releases_and_stops_auto_operation(self):
        emergency = SimpleNamespace(
            event=threading.Event(), stop=MagicMock()
        )
        guard = PhysicalMouseGuard(emergency)
        guard._active.set()
        with patch.object(guard, "close", wraps=guard.close) as close:
            guard._watchdog()
            close.assert_called_once_with()
        self.assertFalse(guard._active.is_set())
        emergency.stop.assert_called_once_with()

    def test_watchdog_noop_after_normal_release(self):
        emergency = SimpleNamespace(
            event=threading.Event(), stop=MagicMock()
        )
        guard = PhysicalMouseGuard(emergency)
        guard._watchdog()
        emergency.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()

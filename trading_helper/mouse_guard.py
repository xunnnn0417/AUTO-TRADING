"""Temporary Windows physical-mouse suppression for LAB automation.

Only physical mouse events are swallowed. Programmatic injected mouse
movement/clicks and all keyboard input (including Escape) remain available.
The Windows hook is released on every exit or error, with a hard watchdog.
No input suppression occurs merely by importing this module.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from .windows import AutomationError

_WH_MOUSE_LL = 14
_WM_QUIT = 0x0012
_LLMHF_INJECTED = 0x01
_LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(
    _LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MOUSE_HOOK_DATA(ctypes.Structure):
    _fields_ = [
        ("pt", _POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


def should_block_physical_mouse(flags: int, active: bool,
                                emergency_stopped: bool) -> bool:
    """Never suppress injected automation, after release, or after Escape."""
    return active and not emergency_stopped and not (flags & _LLMHF_INJECTED)


class PhysicalMouseGuard:
    """Temporary physical-mouse filter for one foreground automation task.

    Closing the LAB process also makes Windows release the low-level hook.
    This is intentionally NOT BlockInput or cursor clipping: those interfere
    with user Escape and/or the application's own mouse movements.
    """

    def __init__(self, emergency, *, maximum_seconds: float = 180.0):
        self.emergency = emergency
        self.maximum_seconds = maximum_seconds
        self._active = threading.Event()
        self._ready = threading.Event()
        self._startup_error = None
        self._thread = None
        self._thread_id = 0
        self._timer = None
        self._hook_proc = None

    def _hook_loop(self) -> None:
        api = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        api.SetWindowsHookExW.argtypes = [
            ctypes.c_int, _HOOKPROC, ctypes.c_void_p, wintypes.DWORD
        ]
        api.SetWindowsHookExW.restype = ctypes.c_void_p
        api.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        ]
        api.CallNextHookEx.restype = _LRESULT
        api.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        api.UnhookWindowsHookEx.restype = wintypes.BOOL
        api.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT,
        ]
        api.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT,
        ]
        api.GetMessageW.restype = wintypes.BOOL
        kernel.GetCurrentThreadId.restype = wintypes.DWORD

        hook = None
        try:
            self._thread_id = int(kernel.GetCurrentThreadId())
            msg = wintypes.MSG()
            # Create the hook-owning thread's message queue before startup.
            api.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

            @_HOOKPROC
            def callback(code, wparam, lparam):
                if code >= 0 and self._active.is_set():
                    try:
                        mouse = ctypes.cast(
                            lparam, ctypes.POINTER(_MOUSE_HOOK_DATA)
                        ).contents
                        if should_block_physical_mouse(
                            int(mouse.flags), True,
                            self.emergency.event.is_set(),
                        ):
                            return 1
                    except Exception:
                        # A broken hook must never make the user's mouse stuck.
                        return api.CallNextHookEx(None, code, wparam, lparam)
                return api.CallNextHookEx(None, code, wparam, lparam)

            self._hook_proc = callback
            hook = api.SetWindowsHookExW(_WH_MOUSE_LL, callback, None, 0)
            if not hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            while True:
                ret = api.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0:
                    break
                if ret == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                api.TranslateMessage(ctypes.byref(msg))
                api.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            self._active.clear()
            if hook:
                api.UnhookWindowsHookEx(hook)
            self._hook_proc = None
            self._ready.set()

    def _watchdog(self) -> None:
        if not self._active.is_set():
            return
        self.close()
        # Stop the automation as well; never keep working with unguarded
        # physical mouse after the time limit has expired.
        self.emergency.stop()

    def start(self):
        if self._thread is not None:
            raise AutomationError("Mouse guard cannot be started twice.")
        self._active.set()
        self._thread = threading.Thread(
            target=self._hook_loop, name="LABPhysicalMouseGuard", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(3.0) or self._startup_error:
            self.close()
            raise AutomationError(
                "Cannot safely lock physical mouse for LAB operation: "
                + str(self._startup_error or "hook did not become ready")
            )
        self._timer = threading.Timer(self.maximum_seconds, self._watchdog)
        self._timer.daemon = True
        self._timer.start()
        return self

    def close(self) -> None:
        self._active.clear()
        timer = self._timer
        if timer is not None:
            timer.cancel()
            self._timer = None
        thread_id = self._thread_id
        if thread_id:
            api = ctypes.WinDLL("user32", use_last_error=True)
            api.PostThreadMessageW.argtypes = [
                wintypes.DWORD, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM,
            ]
            api.PostThreadMessageW(thread_id, _WM_QUIT, 0, 0)
        if self._thread and threading.current_thread() is not self._thread:
            self._thread.join(timeout=0.8)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

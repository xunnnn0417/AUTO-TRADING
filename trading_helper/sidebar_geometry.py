"""Reconcile only our sidebar HWND when native and Qt geometry diverge."""
from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes
from datetime import datetime, timezone

from PySide6.QtGui import QGuiApplication


def parked_rect(rect, work, y):
    left, top, right, bottom = rect
    width, height = right-left, bottom-top
    x = max(work[0], work[2]-width)
    y = max(work[1], min(y, work[3]-height))
    return x, y, x+width, y+height


def ensure_native_sidebar(widget, screen, desired_y, diagnostic_path=None):
    # Offscreen tests and non-Windows platforms keep Qt's ordinary docking.
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(int(widget.winId()))
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        class MonitorInfo(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD),
                        ('device', wintypes.WCHAR*32)]

        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE

        def info(handle):
            value = MonitorInfo()
            value.cbSize = ctypes.sizeof(value)
            return value if user32.GetMonitorInfoW(wintypes.HANDLE(handle), ctypes.byref(value)) else None

        geometry = screen.geometry()
        ratio = float(screen.devicePixelRatio())

        def matches(value):
            if value is None:
                return False
            bounds = value.monitor
            # Some Qt drivers name screens after the panel model rather than
            # DISPLAY1. Origins remain physical; only each screen's size scales.
            return (value.device.casefold() == screen.name().casefold() or
                    (bounds.left == geometry.left() and bounds.top == geometry.top()
                     and abs(bounds.right-bounds.left-round(geometry.width()*ratio)) <= 2
                     and abs(bounds.bottom-bounds.top-round(geometry.height()*ratio)) <= 2))

        target = info(user32.MonitorFromWindow(hwnd, 2))
        if not matches(target):
            # Qt leaves monitor origins unscaled on Windows. Match the device
            # name instead of multiplying virtual-desktop coordinates by DPR.
            matches = []
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                               wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

            def visit(handle, _dc, _rect, _data):
                value = info(handle)
                if matches(value):
                    matches.append(value)
                return True

            callback = callback_type(visit)
            user32.EnumDisplayMonitors(None, None, callback, 0)
            if len(matches) != 1:
                return None
            target = matches[0]
        work = target.work
        before = (rect.left, rect.top, rect.right, rect.bottom)
        native_y = work.top + round((desired_y-screen.availableGeometry().top())*ratio)
        expected = parked_rect(before, (work.left, work.top, work.right, work.bottom), native_y)
        if before[0] == expected[0] and abs(before[1]-expected[1]) <= 1:
            return None
        # Do not activate, resize, change Z order, or touch any other window.
        if not user32.SetWindowPos(hwnd, None, expected[0], expected[1], 0, 0,
                                   0x0001 | 0x0004 | 0x0010 | 0x0200):
            return None
        after = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(after)):
            return None
        result = dict(time=datetime.now(timezone.utc).isoformat(), before=before,
                      after=(after.left,after.top,after.right,after.bottom), expected=expected,
                      qt=(widget.x(),widget.y(),widget.width(),widget.height()),
                      dpr=ratio, collapsed=widget.collapsed)
        if diagnostic_path is not None:
            try:
                rows = json.loads(diagnostic_path.read_text(encoding='utf-8')) if diagnostic_path.exists() else []
                rows = rows if isinstance(rows, list) else []
                diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
                diagnostic_path.write_text(json.dumps((rows+[result])[-20:]), encoding='utf-8')
            except (OSError, ValueError):
                pass
        return result
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None

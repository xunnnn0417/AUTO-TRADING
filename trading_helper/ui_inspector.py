"""Read-only hover inspection for manual verification of Windows UIA targets.

No mouse movement, clicks, typing, calibration writes, or order submission.
"""
from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


def safe_display_name(value: str) -> str:
    """Avoid showing likely account numbers or long identifiers."""
    return re.sub(r"\d{4,}", "[數字隱藏]", str(value or ""))[:85]


@dataclass(frozen=True)
class HoverSnapshot:
    position: tuple[int, int]
    rectangle: tuple[int, int, int, int] | None
    control_type: str
    name: str
    automation_id: str
    class_name: str
    ancestor_types: tuple[str, ...]
    note: str

    @property
    def is_candidate(self) -> bool:
        return self.rectangle is not None


def valid_target_rectangle(
    rectangle: tuple[int, int, int, int],
    position: tuple[int, int],
) -> bool:
    """A UIA bounding rectangle must really enclose the hovered pixel."""
    left, top, right, bottom = rectangle
    x, y = position
    return (
        right - left >= 6
        and bottom - top >= 6
        and right - left <= 3000
        and bottom - top <= 3000
        and left <= x < right
        and top <= y < bottom
        and all(-15000 < part < 15000 for part in rectangle)
    )


def select_control_rectangle(
    candidates: list[tuple[str, tuple[int, int, int, int]]],
    position: tuple[int, int],
) -> tuple[tuple[int, int, int, int] | None, str]:
    """Choose the smallest trustworthy semantic UIA control enclosing a point."""
    semantic_types = (
        "Button", "Edit", "ComboBox", "CheckBox", "RadioButton",
        "TabItem", "Hyperlink", "Text",
    )
    valid = [
        (control_type, rect)
        for control_type, rect in candidates
        if valid_target_rectangle(rect, position)
        and rect[2] - rect[0] <= 600
        and rect[3] - rect[1] <= 160
    ]
    for preferred_type in semantic_types:
        matches = [item for item in valid if item[0] == preferred_type]
        if matches:
            control_type, rect = min(
                matches,
                key=lambda item: (
                    (item[1][2] - item[1][0]) * (item[1][3] - item[1][1])
                ),
            )
            return rect, control_type
    return None, ""


def _get_cursor() -> tuple[int, int]:
    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        raise RuntimeError("無法讀取滑鼠座標")
    return int(point.x), int(point.y)


def process_id_for_window(handle: int) -> int:
    """Resolve process ID without focusing or changing the window."""
    if not handle:
        return 0
    api = ctypes.windll.user32
    api.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    pid = wintypes.DWORD()
    api.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return int(pid.value)


def _window_process_at(x: int, y: int) -> int:
    api = ctypes.windll.user32
    api.WindowFromPoint.argtypes = (wintypes.POINT,)
    api.WindowFromPoint.restype = wintypes.HWND
    api.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    window = api.WindowFromPoint(wintypes.POINT(x, y))
    pid = wintypes.DWORD()
    if not window:
        return 0
    api.GetWindowThreadProcessId(window, ctypes.byref(pid))
    return int(pid.value)


def hover_snapshot(expected_process_id: int) -> HoverSnapshot:
    """Inspect currently hovered UIA element only when it belongs to the selected process."""
    if expected_process_id <= 0:
        raise ValueError("目標程序無效")
    x, y = _get_cursor()
    position = x, y
    if _window_process_at(x, y) != expected_process_id:
        return HoverSnapshot(position, None, "", "", "", "", (),
                             "滑鼠不在所選交易平台的視窗上；請把滑鼠停在欄位內再試。")
    from pywinauto import Desktop

    element = Desktop(backend="uia").from_point(x, y)
    parents: list[str] = []
    current = element
    chain = []
    for depth in range(9):
        try:
            info = current.element_info
            rect = info.rectangle
            bounds = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
            control_type = str(info.control_type or "Unknown")
            chain.append((current, info, control_type, bounds))
            if depth:
                parents.append(control_type)
            if control_type == "Window":
                break
            current = current.parent()
            if current is None:
                break
        except Exception:
            break
    rectangle, selected_type = select_control_rectangle(
        [(control_type, bounds) for _, _, control_type, bounds in chain],
        position,
    )
    selected = next(
        (
            (control, info)
            for control, info, control_type, bounds in chain
            if rectangle is not None
            and control_type == selected_type
            and bounds == rectangle
        ),
        (element, element.element_info),
    )
    _, info = selected
    return HoverSnapshot(
        position=position,
        rectangle=rectangle,
        control_type=selected_type or str(info.control_type or "Unknown"),
        name=safe_display_name(str(info.name or "")),
        automation_id=safe_display_name(str(info.automation_id or "")),
        class_name=safe_display_name(str(info.class_name or "")),
        ancestor_types=tuple(parents),
        note=(
            "已讀取游標所在 UIA 控制項及其上層；請核對黃色完整外框。"
            if rectangle else "找不到可確認的完整 UIA 控制項外框；不會用小方框代替。"
        ),
    )


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _native_monitor_at(x: int, y: int) -> tuple[int, tuple[int, int, int, int]]:
    """Locate a physical screen using Win32; no mouse movement or input."""
    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    handle = user32.MonitorFromPoint(wintypes.POINT(x, y), 0)
    if not handle:
        raise ValueError("外框位置不在任何實體螢幕內")
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        raise RuntimeError("無法讀取 Windows 實體螢幕座標")
    rect = info.rcMonitor
    return int(handle), (rect.left, rect.top, rect.right, rect.bottom)


def logical_bounds_for_physical(
    bounds: tuple[int, int, int, int],
    monitor: tuple[int, int, int, int],
    logical_screen: QRect,
    dpi_ratio: float,
) -> QRect:
    """Convert physical UIA pixels into Qt device-independent coordinates.

    Physical monitor offset is subtracted *before* dividing by DPI scale.
    The logical Qt screen origin is then re-added, including on left monitors.
    """
    if dpi_ratio <= 0:
        raise ValueError("無效的 DPI 縮放倍率")
    l, t, r, b = bounds
    ml, mt, mr, mb = monitor
    if not (
        ml <= l < r <= mr
        and mt <= t < b <= mb
        and abs(logical_screen.width() * dpi_ratio - (mr - ml)) <= 3
        and abs(logical_screen.height() * dpi_ratio - (mb - mt)) <= 3
    ):
        raise ValueError("UIA 座標與 Windows/Qt 螢幕尺寸不一致；拒絕畫錯外框")
    x1 = logical_screen.left() + round((l - ml) / dpi_ratio)
    y1 = logical_screen.top() + round((t - mt) / dpi_ratio)
    x2 = logical_screen.left() + round((r - ml) / dpi_ratio)
    y2 = logical_screen.top() + round((b - mt) / dpi_ratio)
    return QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))


def qt_rect_for_physical(bounds: tuple[int, int, int, int]) -> QRect:
    """Map a UIA physical rectangle to the matching Qt screen.

    Fail closed for ambiguous screens and cross-monitor rectangles.
    """
    l, t, r, b = bounds
    if not (l < r and t < b):
        raise ValueError("UIA 外框位置無效")
    center = ((l + r) // 2, (t + b) // 2)
    monitor_handle, native = _native_monitor_at(*center)
    if any(
        _native_monitor_at(x, y)[0] != monitor_handle
        for x, y in ((l, t), (r - 1, t), (l, b - 1), (r - 1, b - 1))
    ):
        raise ValueError("UIA 外框跨越多個螢幕，暫不自動畫框")
    candidates = []
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio()
        if (
            abs(geometry.left() - native[0]) <= 2
            and abs(geometry.top() - native[1]) <= 2
            and abs(geometry.width() * ratio - (native[2] - native[0])) <= 3
            and abs(geometry.height() * ratio - (native[3] - native[1])) <= 3
        ):
            candidates.append(screen)
    if len(candidates) != 1:
        raise RuntimeError("無法唯一對應 Windows 與 Qt 螢幕；不顯示不可靠外框")
    screen = candidates[0]
    return logical_bounds_for_physical(bounds, native, screen.geometry(), screen.devicePixelRatio())


class CandidateOutline(QWidget):
    """Click-through, non-activating yellow bounding-box overlay."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def display(self, rectangle: tuple[int, int, int, int], ms: int = 5500) -> None:
        left, top, right, bottom = rectangle
        if right <= left or bottom <= top:
            raise ValueError("無效的外框位置")
        self._timer.stop()
        # UIA returns physical pixels while Qt QWidget uses device-independent coordinates.
        self.setGeometry(qt_rect_for_physical(rectangle))
        self.show()
        self.raise_()
        self._timer.start(ms)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(255, 195, 0, 35))
        painter.setPen(QPen(QColor(255, 190, 0, 240), 4))
        painter.drawRect(QRect(2, 2, max(1, self.width() - 4), max(1, self.height() - 4)))
        painter.end()


class CandidatePointMarker(QWidget):
    """Small click-through marker for a saved coordinate without UIA bounds."""

    DIAMETER = 18

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def display(self, point: tuple[int, int], ms: int = 5500) -> None:
        x, y = map(int, point)
        radius = self.DIAMETER // 2
        physical = (x - radius, y - radius, x + radius, y + radius)
        self._timer.stop()
        self.setGeometry(qt_rect_for_physical(physical))
        self.show()
        self.raise_()
        self._timer.start(ms)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        outer = QRect(2, 2, max(1, self.width() - 4), max(1, self.height() - 4))
        painter.setPen(QPen(QColor(8, 8, 12, 245), 1.5))
        painter.setBrush(QColor(8, 8, 12, 225))
        painter.drawEllipse(outer)
        inner = outer.adjusted(2, 2, -2, -2)
        painter.setPen(QPen(QColor(255, 232, 164, 245), 1))
        painter.setBrush(QColor(255, 190, 0, 255))
        painter.drawEllipse(inner)
        painter.end()

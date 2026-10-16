"""Minimal test-only Windows frameless chrome.

Qt keeps the existing app content and callbacks. The top edge is a compact
titlebar; only blank areas can drag. On Windows WM_NCHITTEST delegates edge
resize to the OS, including corner hit regions; no app-controlled mouse
automation or broker interaction is involved.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QToolButton


def edge_hit_test(x: int, y: int, rect: tuple[int,int,int,int], border: int=7) -> int:
    """Windows edge/corner codes, pure and independently testable."""
    l,t,r,b=rect
    if x < l or x >= r or y < t or y >= b:
        return 1  # HTCLIENT (outside is left to Windows)
    left=x<l+border
    right=x>=r-border
    top=y<t+border
    bottom=y>=b-border
    if top and left: return 13  # HTTOPLEFT
    if top and right: return 14 # HTTOPRIGHT
    if bottom and left: return 16 # HTBOTTOMLEFT
    if bottom and right: return 17 # HTBOTTOMRIGHT
    if left: return 10 # HTLEFT
    if right: return 11 # HTRIGHT
    if top: return 12 # HTTOP
    if bottom: return 15 # HTBOTTOM
    return 1


class FramelessNativeMixin:
    """Only adjust native hit-testing for a non-maximized Windows top level."""
    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                msg=ctypes.cast(int(message),ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x0084 and not self.isMaximized() and not self.isMinimized():
                    rect=wintypes.RECT()
                    user32=ctypes.windll.user32
                    if user32.GetWindowRect(wintypes.HWND(int(self.winId())),ctypes.byref(rect)):
                        # WM_NCHITTEST carries signed *physical screen* coords
                        # in LPARAM. They must be used instead of GetCursorPos,
                        # including when Windows is sizing without a pointer move.
                        lp=int(msg.lParam)
                        x=ctypes.c_short(lp & 0xffff).value
                        y=ctypes.c_short((lp >> 16) & 0xffff).value
                        dpi=max(1.0,float(self.devicePixelRatioF()))
                        border=max(6,round(6*dpi))
                        hit=edge_hit_test(
                            x,y,(rect.left,rect.top,rect.right,rect.bottom),border)
                        if hit != 1:
                            return True, hit
            except (AttributeError,ValueError,TypeError,OverflowError):
                pass  # Qt's own event path remains available
        return super().nativeEvent(event_type,message)


class WindowChromeButton(QToolButton):
    """Simple symbols with no persistent button frame."""
    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role=role
        self.setObjectName("chrome_"+role)
        # Compact DeepCharts-like symbols with a ~30px accessible hit area.
        self.setFixedSize(30, 30)
        accessible={
            "minimize":"最小化",
            "maximize":"最大化",
            "close":"關閉",
        }[role]
        self.setToolTip(accessible)
        self.setAccessibleName(accessible)
        self.setCursor(Qt.ArrowCursor)

    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Avoid an oversized Windows-style glyph. Keep subdued by default.
        hovered = self.underMouse()
        color = "#ff9ba4" if self.role == "close" and hovered else (
            "#f2edf7" if hovered else "#a9a6b4")
        pen=QPen(QColor(color),1.1)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        x=self.width()//2
        y=self.height()//2
        if self.role=="minimize":
            painter.drawLine(x-4,y+1,x+4,y+1)
        elif self.role=="maximize":
            if self.window().isMaximized():
                painter.drawRect(x-2,y-3,7,7)
                painter.drawLine(x-5,y-1,x+2,y-1)
                painter.drawLine(x-5,y-1,x-5,y+6)
            else:
                painter.drawRect(x-4,y-4,8,8)
        elif self.role=="close":
            painter.drawLine(x-4,y-4,x+4,y+4)
            painter.drawLine(x+4,y-4,x-4,y+4)
        painter.end()


class CompactTitleBar(QFrame):
    """MenuWidget titlebar that never drags from interactive child controls."""
    def __init__(self,parent):
        super().__init__(parent)
        self.setObjectName("compactTitleBar")
        self.setFixedHeight(39)
        self.setMouseTracking(True)
        self._fallback_drag_offset=None

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            handle=self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._fallback_drag_offset=event.globalPosition().toPoint()-self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._fallback_drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint()-self._fallback_drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        self._fallback_drag_offset=None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.window().toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

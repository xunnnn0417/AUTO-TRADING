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

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton,
)


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
    def showEvent(self, event):
        super().showEvent(event)
        self._apply_native_window_corners()

    def _apply_native_window_corners(self) -> None:
        """Ask Windows 11 for its small rounded top-level window corners."""
        if sys.platform != "win32" or self.isMaximized():
            return
        try:
            preference = ctypes.c_int(3)  # DWMWCP_ROUNDSMALL
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(int(self.winId())),
                33,  # DWMWA_WINDOW_CORNER_PREFERENCE
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
        except (AttributeError, OSError, TypeError, ValueError):
            # Older Windows versions and offscreen Qt have no DWM corner API.
            pass

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
                # Back window's exposed top/right edges; complete front
                # window below. No crossed or missing rectangle edges.
                painter.drawLine(x-1,y-5,x+5,y-5)
                painter.drawLine(x+5,y-5,x+5,y+1)
                painter.drawLine(x+5,y+1,x+3,y+1)
                painter.drawRect(x-4,y-2,7,7)
            else:
                painter.drawRect(x-4,y-4,8,8)
        elif self.role=="close":
            painter.drawLine(x-4,y-4,x+4,y+4)
            painter.drawLine(x+4,y-4,x-4,y+4)
        painter.end()


class ClearFieldButton(QToolButton):
    """Vector-drawn clear mark that stays centered across Windows fonts/DPI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("lineEditClearButton")
        self.setAccessibleName("清除內容")
        self.setToolTip("清除內容")
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFixedSize(22, 22)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Keep the hover affordance smaller than the click target so the X
        # reads as a centered clear glyph, not a separate circular control.
        cx = (self.width() - 1) / 2
        cy = (self.height() - 1) / 2
        if self.underMouse():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#302d37"))
            painter.drawEllipse(
                round(cx - 7), round(cy - 7), 14, 14
            )
        pen = QPen(QColor("#b9b4c0"), 1.55)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(cx - 4, cy - 4, cx + 4, cy + 4)
        painter.drawLine(cx + 4, cy - 4, cx - 4, cy + 4)
        painter.end()


class ClearButtonLineEdit(QLineEdit):
    """Line edit with a small, vertically centered, accessible clear control."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.clear_button = ClearFieldButton(self)
        self.clear_button.clicked.connect(self.clear)
        self.textChanged.connect(self._update_clear_button)
        self.missing_indicator = QLabel(self)
        self.missing_indicator.setObjectName("missingFieldIndicatorDot")
        self.missing_indicator.setFixedSize(6, 6)
        self.missing_indicator.setStyleSheet(
            "background-color:#fa5362;border-radius:3px;"
        )
        self.missing_indicator.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.missing_indicator.setAccessibleName("此欄位尚未填寫")
        self.missing_indicator.hide()
        self.setTextMargins(0, 0, 28, 0)
        self._position_clear_button()
        self._position_missing_indicator()
        self._update_clear_button(self.text())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_clear_button()
        self._position_missing_indicator()

    def set_missing_indicator(self, visible: bool, tooltip: str = "") -> None:
        self.missing_indicator.setToolTip(tooltip)
        self.missing_indicator.setVisible(bool(visible))
        if visible:
            self._position_missing_indicator()
            self.missing_indicator.raise_()

    def _position_clear_button(self) -> None:
        button = self.clear_button
        button.move(
            max(0, self.width() - button.width() - 5),
            max(0, (self.height() - button.height()) // 2),
        )

    def _position_missing_indicator(self) -> None:
        self.missing_indicator.move(max(0, self.width() - 12), 4)

    def _update_clear_button(self, text: str) -> None:
        self.clear_button.setVisible(bool(text))


class CompactTitleBar(QFrame):
    """MenuWidget titlebar that never drags from interactive child controls."""
    def __init__(self,parent, *, allow_maximize: bool=True):
        super().__init__(parent)
        self.setObjectName("compactTitleBar")
        self.setFixedHeight(39)
        self.setMouseTracking(True)
        self.allow_maximize=bool(allow_maximize)
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
        if event.button()==Qt.LeftButton and self.allow_maximize:
            self.window().toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ThemedDialog(FramelessNativeMixin, QDialog):
    """Dialog with the same compact title controls and resize behavior as LAB."""

    def setWindowTitle(self, title: str) -> None:
        super().setWindowTitle(title)
        title_label = getattr(self, "_chrome_title_label", None)
        if title_label is not None:
            title_label.setText(str(title))

    def install_chrome(
        self, *, show_minimize: bool=False, show_maximize: bool=False,
        center_title: bool=False, title_top_inset: int | None=None,
    ) -> None:
        if getattr(self, "_app_chrome_installed", False):
            return
        layout = self.layout()
        if layout is None:
            raise RuntimeError("ThemedDialog requires a layout before chrome setup")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self._restore_geometry = None
        self._last_normal_geometry = self.geometry()
        self.title_bar = CompactTitleBar(
            self, allow_maximize=show_maximize
        )
        row = QHBoxLayout(self.title_bar)
        top_inset = 2 if title_top_inset is None else max(0, int(title_top_inset))
        row.setContentsMargins(10, top_inset, 3, 2)
        row.setSpacing(1)
        title = QLabel(self.windowTitle(), self.title_bar)
        title.setObjectName("dialogTitle")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._chrome_title_label = title
        if center_title:
            title.setAlignment(Qt.AlignCenter)
            row.addStretch(1)
            row.addWidget(title)
            row.addStretch(1)
        else:
            title.setAlignment(
                Qt.AlignLeft
                | (Qt.AlignTop if title_top_inset is not None else Qt.AlignVCenter)
            )
            row.addWidget(title)
            row.addStretch(1)
        self.chrome_close = WindowChromeButton("close", self.title_bar)
        self.chrome_close.clicked.connect(self.close)
        if show_minimize:
            self.chrome_minimize = WindowChromeButton("minimize", self.title_bar)
            self.chrome_minimize.clicked.connect(self._minimize_from_chrome)
            row.addWidget(self.chrome_minimize)
        if show_maximize:
            self.chrome_maximize = WindowChromeButton("maximize", self.title_bar)
            self.chrome_maximize.clicked.connect(self.toggle_maximized)
            row.addWidget(self.chrome_maximize)
        row.addWidget(self.chrome_close)
        # A normal layout widget inherits the dialog's content margins, which
        # leaves the titlebar (and its close button) visibly inset.  QLayout's
        # menu-bar slot spans the dialog edge while preserving those margins
        # for the actual content below it.
        layout.setMenuBar(self.title_bar)
        self.setProperty("appDialogChrome", True)
        self._app_chrome_installed = True

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            QTimer.singleShot(0, self._ensure_taskbar_entry)

    def _ensure_taskbar_entry(self) -> None:
        """Keep owned app dialogs reachable from the Windows taskbar."""
        if sys.platform != "win32" or not self.isVisible():
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = wintypes.HWND(int(self.winId()))
            get_long = user32.GetWindowLongPtrW
            set_long = user32.SetWindowLongPtrW
            get_long.argtypes = (wintypes.HWND, ctypes.c_int)
            get_long.restype = ctypes.c_ssize_t
            set_long.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
            set_long.restype = ctypes.c_ssize_t
            ex_style = int(get_long(hwnd, -20))  # GWL_EXSTYLE
            app_window = 0x00040000  # WS_EX_APPWINDOW
            tool_window = 0x00000080  # WS_EX_TOOLWINDOW
            updated = (ex_style | app_window) & ~tool_window
            if updated != ex_style:
                set_long(hwnd, -20, updated)
                user32.SetWindowPos(
                    hwnd, None, 0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020,
                )
        except (AttributeError, OSError, TypeError, ValueError):
            pass

    def _minimize_from_chrome(self) -> None:
        if self.isMaximized():
            self._restore_geometry = self.geometry()
        elif not self.isMinimized():
            self._last_normal_geometry = self.geometry()
        self.showMinimized()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.isMaximized() and not self.isMinimized():
            if self.width() >= 240 and self.height() >= 180:
                self._last_normal_geometry = self.geometry()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and not self.isMinimized():
            QTimer.singleShot(0, self._restore_if_minimized_geometry_was_lost)

    def _restore_if_minimized_geometry_was_lost(self) -> None:
        if (
            self.isVisible()
            and not self.isMinimized()
            and not self.isMaximized()
            and (self.width() < 240 or self.height() < 180)
            and self._last_normal_geometry is not None
        ):
            self.setGeometry(self._last_normal_geometry)

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            if self._restore_geometry is not None:
                self.setGeometry(self._restore_geometry)
        else:
            self._restore_geometry = self.geometry()
            self.showMaximized()

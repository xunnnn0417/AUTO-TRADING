"""Two-second descriptive hover help for concise main-screen controls.

Does not change clicks, selections, window targets or trading automation.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QToolTip, QWidget


class DelayedHoverHelp(QObject):
    def __init__(self, parent: QObject, delay_ms: int = 2000):
        super().__init__(parent)
        self.delay_ms = delay_ms
        self._details: dict[QWidget, str] = {}
        self._active: QWidget | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._show_active)

    def register(self, widget: QWidget, description: str) -> None:
        self._details[widget] = description
        widget.setToolTip(description)
        widget.setAccessibleDescription(description)
        widget.installEventFilter(self)

    def _show_active(self) -> None:
        widget = self._active
        if widget is None or not widget.isVisible() or not widget.isEnabled():
            return
        QToolTip.showText(
            widget.mapToGlobal(QPoint(2, widget.height() + 4)),
            self._details[widget],
            widget,
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in self._details:
            if event.type() in (QEvent.Enter, QEvent.FocusIn):
                self._active = watched
                self._timer.start(self.delay_ms)
            elif event.type() in (
                QEvent.Leave, QEvent.FocusOut,
                QEvent.Hide, QEvent.MouseButtonPress,
            ):
                if self._active is watched:
                    self._active = None
                    self._timer.stop()
                    QToolTip.hideText()
            elif event.type() == QEvent.ToolTip:
                # Suppress the system's faster default tooltip.
                # It will be shown by the 2-second timer instead.
                return True
        return super().eventFilter(watched, event)

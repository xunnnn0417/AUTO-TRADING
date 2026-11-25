"""Small dropdown affordances for compact desktop controls; no workflow state."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QListView, QToolButton


def paint_chevron(painter, x, y, opened=False):
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor('#c0b5d0'), 1.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    direction = -1 if opened else 1
    painter.drawLine(int(x-3), int(y-direction), int(x), int(y+direction*2))
    painter.drawLine(int(x), int(y+direction*2), int(x+3), int(y-direction))


class SmallDisclosureButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setStyleSheet('QToolButton { padding:4px 17px 4px 6px; } '
                           'QToolButton::menu-indicator { image:none; width:0; }')

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        paint_chevron(painter, self.width()-9, self.height()/2,
                      self.isChecked() or bool(self.menu() and self.menu().isVisible()))


class HoverStageCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(74, 24)
        self.setStyleSheet('QComboBox {font-size:11px;background:transparent;border:0;min-height:0;}'
                           'QComboBox::drop-down {border:0;width:0;}'
                           'QComboBox::down-arrow {image:none;}')
        view = QListView()
        view.setSpacing(0)
        view.setUniformItemSizes(True)
        view.setMinimumWidth(self.width())
        view.setStyleSheet('QListView {background:#17151e;color:#eae4f2;'
            'border:1px solid #3c3548;border-radius:7px;padding:4px;outline:0;font-size:11px;}'
            'QListView::item {min-height:18px;padding:2px 8px;border:0;border-radius:4px;}'
            'QListView::item:hover {background:#292433;}'
            'QListView::item:selected {background:#383044;color:#ffffff;}')
        self.setView(view)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Highlight only while the pointer is really over it or the list is
        # open. Keyboard focus (kept after choosing an item) and Qt's stale
        # under-mouse flag after the popup closes left it looking hovered.
        pointer_inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        active = pointer_inside or self.view().isVisible()
        if active and self.isEnabled():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#262030'))
            painter.drawRoundedRect(QRectF(self.rect()), 5, 5)
        text = self.currentText() if self.currentIndex() >= 0 else self.placeholderText()
        text = self.fontMetrics().elidedText(text, Qt.ElideRight, self.width()-23)
        width = self.fontMetrics().horizontalAdvance(text)
        painter.setPen(QColor('#eee8f4' if active else '#b8a8d5') if self.isEnabled() else QColor('#77717f'))
        painter.drawText(QRectF(4, 0, width, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        if self.isEnabled():
            paint_chevron(painter, width+12, self.height()/2, self.view().isVisible())

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()


class LiveProfileCombo(HoverStageCombo):
    """目前持倉's 方案 name, styled like the side panel's subtitle. With one
    方案 holding a position it is plain text: no arrow, no hover, no click.
    With two or more it is a normal drop-down."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.locked = True
        self.setFocusPolicy(Qt.NoFocus)

    def show_payload(self, value, active_name: str) -> None:
        """Same 方案 list / choice on the main screen, side panel and phone."""
        from PySide6.QtCore import QSignalBlocker
        value = value or {}
        name = value.get('profile') or active_name
        choices = list(value.get('choices') or [])
        items = choices if name in choices else [name] + choices
        with QSignalBlocker(self):
            if [self.itemText(i) for i in range(self.count())] != items:
                self.clear()
                self.addItems(items)
            self.setCurrentText(name)
        self.set_locked(len(choices) < 2)

    def set_locked(self, locked: bool) -> None:
        self.locked = bool(locked)
        self.setCursor(Qt.ArrowCursor if self.locked else Qt.PointingHandCursor)
        self.update()

    def mousePressEvent(self, event):
        if not self.locked:
            super().mousePressEvent(event)

    def wheelEvent(self, event):
        if not self.locked:
            super().wheelEvent(event)

    def paintEvent(self, event):
        if not self.locked:
            return super().paintEvent(event)
        painter = QPainter(self)
        text = self.fontMetrics().elidedText(self.currentText(), Qt.ElideRight, self.width() - 8)
        painter.setPen(QColor('#b8a8d5'))
        painter.drawText(QRectF(4, 0, self.width() - 4, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def showPopup(self):
        # The list delegate also reserves space for its selection indicator.
        width = max((self.view().fontMetrics().horizontalAdvance(self.itemText(i)) + 48
                     for i in range(self.count())), default=self.width())
        self.view().setMinimumWidth(max(self.width(), width))
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self.clearFocus()
        self.update()

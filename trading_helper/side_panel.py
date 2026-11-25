"""Floating quick controls: a view of the main window, never a second trader."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPalette, QPen, QRegion
import shiboken6
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QStyleOptionToolButton, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .calendar_events import TAIPEI, UTC, format_event_time
from .event_summary import event_summary, trading_session
from .progress_ruler import AccountRuler, money
from .ui_theme import themed_icon
from .sidebar_geometry import ensure_native_sidebar
from .compact_controls import HoverStageCombo


class EventFlyout(QFrame):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(245, 243, 250, 70), 0.7))
        painter.setBrush(QColor('#111116'))
        painter.drawRoundedRect(QRectF(0.35, 0.35, self.width()-0.7, self.height()-0.7), 10, 10)


class EventSummaryButton(QToolButton):
    """One elided line; the tooltip retains the full event details."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(100, 30)

    def minimumSizeHint(self):
        return QSize(40, 30)

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = ''
        option.arrowType = Qt.NoArrow
        option.icon = QIcon()  # the triangle is painted below, once
        self.style().drawComplexControl(QStyle.CC_ToolButton, option, painter, self)
        # Small equilateral triangle instead of the style's wide, flat arrow.
        from .ui_theme import triangle_icon
        triangle_icon("right" if self.isChecked() else "left").paint(
            painter, QRect(3, (self.height()-12)//2, 12, 12))
        painter.setPen(QColor('#ece8f1'))
        rect = QRect(23, 0, max(1, self.width()-27), self.height())
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft,
                         self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width()))


class WarningFlyout(QFrame):
    """Nonmodal explanation beside the sidebar; never a trade confirmation."""
    tip_y = 30

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(.35, .35, self.width()-8.7, self.height()-.7), 9, 9)
        tip = QPainterPath()
        tip.moveTo(self.width()-9, self.tip_y-5)
        tip.lineTo(self.width()-.35, self.tip_y)
        tip.lineTo(self.width()-9, self.tip_y+5)
        tip.closeSubpath()
        painter.setPen(QPen(QColor(245, 243, 250, 70), .7))
        painter.setBrush(QColor('#17171e'))
        painter.drawPath(shape.united(tip))


class SideQuickPanel(QWidget):
    WIDTH = 340
    HANDLE_HEIGHT = 40
    PARKED_HEIGHT = 28  # parked tab at the screen edge: shorter than the drag ball

    def __init__(self, app):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # An independent tool window survives hiding/minimizing the main UI.
        # The main owner explicitly closes it before shutting down.
        self.app = app
        self.setWindowTitle('對沖小幫手・側邊快捷')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.collapsed = False
        self._drag_offset = None
        self._drag_widgets = ()
        self._handle_press = None
        self._handle_pointer = None
        self._handle_dragging = False
        self._collapse_press = None
        self._collapse_moved = False
        self.collapse_button = None
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(180)
        self._hold_timer.timeout.connect(self._begin_handle_drag)
        # One click on the ball opens the side panel; a quick second click
        # instead opens / closes 目前持倉 on its own (ball stays parked).
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(min(300, QGuiApplication.styleHints().mouseDoubleClickInterval()))
        self._click_timer.timeout.connect(lambda: self.set_collapsed(False))
        self._screen = app.screen() or QGuiApplication.primaryScreen()
        self._dock_timer = QTimer(self)
        self._dock_timer.setSingleShot(True)
        self._dock_timer.timeout.connect(self.dock)
        self._y = int(app.store.data['ui'].get('side_panel_y', 70))
        self.setStyleSheet('''
            QWidget { color: #ece8f1; font-family: "Segoe UI", "Microsoft JhengHei UI"; font-size: 11px; }
            QLabel { background: transparent; }
            QLabel[muted="true"] { color: #a6a0b2; font-size: 10px; }
            QLineEdit, QComboBox { background: #1c1b23; border: 1px solid #393642;
                border-radius: 7px; padding: 3px 8px; min-height: 24px; }
            QLineEdit:focus, QComboBox:focus { border-color: #9a86ec; }
            QComboBox::drop-down { border: 0; width: 24px; background: transparent; }
            QComboBox::down-arrow { image: none; width: 0; height: 0; }
            QPushButton, QToolButton { background: transparent; border: 0; border-radius: 6px; padding: 4px; }
            QPushButton:hover, QToolButton:hover { background: #34303f; }
            QPushButton:disabled, QToolButton:disabled { color: #706a7a; }
            QPushButton#sideFill { background: #7053d9; border: 1px solid #9278ed; min-height: 26px; padding: 3px; }
            QPushButton#sideFill:hover { background: #8063e9; }
            QPushButton#sideFill:disabled { background: #393442; border-color: #494050; }
            QToolButton#sideCloseBoth { background: transparent; border: 1px solid #6a55d8; border-radius: 7px; }
            QToolButton#sideCloseBoth:hover { background: #1f1a33; border-color: #8a75ee; }
            QToolButton#sideHome { border: 1px solid rgba(245,243,250,55); border-radius: 7px; }
            QToolButton#sideHandle, QToolButton#sideHandle:hover { background: transparent; border: 0; padding: 0; }
            QScrollArea { background: transparent; border: 0; }
            QScrollBar:vertical { background: transparent; width: 5px; }
            QScrollBar::handle:vertical { background: #51495f; min-height: 20px; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QFrame#eventFlyout { background: #111116; border: 1px solid #38353f; border-radius: 10px; }
            QTabWidget::pane { border: 0; background: transparent; }
            QTabBar::tab { background: transparent; color: #aaa2b6; padding: 7px 8px; border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: #f1edf7; border-bottom-color: #9a84e5; }
        ''')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(0)
        self.handle = self._icon_button('panel-right-open', '展開側邊快捷')
        self.handle.setObjectName('sideHandle')
        self.handle.setToolTip('按一下展開，長按拖動')
        self.handle.setCursor(Qt.OpenHandCursor)
        self.handle.installEventFilter(self)
        self.handle.clicked.connect(lambda: self.set_collapsed(False))
        outer.addWidget(self.handle)
        self.handle.hide()
        self.body = QWidget(self)
        outer.addWidget(self.body)
        root = QVBoxLayout(self.body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        header = QFrame(self.body)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 2, 0, 7)
        row.setSpacing(6)
        title = QLabel('對沖小幫手')
        title.setStyleSheet('font-size: 13px; font-weight: 600;')
        self.stage_selector = HoverStageCombo()
        self.stage_selector.setObjectName('sideStageSelector')
        self.stage_selector.setAccessibleName('側邊階段')
        self.stage_selector.setPlaceholderText('尚未讀取')
        self.stage_selector.currentTextChanged.connect(self._stage_selected)
        # 方案 first, then 階段 (a stage belongs to the chosen 方案).
        self.profile_selector = HoverStageCombo()
        self.profile_selector.setObjectName('sideProfileSelector')
        self.profile_selector.setAccessibleName('側邊方案')
        self.profile_selector.setToolTip('切換方案')
        self.profile_selector.currentTextChanged.connect(self._profile_selected)
        row.addWidget(title)
        row.addWidget(self.profile_selector, 0, Qt.AlignBottom)
        row.addWidget(self.stage_selector, 0, Qt.AlignBottom)
        row.addStretch()
        self.live_button = self._icon_button('chart', '目前持倉')
        self.live_button.setObjectName('sideLivePnlButton')
        self.live_button.setCheckable(True)
        self.live_button.toggled.connect(self._toggle_live)
        row.addWidget(self.live_button)
        self.update_button = self._icon_button('refresh', '更新數值')
        self.update_button.clicked.connect(self.update_values)
        row.addWidget(self.update_button)
        self.collapse_button = self._icon_button('panel-right-close', '收起側邊快捷')
        self.collapse_button.setToolTip('按一下收起，按住可上下拖動')
        self.collapse_button.installEventFilter(self)
        self.collapse_button.clicked.connect(lambda: self.set_collapsed(True))
        row.addWidget(self.collapse_button)
        root.addWidget(header)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet('background: rgba(218,210,233,50);')
        root.addWidget(divider)
        for widget in (header, title):
            widget.installEventFilter(self)
        self._drag_widgets = (header, title)

        lots_row = QHBoxLayout()
        self.lots = {}
        for role, caption in (('internal', '場內手數'), ('external', '場外手數')):
            column = QVBoxLayout()
            label = QLabel(caption)
            label.setProperty('muted', True)
            label.setAlignment(Qt.AlignCenter)
            value = QLabel('—')
            value.setAlignment(Qt.AlignCenter)
            value.setStyleSheet('font-size: 20px; font-weight: 400;')
            column.addWidget(label)
            column.addWidget(value)
            lots_row.addLayout(column, 1)
            self.lots[role] = value
        root.addLayout(lots_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        # Reuse the existing combo's arrow rendering and item values.
        self.direction = type(app.internal_direction_input)()
        self.direction.addItem('買入', 'BUY')
        self.direction.addItem('賣出', 'SELL')
        self.direction.setAccessibleName('側邊場內方向')
        self.direction.currentIndexChanged.connect(app.internal_direction_input.setCurrentIndex)
        self.inputs = {}
        self.warnings = {}
        controls = [('場內方向', self.direction)]
        for key, caption in (('expected_sl_combined', '預期 SL'),
                             ('internal_balance', '場內餘額'), ('daily_pnl', '每日獲利／虧損')):
            entry = QLineEdit()
            palette = entry.palette()
            palette.setColor(QPalette.PlaceholderText, QColor('#8b8498'))
            entry.setPalette(palette)
            entry.setAccessibleName('側邊' + caption)
            entry.textEdited.connect(app.parameter_inputs[key].setText)
            entry.returnPressed.connect(app.parameter_inputs[key].returnPressed.emit)
            self.inputs[key] = entry
            if key in ('expected_sl_combined', 'internal_balance', 'daily_pnl'):
                entry.setTextMargins(0, 0, 16, 0)
                badge = type(app.expected_sl_warning_badge)(entry)
                badge.setCursor(Qt.PointingHandCursor)
                badge.setToolTip('請先確認保證金比例相關規則。' if key == 'expected_sl_combined'
                                 else '每日獲利/虧損數值可能有誤，請確認後修改並更新。' if key == 'daily_pnl'
                                 else '請確認並修改場內餘額，更新成功後再操作。')
                badge.hide()
                badge.installEventFilter(self)
                entry.installEventFilter(self)
                self.warnings[key] = badge
            if key == 'internal_balance':
                # Same as the main window: read icon flush inside the box.
                from .gui import _InlineFieldControls
                self.read_balance_button = QToolButton(entry)
                self.read_balance_button.setObjectName('sideReadBalance')
                self.read_balance_button.setIcon(themed_icon('download', '#9a90b0', 14))
                self.read_balance_button.setCursor(Qt.PointingHandCursor)
                self.read_balance_button.setFixedSize(28, 28)
                self.read_balance_button.setToolTip('讀取場內餘額')
                self.read_balance_button.setStyleSheet(
                    'QToolButton#sideReadBalance { background: transparent; border: 0; border-radius: 5px;'
                    ' padding: 0; }'
                    'QToolButton#sideReadBalance:hover { background: #26232f; }')
                self.read_balance_button.clicked.connect(lambda: app.balance_button_clicked('side'))
                entry.setTextMargins(0, 0, 44, 0)
                self._balance_inline = _InlineFieldControls(entry, (), self.read_balance_button)
            controls.append((caption, entry))
        for index, (caption, widget) in enumerate(controls):
            label = QLabel(caption)
            label.setProperty('muted', True)
            if widget is self.inputs.get('internal_balance'):
                # 「~」「−」 on the caption row's right: no width taken from the box.
                head = QWidget()
                head_layout = QHBoxLayout(head)
                head_layout.setContentsMargins(0, 0, 0, 0)
                head_layout.setSpacing(3)
                head_layout.addWidget(label)
                head_layout.addStretch(1)
                self.balance_prefix_buttons = {}
                for symbol in ('~', '-'):
                    key_button = QToolButton(head)
                    key_button.setObjectName('sideBalancePrefix' + ('Tilde' if symbol == '~' else 'Minus'))
                    key_button.setText('~' if symbol == '~' else '\u2212')
                    key_button.setCheckable(True)
                    key_button.setFixedSize(16, 16)
                    key_button.setCursor(Qt.PointingHandCursor)
                    key_button.setStyleSheet(
                        'QToolButton { padding: 0; min-height: 0; font-size: 11px; border: 1px solid #4a4356;'
                        ' border-radius: 3px; background: #1d1b24; color: #d8d2e4; }'
                        'QToolButton:hover { background: #292733; border-color: #62568e; }'
                        'QToolButton:checked { background: #3a2f6e; border-color: #8a6fe0; color: #ffffff; }')
                    key_button.clicked.connect(lambda _c=False, s=symbol: app._toggle_balance_prefix(s))
                    head_layout.addWidget(key_button)
                    self.balance_prefix_buttons[symbol] = key_button
                grid.addWidget(head, (index // 2) * 2, index % 2)
                grid.addWidget(widget, (index // 2) * 2 + 1, index % 2)
                continue
            grid.addWidget(label, (index // 2) * 2, index % 2)
            grid.addWidget(widget, (index // 2) * 2 + 1, index % 2)
        root.addLayout(grid)
        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.fill_button = QPushButton('填入兩邊')
        self.fill_button.setObjectName('sideFill')
        self.fill_button.setFixedHeight(36)
        self.fill_button.setIcon(themed_icon('arrow-left-right', '#ffffff', 16))
        self.fill_button.clicked.connect(app.fill_both_from_side_panel)
        actions.addWidget(self.fill_button, 1)
        self.close_both_button = QToolButton()
        self.close_both_button.setObjectName('sideCloseBoth')
        self.close_both_button.setAccessibleName('兩邊平倉')
        self.close_both_button.setToolTip('兩邊平倉：平掉場內、場外全部持倉（會確認兩次）')
        self.close_both_button.setIcon(themed_icon('square-x', '#c9b8ff', 16))
        self.close_both_button.setFixedSize(36, 36)
        self.close_both_button.clicked.connect(app.close_both_from_side_panel)
        actions.addWidget(self.close_both_button)
        home = self._icon_button('home', '開啟主畫面')
        home.setObjectName('sideHome')
        home.setFixedSize(36, 36)
        home.clicked.connect(self.open_main)
        actions.addWidget(home)
        root.addLayout(actions)
        progress = QLabel('帳號進度')
        self.progress_label = progress
        progress.setAlignment(Qt.AlignCenter)
        progress_layout = QVBoxLayout()
        progress_layout.setContentsMargins(0, 20, 0, 0)
        progress_layout.setSpacing(0)
        progress_layout.addWidget(progress)
        self.ruler = AccountRuler(compact=True)
        progress_layout.addWidget(self.ruler)
        root.addLayout(progress_layout)

        self.events_button = EventSummaryButton()
        self.events_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.events_button.setCheckable(True)
        # Small equilateral triangle instead of Qt's wide, flat arrow.
        from .ui_theme import triangle_icon
        self.events_button.setArrowType(Qt.NoArrow)
        self.events_button.setIconSize(QSize(12, 12))
        self.events_button.setIcon(triangle_icon("left"))
        self.events_button.setAccessibleName('重大事件')
        self.events_button.toggled.connect(self._expand_events)
        root.addWidget(self.events_button)
        self.event_flyout = EventFlyout(self, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.event_flyout.setObjectName('eventFlyout')
        self.event_flyout.setWindowTitle('重大事件')
        self.event_flyout.setAttribute(Qt.WA_TranslucentBackground)
        self.event_flyout.installEventFilter(self)
        flyout_layout = QVBoxLayout(self.event_flyout)
        flyout_layout.setContentsMargins(12, 10, 12, 12)
        from .event_feed import EventFeedView
        self.calendar = app._get_event_calendar()
        self.event_view = EventFeedView(lambda: self.calendar, self.event_flyout,
                                        title='重大事件', close=self.events_button.setChecked, compact=True,
                                        show_countdown=False)
        flyout_layout.addWidget(self.event_view)
        # Shared view attributes retained for the sidebar's preview controls.
        for name in ('event_tabs', 'event_rows', 'news_rows', 'event_status', 'source_details'):
            setattr(self, name, getattr(self.event_view, name))
        self.event_flyout.hide()
        self.live_flyout = EventFlyout(self, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.live_flyout.setObjectName('liveFlyout')
        self.live_flyout.setWindowTitle('目前持倉')
        self.live_flyout.setAttribute(Qt.WA_TranslucentBackground)
        live_layout = QVBoxLayout(self.live_flyout)
        live_layout.setContentsMargins(14, 8, 10, 10)
        live_head = QHBoxLayout()
        live_title = QLabel('目前持倉', self.live_flyout)
        live_title.setStyleSheet('font-size: 13px; font-weight: 600;')
        live_head.addWidget(live_title)
        # Which 方案's position is shown (same look as the panel's subtitle).
        from .compact_controls import LiveProfileCombo
        self.live_profile = LiveProfileCombo(self.live_flyout)
        self.live_profile.setObjectName('liveProfileSelector')
        self.live_profile.setAccessibleName('目前持倉方案')
        self.live_profile.textActivated.connect(self.app.set_live_preference)
        live_head.addWidget(self.live_profile, 0, Qt.AlignBottom)
        live_head.addStretch(1)
        # 「›」 at the header's top-right closes the panel.
        self.live_collapse = QToolButton(self.live_flyout)
        self.live_collapse.setObjectName('liveFlyoutCollapse')
        self.live_collapse.setText('›')
        self.live_collapse.setToolTip('收起目前持倉')
        self.live_collapse.setFixedSize(22, 22)
        self.live_collapse.setStyleSheet(
            'QToolButton{background:transparent;border:none;border-radius:5px;'
            'color:#c9b8ff;padding:0;font-size:16px;}QToolButton:hover{background:#2c2540;}')
        self.live_collapse.clicked.connect(lambda: self.live_button.setChecked(False))
        live_head.addWidget(self.live_collapse)
        live_layout.addLayout(live_head)
        from .live_pnl_view import LivePnlBar
        self.live_bar = LivePnlBar(self.live_flyout, compact=True)
        live_layout.addWidget(self.live_bar)
        self.live_flyout.hide()
        self.live_flyout.installEventFilter(self)
        app.signals.live_pnl.connect(self._show_live)
        self._warning_key = None
        self._warning_context = None
        self.warning_flyout = WarningFlyout(self, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.warning_flyout.setWindowTitle('側欄提醒說明')
        self.warning_flyout.setWindowModality(Qt.NonModal)
        self.warning_flyout.setAttribute(Qt.WA_TranslucentBackground)
        self.warning_flyout.setFocusPolicy(Qt.StrongFocus)
        warning_layout = QVBoxLayout(self.warning_flyout)
        warning_layout.setContentsMargins(13, 9, 21, 13)
        warning_layout.setSpacing(10)
        warning_header = QHBoxLayout()
        self.warning_title = QLabel()
        self.warning_title.setTextFormat(Qt.PlainText)
        warning_header.addWidget(self.warning_title, 1)
        warning_close = type(app.chrome_close)('close', self.warning_flyout)
        warning_close.setFixedSize(24, 24)
        warning_close.setAccessibleName('關閉提醒說明')
        warning_close.clicked.connect(self._hide_warning)
        warning_header.addWidget(warning_close)
        warning_layout.addLayout(warning_header)
        self.warning_numbers = QLabel()
        self.warning_numbers.setTextFormat(Qt.PlainText)
        self.warning_numbers.setTextInteractionFlags(Qt.TextSelectableByMouse)
        warning_layout.addWidget(self.warning_numbers)
        self.warning_text = QLabel()
        self.warning_text.setTextFormat(Qt.PlainText)
        self.warning_text.setWordWrap(True)
        self.warning_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        warning_layout.addWidget(self.warning_text)
        self.warning_flyout.hide()
        QApplication.instance().installEventFilter(self)
        self.calendar.changed.connect(self.update_events)
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(300)
        self.sync_timer.timeout.connect(self.sync_from_main)
        self.sync_timer.start()
        self.event_timer = QTimer(self)
        self.event_timer.setInterval(30_000)
        self.event_timer.timeout.connect(self.update_events)
        self.event_timer.timeout.connect(self.calendar.refresh)
        self.event_timer.start()
        self.summary_timer = QTimer(self)
        self.summary_timer.setInterval(1000)
        self.summary_timer.timeout.connect(self.update_event_summary)
        self.summary_timer.start()
        self._screen.availableGeometryChanged.connect(self.dock)
        self.sync_from_main()
        self.update_events()
        self.set_collapsed(False)

    def _icon_button(self, icon, caption):
        button = QToolButton(self)
        button.setIcon(themed_icon(icon))
        button.setToolTip(caption)
        button.setAccessibleName(caption)
        button.setFixedSize(24, 24)
        return button

    def start(self):
        self.sync_timer.start()
        self.event_timer.start()
        self.summary_timer.start()
        self.show()
        self.dock()
        self.calendar.refresh()

    def suspend(self):
        self._cancel_collapse_drag()
        self._cancel_handle_drag()
        self.hide()
        self.sync_timer.stop()
        self.event_timer.stop()
        self.summary_timer.stop()

    def sync_from_main(self):
        if self.isVisible() and not self._handle_dragging:
            self.dock()
        app = self.app
        busy = bool(app._active_tasks or app._parameter_write_active
                    or app._trade_settings_busy or app._update_in_progress
                    or app._fill_waiting_for_sheet)
        for key, entry in self.inputs.items():
            source = app.parameter_inputs[key]
            if entry.text() != source.text():
                entry.setText(source.text())
            if key == 'internal_balance' and hasattr(self, 'balance_prefix_buttons'):
                tilde, minus, _body = app._split_balance_prefix(source.text())
                for symbol, state in (('~', tilde), ('-', minus)):
                    button = self.balance_prefix_buttons[symbol]
                    if button.isChecked() != state:
                        button.setChecked(state)
                    button.setEnabled(not busy and source.isEnabled())
            entry.setPlaceholderText(source.placeholderText())
            entry.setEnabled(not busy and source.isEnabled())
        with QSignalBlocker(self.direction):
            self.direction.setCurrentIndex(app.internal_direction_input.currentIndex())
        self.direction.setEnabled(not busy and app.internal_direction_input.isEnabled())
        for role, label in self.lots.items():
            raw = app.data_labels[role + '_lot'].text()
            try:
                value = Decimal(raw)
                label.setText(f'{value:.2f}' if value.is_finite() else '—')
            except InvalidOperation:
                label.setText(raw or '—')
        profiles = app.profile_combo
        with QSignalBlocker(self.profile_selector):
            names = [profiles.itemText(i) for i in range(profiles.count())]
            if names != [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
                self.profile_selector.clear()
                self.profile_selector.addItems(names)
            self.profile_selector.setCurrentIndex(profiles.currentIndex())
        self.profile_selector.setEnabled(not busy and profiles.isEnabled())
        source = app.stage_selector
        with QSignalBlocker(self.stage_selector):
            options = [source.itemText(i) for i in range(source.count())]
            if options != [self.stage_selector.itemText(i) for i in range(self.stage_selector.count())]:
                self.stage_selector.clear()
                self.stage_selector.addItems(options)
            self.stage_selector.setCurrentIndex(source.currentIndex())
        self.stage_selector.setEnabled(not busy and source.isEnabled())
        self.stage_selector.setToolTip(source.toolTip())
        if (self.ruler.state != app.account_ruler.state
                or self.ruler.placeholder != app.account_ruler.placeholder):
            self.ruler.set_state(app.account_ruler.state, app.account_ruler.placeholder)
        self.fill_button.setEnabled(not busy and app.action_buttons['填入兩邊'].isEnabled())
        self.close_both_button.setEnabled(not busy)
        self.update_button.setEnabled(not busy)
        # Same rule as the main window: a 每日獲利/虧損 reason (e.g. 「已達到
        # 獲利目標」) puts the "!" on that field instead of 場內餘額.
        balance_active = app._balance_warning_active()
        on_pnl = balance_active and app._pnl_warning(app._balance_range_warning_detail())
        for key, visible in (
            ('expected_sl_combined', app._expected_sl_warning_values() is not None),
            ('internal_balance', balance_active and not on_pnl),
            ('daily_pnl', on_pnl),
        ):
            badge = self.warnings[key]
            badge.setVisible(visible)
            if key == 'internal_balance':
                badge.setToolTip(app.balance_warning_badge.toolTip())
            badge.move(max(0, self.inputs[key].width() - 14), 1)
            badge.raise_()
        if self._warning_key is not None:
            if (busy or self._warning_context != app._trade_settings_context()
                    or not self.warnings[self._warning_key].isVisible()):
                self._hide_warning()
            else:
                self._update_warning_content(self._warning_key)
                self._position_warning_flyout()

    def update_values(self):
        if not self.update_button.isEnabled():
            return
        if any(entry.text().strip() for entry in self.app.parameter_inputs.values()):
            self.app.parameter_update_button.click()
        else:
            self.app.read_sheet()
        self.calendar.refresh()

    def open_main(self):
        self.set_collapsed(True)
        self.app._side_fill_active = False
        if self.app.isMinimized():
            self.app.showNormal()
        else:
            self.app.show()
        self.app.raise_()
        self.app.activateWindow()

    def _show_warning(self, key):
        if self._warning_key == key and self.warning_flyout.isVisible():
            self._hide_warning()
            return
        if self.collapsed or not self.isVisible() or not self._update_warning_content(key):
            return
        self.events_button.setChecked(False)
        self._warning_key = key
        self._warning_context = self.app._trade_settings_context()
        self._position_warning_flyout()
        self.warning_flyout.show()
        self.warning_flyout.raise_()
        self.warning_flyout.activateWindow()
        self.warning_flyout.setFocus(Qt.OtherFocusReason)

    def _update_warning_content(self, key):
        if key == 'expected_sl_combined':
            values = self.app._expected_sl_warning_values()
            if values is None:
                return False
            original, adjusted = values
            title = '預期 SL 提醒'
            numbers = f'原始 SL：{original} 點\n預期 SL：{adjusted} 點'
            message = '手數可能增加，請先確認保證金比例相關規則。'
        elif key == 'daily_pnl':
            reason = self.app._balance_range_warning_detail()
            if not self.app._balance_warning_active() or not self.app._pnl_warning(reason):
                return False
            title = '每日獲利／虧損提醒'
            value = self.inputs['daily_pnl'].text().strip() or self.inputs['daily_pnl'].placeholderText()
            numbers = '每日獲利／虧損：' + value if value else ''
            message = reason.rstrip('。') + '。\n請確認平台實際數值後修改並更新，再操作。'
        else:
            if not self.app._balance_warning_active():
                return False
            title = '場內餘額提醒'
            balance, _ = self.app._cash_reference_values()
            numbers = '' if balance is None else '場內餘額：'+money(balance)
            reason = self.app._balance_range_warning_detail()
            message = reason+'\n請確認並修改數值，更新後再操作。'
        for label, text in ((self.warning_title, title), (self.warning_numbers, numbers), (self.warning_text, message)):
            if label.text() != text:
                label.setText(text)
        self.warning_numbers.setVisible(bool(numbers))
        return True

    def _position_warning_flyout(self):
        if self._warning_key is None or self._valid_screen() is None:
            return
        area = self._screen.availableGeometry()
        popup = self.warning_flyout
        left = min(self.x(), self.live_flyout.x() if self.live_flyout.isVisible() else self.x())
        popup.setFixedWidth(min(268, max(160, left-area.left()-8), area.width()))
        popup.adjustSize()
        anchor = self.warnings[self._warning_key].mapToGlobal(
            self.warnings[self._warning_key].rect().center())
        y = max(area.top(), min(anchor.y()-popup.height()//2, area.bottom()-popup.height()+1))
        left = min(self.x(), self.live_flyout.x() if self.live_flyout.isVisible() else self.x())
        popup.move(max(area.left(), left-popup.width()-8), y)
        popup.tip_y = max(16, min(popup.height()-16, anchor.y()-y))
        popup.update()

    def _hide_warning(self):
        self._warning_key = None
        self.warning_flyout.hide()

    def _expand_events(self, expanded):
        from .ui_theme import triangle_icon
        self.events_button.setIcon(triangle_icon("right" if expanded else "left"))
        self.event_flyout.setVisible(expanded and not self.collapsed)
        if expanded:
            self._hide_warning()
            self.event_status.setChecked(False)
            self._position_event_flyout()
            self._position_live_flyout()
            self.event_flyout.raise_()
            self.event_flyout.activateWindow()
            self.calendar.refresh()

    def _toggle_live(self, opened):
        if not opened:
            self.live_bar.dismiss_closed()
        self._show_live(getattr(self.app, 'live_pnl_payload', None))
        self.live_flyout.setVisible(opened)
        # 重大事件 gets shorter / back to full height so both fit one column.
        self._position_event_flyout()
        if opened:
            self._position_live_flyout()
            self.live_flyout.raise_()

    def _show_live(self, value):
        """value: {"profile", "choices", "state"}; no position anywhere -> the
        active 方案's name, plain."""
        self.live_bar.set_state((value or {}).get('state'))
        self.live_bar.set_closed(self.app.shown_after_close_card(value or {})
                                 if hasattr(self.app, 'shown_after_close_card') else None)
        self.live_profile.show_payload(value, self.app.profiles.active_name)

    LIVE_FLYOUT_HEIGHT = 176

    def _live_drag(self, event) -> bool:
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._live_drag_offset = event.globalPosition().toPoint().y() - self.y()
            return True
        offset = getattr(self, '_live_drag_offset', None)
        if offset is None:
            return False
        if kind == QEvent.MouseMove:
            self._y = event.globalPosition().toPoint().y() - offset
            self.dock()
            return True
        if kind == QEvent.MouseButtonRelease:
            self._live_drag_offset = None
            self._y = self.y()
            self.app.store.data['ui']['side_panel_y'] = self._y
            self.app.save_ui_state()
            return True
        return False
    FLYOUT_WIDTH = 360

    def popup_left_edge(self) -> int:
        """Left edge of the panel plus its open 目前持倉 / 重大事件 panels:
        notifications go to the left of all of them, never on top."""
        edges = [self.frameGeometry().left()]
        for flyout in (self.live_flyout, self.event_flyout):
            if flyout.isVisible():
                edges.append(flyout.frameGeometry().left())
        return min(edges)

    def _position_live_flyout(self):
        if not self.live_flyout.isVisible() or self._valid_screen() is None:
            return
        area = self._screen.availableGeometry()
        width, height = self.FLYOUT_WIDTH, self.LIVE_FLYOUT_HEIGHT
        right = self.x() - 8
        top = max(area.top(), min(self.y(), area.bottom() - height + 1))
        # 重大事件 open too: side by side only when they would overlap;
        # otherwise both sit right next to the side panel (one above the other).
        if self.event_flyout.isVisible():
            other = self.event_flyout.geometry()
            if top < other.bottom() + 8 and top + height > other.top() - 8:
                right = other.x() - 8
        self.live_flyout.setFixedSize(width, height)
        self.live_flyout.move(max(area.left(), right - width), top)

    def _position_event_flyout(self):
        if not self.event_flyout.isVisible() or self._valid_screen() is None:
            return
        area = self._screen.availableGeometry()
        width = min(self.FLYOUT_WIDTH, max(160, self.x() - area.left() - 8))
        height = min(420, area.height() - 16)
        if self.live_flyout.isVisible():
            # 目前持倉 sits at the top: 重大事件 takes the space below it
            # (bottom still level with the side panel), so they stack
            # instead of standing side by side.
            room = self.height() - self.LIVE_FLYOUT_HEIGHT - 8
            height = max(240, min(height, room))
        self.event_flyout.setFixedSize(width, height)
        self.event_flyout.move(max(area.left(), self.x() - width - 8),
            max(area.top(), min(self.y()+self.height()-height, area.bottom()-height+1)))

    def _profile_selected(self, value):
        if not self.profile_selector.isEnabled() or value == self.app.profile_combo.currentText():
            return
        # Any question the switch asks appears beside the side panel.
        self.app._side_action_active = True
        try:
            self.app.profile_combo.setCurrentText(value)
        finally:
            self.app._side_action_active = False
        self.sync_from_main()

    def _stage_selected(self, value):
        if self.stage_selector.isEnabled():
            self.app.stage_selector.setCurrentText(value)
            self.sync_from_main()

    def update_event_summary(self):
        from .calendar_events import events_for_display
        now = datetime.now(UTC)
        events = events_for_display(self.calendar, now)
        upcoming = [event for event in events if now < event.when <= now + timedelta(days=45)]
        stale = self.calendar.error or not self.calendar.is_fresh(now)
        settings = self.app.store.data.get('ui', {}).get('trading_day_separator', {})
        start, end = trading_session(now, settings)
        summary = event_summary(upcoming+[e for e in events if start <= e.when <= now],
                                now, settings, self.calendar.covers_day(start, end, now), self.calendar.title)
        self.events_button.setText(summary)
        tooltip = (summary+f'\n今日事件範圍：{start:%m/%d %H:%M}–{end:%m/%d %H:%M}（台北，依切日設定）'
                   '\n按一下查看詳情。'+ ('\n部分來源資料待更新。' if stale else ''))
        for event in upcoming[:6]:
            tooltip += f'\n{event.when.astimezone(TAIPEI):%m/%d} {format_event_time(event.when)} · {event.currency} · {self.calendar.title(event.title)}'
        self.events_button.setToolTip(tooltip)

    def update_events(self):
        self.update_event_summary()
        self.event_view.update_events()

    def set_collapsed(self, collapsed):
        was_collapsed = self.collapsed
        if collapsed and not was_collapsed:
            self._y = self.y()
            self.app.store.data['ui']['side_panel_y'] = self._y
            self.app.save_ui_state()
        if collapsed:
            self._hide_warning()
            self.events_button.setChecked(False)
            # 目前持倉 stays open on its own next to the small ball.
        self.collapsed = collapsed
        self.clearMask()
        self.body.setVisible(not collapsed)
        self.handle.setVisible(collapsed)
        self.layout().setContentsMargins(*((0, 0, 0, 0) if collapsed else (14, 10, 14, 10)))
        self._fit_contents()
        self.dock()
        self.live_flyout.setVisible(self.live_button.isChecked())
        self._position_live_flyout()

    def _fit_contents(self):
        if self.collapsed:
            self.handle.setFixedSize(28, self.PARKED_HEIGHT)
            self.setFixedSize(28, self.PARKED_HEIGHT)
            return
        # adjustSize alone retains the expanded layout's old minimum height
        # after hiding its scroll area. Recompute before fixing the height.
        self.setFixedWidth(self.WIDTH)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.body.layout().invalidate()
        self.body.layout().activate()
        self.body.updateGeometry()
        self.layout().invalidate()
        self.layout().activate()
        self.setFixedHeight(self.layout().sizeHint().height())

    def _valid_screen(self):
        """The docking screen, re-resolved if Windows replaced it.

        Display sleep/wake or a resolution/RDP change can delete the QScreen
        captured at startup; using it then raised "Internal C++ object
        (QScreen) already deleted" (seen when switching profiles).
        """
        screen = self._screen
        if screen is not None and shiboken6.isValid(screen):
            return screen
        replacement = self.screen() or QGuiApplication.primaryScreen()
        if replacement is not None and shiboken6.isValid(replacement):
            replacement.availableGeometryChanged.connect(self.dock)
            self._screen = replacement
            return replacement
        self._screen = None
        return None

    def dock(self, *_):
        if self._valid_screen() is None or self._handle_dragging:
            return
        area = self._screen.availableGeometry()
        self.move(area.right() - self.width() + 1,
                  max(area.top(), min(self._y, area.bottom() - self.height() + 1)))
        if self.isVisible():
            ensure_native_sidebar(self, self._screen,
                max(area.top(), min(self._y, area.bottom()-self.height()+1)),
                self.app.store.path.parent/'diagnostics'/'side-panel-geometry.json')
        self._position_event_flyout()
        self._position_warning_flyout()
        self._position_live_flyout()

    def _schedule_dock(self):
        # Windows can deliver the native resize/move after set_collapsed has
        # already parked the old size. Re-evaluate once that geometry settles.
        timer = getattr(self, '_dock_timer', None)
        if timer is not None and self.isVisible() and not self._handle_dragging:
            timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_dock()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_dock()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_dock()
        if hasattr(self, 'live_button') and self.live_button.isChecked():
            self.live_flyout.show()
            self._position_live_flyout()

    def _begin_handle_drag(self):
        if self._handle_pointer is None or not self.collapsed:
            return
        if self.live_flyout.isVisible():
            return  # 目前持倉 open: the ball only slides along the edge
        self._handle_dragging = True
        self.handle.setCursor(Qt.ClosedHandCursor)
        self.handle.setFixedSize(self.HANDLE_HEIGHT, self.HANDLE_HEIGHT)
        self.setFixedSize(self.HANDLE_HEIGHT, self.HANDLE_HEIGHT)
        self.setMask(QRegion(self.rect(), QRegion.Ellipse))
        self._move_handle_drag(self._handle_pointer)
        self.update()

    def _move_handle_drag(self, point):
        screen = QGuiApplication.screenAt(point) or self._valid_screen()
        if screen is not None and screen is not self._screen:
            if self._screen is not None and shiboken6.isValid(self._screen):
                self._screen.availableGeometryChanged.disconnect(self.dock)
            self._screen = screen
            self._screen.availableGeometryChanged.connect(self.dock)
        if self._screen is None:
            return
        area = self._screen.availableGeometry()
        radius = self.HANDLE_HEIGHT // 2
        self.move(max(area.left(), min(point.x() - radius, area.right() - self.width() + 1)),
                  max(area.top(), min(point.y() - radius, area.bottom() - self.height() + 1)))

    def _release_handle(self, point):
        self._hold_timer.stop()
        dragging = self._handle_dragging
        if dragging:
            self._move_handle_drag(point)
            # Centre the (shorter) parked tab on where the ball was dropped.
            self._y = self.y() + self.HANDLE_HEIGHT // 2 - self.PARKED_HEIGHT // 2
        self._handle_dragging = False
        self._handle_press = self._handle_pointer = None
        self.handle.releaseMouse()
        self.handle.setCursor(Qt.OpenHandCursor)
        self.set_collapsed(dragging)
        if dragging:
            # Persist only the parked handle, never the temporary upward
            # offset needed to fit the expanded panel above the taskbar.
            self.app.store.data['ui']['side_panel_y'] = self._y
            self.app.save_ui_state()

    def _cancel_handle_drag(self):
        self._hold_timer.stop()
        if self._handle_press is None:
            return
        self._handle_dragging = False
        self._handle_press = self._handle_pointer = None
        self.handle.releaseMouse()
        self.handle.setCursor(Qt.OpenHandCursor)
        self.set_collapsed(True)

    def _cancel_collapse_drag(self):
        if self._collapse_press is not None:
            self._collapse_press = None
            self._collapse_moved = False
            self.collapse_button.releaseMouse()

    def eventFilter(self, watched, event):
        news = getattr(self, 'event_flyout', None)
        if news is not None and news.isVisible():
            if event.type() == QEvent.ApplicationDeactivate:
                self.events_button.setChecked(False)
            elif event.type() == QEvent.MouseButtonPress:
                # Native QWindow receives the press before its QWidget child.
                # Testing only QWidget.window() misclassifies real inside clicks.
                point = event.globalPosition().toPoint()
                target = watched if isinstance(watched, QWidget) else None
                inside = ((target in (self, news) or news.isAncestorOf(target) or self.isAncestorOf(target))
                          if target is not None else
                          (news.frameGeometry().contains(point) or self.frameGeometry().contains(point)))
                if not inside:
                    self.events_button.setChecked(False)
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.events_button.setChecked(False)
                return True
        popup = getattr(self, 'warning_flyout', None)
        if popup is not None and popup.isVisible():
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._hide_warning()
                return True
            if event.type() == QEvent.ApplicationDeactivate:
                self._hide_warning()
            elif event.type() == QEvent.MouseButtonPress:
                point = event.globalPosition().toPoint()
                on_badge = any(badge.isVisible() and QRect(badge.mapToGlobal(QPoint()), badge.size()).contains(point)
                               for badge in self.warnings.values())
                if not popup.frameGeometry().contains(point) and not on_badge:
                    self._hide_warning()
        if watched is getattr(self, 'event_flyout', None) and event.type() == QEvent.Close:
            self.events_button.setChecked(False)
        if watched is self.collapse_button:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._collapse_press = event.globalPosition().toPoint()
                self._collapse_start_y = self.y()
                self._collapse_moved = False
                self.collapse_button.grabMouse()
                return True
            if event.type() == QEvent.MouseMove and self._collapse_press is not None:
                delta = event.globalPosition().toPoint() - self._collapse_press
                self._collapse_moved |= delta.manhattanLength() >= QGuiApplication.styleHints().startDragDistance()
                if self._collapse_moved:
                    self._y = self._collapse_start_y + delta.y()
                    self.dock()
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._collapse_press is not None:
                self._collapse_press = None
                self.collapse_button.releaseMouse()
                if self._collapse_moved:
                    self._y = self.y()
                    self.app.store.data['ui']['side_panel_y'] = self._y
                    self.app.save_ui_state()
                else:
                    self.set_collapsed(True)
                return True
        if watched is self.handle:
            # Windows delivers a quick second press as a double-click event.
            if (event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick)
                    and event.button() == Qt.LeftButton):
                self._handle_press = self._handle_pointer = event.globalPosition().toPoint()
                self._edge_start_y, self._edge_moved = self.y(), False
                self._hold_timer.start()
                self.handle.grabMouse()
                return True
            if (event.type() == QEvent.MouseMove and self._handle_press is not None
                    and self.live_flyout.isVisible()):
                # 目前持倉 open: slide ball + panel together, up / down only.
                delta = event.globalPosition().toPoint() - self._handle_press
                if delta.manhattanLength() >= QGuiApplication.styleHints().startDragDistance():
                    self._hold_timer.stop()
                    self._edge_moved = True
                if self._edge_moved:
                    self._y = self._edge_start_y + delta.y()
                    self.dock()
                return True
            if (event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton
                    and self._handle_press is not None and getattr(self, '_edge_moved', False)):
                self._hold_timer.stop()
                self._handle_press = self._handle_pointer = None
                self._edge_moved = False
                self.handle.releaseMouse()
                self._y = self.y()
                self.app.store.data['ui']['side_panel_y'] = self._y
                self.app.save_ui_state()
                return True
            if event.type() == QEvent.MouseMove and self._handle_press is not None:
                self._handle_pointer = event.globalPosition().toPoint()
                if not self._handle_dragging and (self._handle_pointer - self._handle_press).manhattanLength() >= QGuiApplication.styleHints().startDragDistance():
                    self._hold_timer.stop()
                    self._begin_handle_drag()
                if self._handle_dragging:
                    self._move_handle_drag(self._handle_pointer)
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._handle_press is not None:
                if self._handle_dragging:
                    self._release_handle(event.globalPosition().toPoint())
                    return True
                self._hold_timer.stop()
                self._handle_press = self._handle_pointer = None
                self.handle.releaseMouse()
                if self._click_timer.isActive():
                    self._click_timer.stop()
                    self.live_button.setChecked(not self.live_button.isChecked())
                else:
                    self._click_timer.start()
                return True
        for key, badge in getattr(self, 'warnings', {}).items():
            if watched is badge and event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    self._show_warning(key)
                    return True
            if watched is self.inputs[key] and event.type() == QEvent.Resize:
                badge.move(max(0, watched.width() - 14), 1)
                badge.raise_()
        if watched is getattr(self, 'live_flyout', None) and self._live_drag(event):
            return True
        if watched not in self._drag_widgets:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint().y() - self.y()
        elif event.type() == QEvent.MouseMove and self._drag_offset is not None:
            self._y = event.globalPosition().toPoint().y() - self._drag_offset
            self.dock()
        elif event.type() == QEvent.MouseButtonRelease and self._drag_offset is not None:
            self._drag_offset = None
            self._y = self.y()
            self.app.store.data['ui']['side_panel_y'] = self._y
            self.app.save_ui_state()
        return super().eventFilter(watched, event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(245, 243, 250, 70), 0.7))
        painter.setBrush(QColor('#08080b'))
        rect = QRectF(0.35, 0.35, self.width() - 0.7, self.height() - 0.7)
        if self._handle_dragging or self.collapsed:
            # Parked / dragged handle: deep purple, so it does not vanish
            # against dark windows the way the near-black body did.
            painter.setPen(QPen(QColor('#8a6fe0'), 0.9))
            painter.setBrush(QColor('#4a2f96'))
        if self._handle_dragging:
            painter.drawEllipse(rect)
        elif self.collapsed:
            # The rounded left cap extends beyond the right edge so the
            # parked handle meets the screen with no transparent gap.
            painter.drawRoundedRect(rect.adjusted(0, 0, 12, 0), 10, 10)
        else:
            painter.drawRoundedRect(rect, 10, 10)

    def closeEvent(self, event):
        self._hide_warning()
        QApplication.instance().removeEventFilter(self)
        self._cancel_collapse_drag()
        self.event_flyout.close()
        self._cancel_handle_drag()
        self.sync_timer.stop()
        self.event_timer.stop()
        self.summary_timer.stop()
        super().closeEvent(event)

    def hideEvent(self, event):
        if hasattr(self, 'warning_flyout'):
            self._hide_warning()
        self._cancel_collapse_drag()
        if hasattr(self, 'events_button'):
            self.events_button.setChecked(False)
        if hasattr(self, 'live_flyout'):
            # Hidden for an operation: never leave it over the broker windows.
            self.live_flyout.hide()
        super().hideEvent(event)

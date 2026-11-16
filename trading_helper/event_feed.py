"""Shared, read-only event feed for the main workspace and sidebar."""
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QTabWidget, QScrollArea,
)
from .calendar_events import UTC, TAIPEI
from .event_summary import relevant_announcement
from .ui_theme import themed_icon


class EventFeedView(QWidget):
    def __init__(self, get_calendar, parent=None, *, title='消息與事件', close=None):
        super().__init__(parent)
        self._get_calendar = get_calendar
        self.calendar = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(QLabel(title), 1)
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(themed_icon('refresh'))
        self.refresh_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.refresh_button.setAccessibleName('更新事件資料')
        self.refresh_button.setToolTip('重新抓取所有消息來源')
        self.refresh_button.clicked.connect(self.manual_refresh)
        header.addWidget(self.refresh_button)
        if close is not None:
            from .window_chrome import WindowChromeButton
            button = WindowChromeButton('close', self)
            button.setFixedSize(24, 24)
            button.clicked.connect(lambda: close(False))
            header.addWidget(button)
        root.addLayout(header)
        self.event_tabs = QTabWidget()
        self.event_rows, self.news_rows = (QLabel() for _ in range(2))
        for caption, label in zip(('即將發生', '已公布／新聞'), (self.event_rows, self.news_rows)):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignTop)
            label.setStyleSheet('padding: 10px 2px;')
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(label)
            self.event_tabs.addTab(scroll, caption)
        root.addWidget(self.event_tabs, 1)
        self.event_status = QToolButton()
        self.event_status.setAccessibleName('消息來源狀態')
        self.event_status.setCheckable(True)
        self.event_status.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.event_status.setArrowType(Qt.DownArrow)
        root.addWidget(self.event_status)
        self.source_details = QLabel()
        self.source_details.setTextFormat(Qt.PlainText)
        self.source_details.setWordWrap(True)
        self.source_details.setProperty('muted', True)
        self.source_details.hide()
        self.event_status.toggled.connect(self.source_details.setVisible)
        self.event_status.toggled.connect(lambda expanded: self.event_status.setArrowType(
            Qt.UpArrow if expanded else Qt.DownArrow))
        root.addWidget(self.source_details)
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.poll)
        self.setStyleSheet('''
            QScrollArea { border: 0; background: transparent; }
            QLabel { background: transparent; }
            QToolButton { border: 0; background: transparent; padding: 4px; }
            QToolButton:hover { background: #302b3c; border-radius: 5px; }
            QToolButton:disabled { color: #aaa2b6; }
            QTabWidget::pane { border: 0; }
            QTabBar::tab { background: transparent; color: #aaa2b6; padding: 7px 8px;
                border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: #f1edf7; border-bottom-color: #9a84e5; }
        ''')
        self.refresh_button.setText('重整')

    def bind(self):
        if self.calendar is None:
            self.calendar = self._get_calendar()
            self.calendar.changed.connect(self.update_events)

    def poll(self):
        self.bind()
        self.update_events()
        self.calendar.refresh()

    def manual_refresh(self):
        self.bind()
        self.calendar.refresh(force=True)

    def showEvent(self, event):
        super().showEvent(event)
        self.event_status.setChecked(False)
        self.poll()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def update_events(self):
        self.bind()
        now = datetime.now(UTC)
        upcoming = [event for event in self.calendar.events if now < event.when <= now + timedelta(days=45)]
        stale = self.calendar.error or not self.calendar.is_fresh(now)
        busy = self.calendar._busy
        self.refresh_button.setEnabled(not busy)
        self.refresh_button.setText('更新中' if busy else '重整')
        def title(original):
            shown = self.calendar.title(original)
            return shown + ('〔機翻〕' if original in self.calendar.translations else '')
        def line(event):
            return f'{event.when.astimezone(TAIPEI):%m/%d %H:%M}  {event.currency} · {event.source}\n{title(event.title)}'
        self.event_rows.setText('\n\n'.join(map(line, upcoming[:20])) or
                               '目前載入資料沒有近期排程；請查看來源更新狀態。')
        recent = [(e.when, e.source+' · 已公布 · '+e.currency, e.title)
                  for e in self.calendar.events if now-timedelta(hours=72) <= e.when <= now]
        recent += [(n.when, n.source, n.title) for n in self.calendar.news
                   if now-timedelta(hours=72) <= n.when <= now
                   and (n.source.startswith('香港電台') or relevant_announcement(n.title))]
        recent = sorted(set(recent), reverse=True)[:24]
        self.news_rows.setText('\n\n'.join(f'{when.astimezone(TAIPEI):%m/%d %H:%M} · {source}\n{title(original)}'
            for when, source, original in recent) or '近 72 小時沒有已載入的相關消息；不代表沒有事件，請查看來源狀態。')
        self.news_rows.setToolTip('\n\n'.join(original for _, _, original in recent))
        self.event_rows.setToolTip('\n'.join(item.title for item in upcoming[:20]))
        details = ('\n'.join(self.calendar.status_lines(now)) +
            '\n台北時間；英文可能機翻，消息可能延遲或漏報。')
        self.event_status.setText('ⓘ 來源狀態 · ' + ('部分待更新' if stale else '已更新'))
        self.event_status.setToolTip(details)
        self.source_details.setText(details)

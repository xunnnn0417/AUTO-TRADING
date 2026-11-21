"""Shared, read-only event feed for the main workspace and sidebar."""
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QTabWidget, QSizePolicy,
)
from .calendar_events import UTC, events_for_display
from .event_summary import relevant_announcement, event_summary, trading_session
from .ui_theme import themed_icon
from .news_cards import NewsCards
from .compact_controls import SmallDisclosureButton


class CountdownLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary = ''
        self.setObjectName('newsCountdown')
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setStyleSheet('background:#17151e;border:1px solid #36313f;border-radius:7px;'
                           'padding:6px 10px;color:#c7bed5;font-size:12px;')

    def set_summary(self, text):
        self._summary = text
        self.setToolTip(text)
        self.setText(self.fontMetrics().elidedText(text, Qt.ElideRight, max(0,self.width()-22)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_summary(self._summary)


class EventFeedView(QWidget):
    def __init__(self, get_calendar, parent=None, *, title='消息與事件', close=None, compact=False,
                 show_countdown=True):
        super().__init__(parent)
        self._get_calendar = get_calendar
        self.calendar = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(QLabel(title), 1)
        self.test_alert_button = QToolButton()
        self.test_alert_button.setText('測試重大消息')
        self.test_alert_button.setToolTip('模擬一則消息，測試提醒與紅點；不會操作交易。')
        self.test_alert_button.clicked.connect(self.test_announcement)
        header.addWidget(self.test_alert_button)
        self.test_alert_button.hide()
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(themed_icon('refresh'))
        self.refresh_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.refresh_button.setAccessibleName('更新事件資料')
        self.refresh_button.setToolTip('重新抓取所有消息來源')
        self.refresh_button.clicked.connect(self.manual_refresh)
        header.addWidget(self.refresh_button)
        owner = getattr(get_calendar, '__self__', None)
        if not compact and getattr(owner, 'store', None) is not None:
            self.rest_settings_button = SmallDisclosureButton()
            self.rest_settings_button.setText('休市提醒')
            self.rest_settings_button.setCheckable(True)
            header.addWidget(self.rest_settings_button)
        if close is not None:
            from .window_chrome import WindowChromeButton
            button = WindowChromeButton('close', self)
            button.setFixedSize(24, 24)
            button.clicked.connect(lambda: close(False))
            header.addWidget(button)
        root.addLayout(header)
        if hasattr(self, 'rest_settings_button'):
            from .rest_reminder_settings import RestReminderSettings
            self.rest_editor = RestReminderSettings(
                lambda: owner.store.data.get('ui', {}).get('rest_reminder', {}), self.save_rest_settings,
                context=lambda: owner.profiles.active_name)
            self.rest_editor.hide()
            root.addWidget(self.rest_editor)
            def toggle_rest_settings(opened):
                if opened:
                    self.rest_editor.load()
                self.rest_editor.setVisible(opened)
                self.rest_settings_button.update()
            self.rest_settings_button.toggled.connect(toggle_rest_settings)
        self.countdown_label = CountdownLabel()
        root.addWidget(self.countdown_label)
        self.countdown_label.setVisible(show_countdown)
        self._show_countdown = show_countdown
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.event_tabs = QTabWidget()
        self.event_rows, self.news_rows = (NewsCards(compact=compact) for _ in range(2))
        for caption, label in zip(('即將發生', '已公布／新聞'), (self.event_rows, self.news_rows)):
            label.setViewportMargins(0, 10, 0, 0)
            self.event_tabs.addTab(label, caption)
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
        if compact:
            self.setStyleSheet(self.styleSheet()+'''
                QLabel, QToolButton, QTabBar::tab { font-size:12px; }
                QToolButton { padding:3px; }
                QTabBar::tab { padding:5px 6px; }
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

    def save_rest_settings(self, value):
        owner = self._get_calendar.__self__
        ui = owner.store.data.setdefault('ui', {})
        previous = ui.get('rest_reminder')
        ui['rest_reminder'] = value
        try:
            owner.save_config()
        except OSError:
            if previous is None:
                ui.pop('rest_reminder', None)
            else:
                ui['rest_reminder'] = previous
            raise
        self.bind()
        self.calendar.changed.emit()
        self.calendar._check_reminders()

    def test_announcement(self):
        self.bind()
        self.calendar.preview_announcement()

    def showEvent(self, event):
        super().showEvent(event)
        self.event_status.setChecked(False)
        self.poll()
        self.timer.start()
        if self._show_countdown:
            self.countdown_timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        self.countdown_timer.stop()
        super().hideEvent(event)

    def update_countdown(self):
        self.bind()
        now = datetime.now(UTC)
        owner = getattr(self._get_calendar, '__self__', None)
        store = getattr(owner, 'store', None)
        settings = store.data.get('ui', {}).get('trading_day_separator', {}) if store else {}
        start, end = trading_session(now, settings)
        self.countdown_label.set_summary(event_summary(events_for_display(self.calendar, now), now, settings,
            self.calendar.covers_day(start,end,now), self.calendar.title))

    def update_events(self):
        self.update_countdown()
        now = datetime.now(UTC)
        events = events_for_display(self.calendar, now)
        if hasattr(self, 'rest_editor'):
            self.rest_editor.update_schedule(now)
        upcoming = sorted(event for event in events if now < event.when <= now + timedelta(days=45))
        stale = self.calendar.error or not self.calendar.is_fresh(now)
        busy = self.calendar._busy
        self.refresh_button.setEnabled(not busy)
        self.refresh_button.setText('更新中' if busy else '重整')
        def title(original):
            shown = self.calendar.title(original)
            return shown + ('〔機翻〕' if original in self.calendar.translations else '')
        self.event_rows.set_entries([(e.when, e.currency+' · '+e.source, e.title, title(e.title), True,
                                     '即將休市' if e.source == '休市提醒' else '即將發生', e.details)
                                    for e in upcoming[:20]], '目前載入資料沒有近期排程；請查看來源更新狀態。')
        recent = [(e.when, e.source+' · 已公布 · '+e.currency, e.title, e.details)
                  for e in events if now-timedelta(hours=72) <= e.when <= now]
        recent += [(n.when, n.source, n.title, n.details) for n in self.calendar.news
                   if now-timedelta(hours=72) <= n.when <= now
                   and relevant_announcement(n.title)]
        recent = sorted(set(recent), reverse=True)[:24]
        self.news_rows.set_entries([(when, source, original, title(original), ' · 已公布 · ' in source,
                                    '已休市' if source.startswith('休市提醒 · ') else '已公布', details)
                                   for when, source, original, details in recent],
                                  '近 72 小時沒有已載入的相關消息；不代表沒有事件，請查看來源狀態。')
        self.news_rows.setToolTip('')
        self.event_rows.setToolTip('')
        details = ('\n'.join(self.calendar.status_lines(now)) +
            '\n台北時間；英文可能機翻，消息可能延遲或漏報。')
        self.event_status.setText('ⓘ 來源狀態 · ' + ('部分待更新' if stale else '已更新'))
        self.event_status.setToolTip(details)
        self.source_details.setText(details)

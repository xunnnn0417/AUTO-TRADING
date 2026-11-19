"""Compact settings editor for local rest reminders, used on the main news page."""
from PySide6.QtCore import QLocale, QTime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QTimeEdit, QLineEdit, QPushButton,
)

from .rest_reminders import normalize_settings
from .ui_theme import install_checkmark_only_indicator


class RestReminderSettings(QWidget):
    def __init__(self, get_settings, save_settings, parent=None):
        super().__init__(parent)
        self.get_settings, self.save_settings = get_settings, save_settings
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 8)
        root.setSpacing(6)
        row = QHBoxLayout()
        self.enabled = QCheckBox('啟用休市提醒')
        row.addWidget(self.enabled)
        row.addSpacing(12)
        row.addWidget(QLabel('休市時間（台北）'))
        self.clock = QTimeEdit()
        self.clock.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
        self.clock.setDisplayFormat('h:mm AP')
        self.clock.setMinimumHeight(30)
        self.clock.setStyleSheet('QTimeEdit { background:#1b1b25; color:#eeedf3; '
                                 'border:1px solid #393743; border-radius:7px; padding:4px 8px; }')
        self.clock.setAccessibleName('休市時間（台北）')
        row.addWidget(self.clock)
        row.addStretch()
        root.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('提前分鐘'))
        self.minutes = QLineEdit()
        self.minutes.setMaximumWidth(140)
        self.minutes.setAccessibleName('提前提醒分鐘')
        self.minutes.setPlaceholderText('60, 30')
        row.addWidget(self.minutes)
        row.addWidget(QLabel('逗號分隔，最多 8 個'))
        row.addStretch()
        root.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('休市日'))
        self.days = []
        for name in '一二三四五六日':
            check = QCheckBox(name)
            check.setAccessibleName('星期'+name+'休市')
            self.days.append(check)
            row.addWidget(check)
        for check in [self.enabled, *self.days]:
            install_checkmark_only_indicator(check)
        row.addStretch()
        self.save_button = QPushButton('儲存')
        self.save_button.clicked.connect(self.save)
        row.addWidget(self.save_button)
        root.addLayout(row)
        row = QHBoxLayout()
        note = QLabel('依平台休市當天的日期與時間設定；只提醒，不會平倉。')
        note.setProperty('muted', True)
        row.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addLayout(row)
        root.addWidget(self.status)
        self.load()

    def load(self):
        try:
            value = normalize_settings(self.get_settings())
            message = ''
        except ValueError:
            value = normalize_settings({})
            message = '設定無效，請重新設定並儲存。'
        self.enabled.setChecked(value['enabled'])
        self.clock.setTime(QTime.fromString(value['time'], 'HH:mm'))
        self.minutes.setText(', '.join(map(str, value['minutes'])))
        for day, check in enumerate(self.days):
            check.setChecked(day in value['days'])
        self.status.setText(message)

    def save(self):
        try:
            raw = self.minutes.text().replace('，', ',').split(',')
            if any(not item.strip().isascii() or not item.strip().isdigit() for item in raw):
                raise ValueError('提前分鐘請填數字，以逗號分隔。')
            value = normalize_settings(dict(enabled=self.enabled.isChecked(),
                time=self.clock.time().toString('HH:mm'), minutes=[int(item) for item in raw],
                days=[i for i, check in enumerate(self.days) if check.isChecked()]))
            self.save_settings(value)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else '儲存失敗，請重試。')
            return
        self.minutes.setText(', '.join(map(str, value['minutes'])))
        self.status.setText('已儲存。' if value['enabled'] else '已關閉休市提醒。')

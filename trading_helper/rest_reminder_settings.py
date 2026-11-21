"""Automatic gold rest schedule with preset/custom advance reminders."""
from datetime import datetime
from PySide6.QtCore import QTimer

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QLineEdit,
    QMenu, QToolButton, QWidgetAction,
)

from .calendar_events import UTC, format_event_time
from .compact_controls import SmallDisclosureButton
from .rest_reminders import normalize_settings, rest_occurrences
from .ui_theme import install_checkmark_only_indicator

PRESETS = {30: '30 分鐘', 60: '1 小時', 90: '1.5 小時', 120: '2 小時'}


class RestReminderSettings(QWidget):
    def __init__(self, get_settings, save_settings, parent=None, *, context=lambda: None):
        super().__init__(parent)
        self.get_settings, self.save_settings = get_settings, save_settings
        self._context = context
        self._loading = True
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self.save)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 8)
        root.setSpacing(7)
        row = QHBoxLayout()
        self.enabled = QCheckBox('啟用休市提醒')
        row.addWidget(self.enabled)
        self.schedule_label = QLabel()
        row.addSpacing(12)
        row.addWidget(self.schedule_label)
        row.addStretch()
        root.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('提前提醒'))
        self.advance_button = SmallDisclosureButton()
        self.advance_button.setAccessibleName('選擇提前提醒時間')
        self.advance_button.setPopupMode(QToolButton.InstantPopup)
        self.advance_menu = QMenu(self)
        self.advance_menu.setStyleSheet('QMenu {background:#17151e;color:#eae4f2;'
                                       'border:1px solid #3c3548;border-radius:7px;padding:4px;}')
        choices = QWidget()
        menu_layout = QVBoxLayout(choices)
        menu_layout.setContentsMargins(9, 5, 9, 5)
        menu_layout.setSpacing(8)
        self.presets = {}
        for minutes, caption in PRESETS.items():
            check = QCheckBox(caption)
            check.toggled.connect(self.update_selection)
            self.presets[minutes] = check
            menu_layout.addWidget(check)
        self.custom = QCheckBox('自訂')
        self.custom.toggled.connect(self.update_selection)
        menu_layout.addWidget(self.custom)
        action = QWidgetAction(self.advance_menu)
        action.setDefaultWidget(choices)
        self.advance_menu.addAction(action)
        self.advance_button.setMenu(self.advance_menu)
        row.addWidget(self.advance_button)
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText('分鐘，例如 15, 45')
        self.custom_input.setAccessibleName('自訂提前分鐘')
        self.custom_input.setMaximumWidth(190)
        row.addWidget(self.custom_input)
        self.custom_input.textEdited.connect(lambda: self._save_timer.start())
        self.custom_input.editingFinished.connect(self.save)
        self.enabled.toggled.connect(self.save)
        row.addStretch()
        root.addLayout(row)
        for check in [self.enabled, self.custom, *self.presets.values()]:
            install_checkmark_only_indicator(check)
        note = QLabel('夏／冬令自動調整；假日與平台時段可能不同。只提醒，不會平倉。')
        note.setProperty('muted', True)
        root.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.load()

    def update_schedule(self, now=None):
        now = now or datetime.now(UTC)
        next_close = next(t for t in rest_occurrences(dict(enabled=True), now) if t > now)
        self.schedule_label.setText(f'下次黃金例行休市：{next_close:%m/%d} {format_event_time(next_close)}（台北）')

    def update_selection(self):
        # Signals can fire while the preset checkboxes are still being built.
        if not hasattr(self, 'custom_input'):
            return
        custom = self.custom.isChecked()
        self.custom_input.setVisible(custom)
        for check in self.presets.values():
            check.setEnabled(not custom)
        selected = [caption for minutes, caption in reversed(PRESETS.items()) if self.presets[minutes].isChecked()]
        text = '自訂' if custom else '、'.join(selected) if len(selected) <= 2 else f'已選 {len(selected)} 個時間'
        self.advance_button.setText(text or '請選擇')
        self.advance_button.setToolTip('自訂分鐘' if custom else '、'.join(selected))
        if not self._loading:
            self.save()

    def load(self):
        self._loading = True
        self._save_timer.stop()
        self._loaded_context = self._context()
        try:
            value = normalize_settings(self.get_settings())
            message = ''
        except ValueError:
            value = normalize_settings({})
            message = '設定無效，請重新設定。'
        self._saved_value = value
        self.enabled.setChecked(value['enabled'])
        for minutes, check in self.presets.items():
            check.setChecked(minutes in value['minutes'] and not value['custom'])
        self.custom.setChecked(value['custom'])
        self.custom_input.setText(', '.join(map(str, value['minutes'])) if value['custom'] else '')
        self.update_selection()
        self.update_schedule()
        self.status.setText(message)
        self._loading = False

    def save(self):
        if self._loading:
            return
        self._save_timer.stop()
        if self._context() != self._loaded_context:
            self.load()
            return
        try:
            minutes = [n for n, check in self.presets.items() if check.isChecked()]
            if self.custom.isChecked():
                raw = self.custom_input.text().replace('，', ',').split(',')
                if any(not item.strip().isascii() or not item.strip().isdigit() for item in raw):
                    raise ValueError('提前分鐘請填數字，以逗號分隔。')
                minutes = [int(item) for item in raw]
            if not minutes:
                raise ValueError('請至少選擇一個提醒時間。')
            value = normalize_settings(dict(enabled=self.enabled.isChecked(), minutes=minutes,
                                            custom=self.custom.isChecked()))
        except ValueError as exc:
            if self.enabled.isChecked():
                self.status.setText(str(exc)+' 尚未套用。')
                return
            # Turning reminders off must also work with an unfinished custom input.
            value = dict(self._saved_value, enabled=False)
        try:
            if value != self._saved_value:
                self.save_settings(value)
                self._saved_value = value
        except OSError:
            self.status.setText('儲存失敗，請重試。')
            return
        self.status.setText('已自動儲存。' if value['enabled'] else '休市提醒已關閉。')

    def hideEvent(self, event):
        if self._save_timer.isActive():
            self.save()
        super().hideEvent(event)

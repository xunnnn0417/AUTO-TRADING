"""Read-only scheduled high-impact events; never a breaking-news service."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal, Slot

FEED_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
CALENDAR_URL = 'https://www.forexfactory.com/calendar'
UTC = timezone.utc
MAX_BYTES = 1_000_000


@dataclass(frozen=True, order=True)
class CalendarEvent:
    when: datetime
    currency: str
    title: str


def parse_events(rows: object) -> list[CalendarEvent]:
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('事件日曆格式不符')
    events = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('impact') != 'High':
            continue
        title, currency = str(row.get('title', '')).strip(), str(row.get('country', '')).strip()
        if not title or len(title) > 180 or len(currency) != 3 or not currency.isalpha():
            continue
        try:
            when = datetime.fromisoformat(str(row.get('date', '')).replace('Z', '+00:00'))
        except ValueError:
            continue
        if when.tzinfo is None:
            continue
        events.add(CalendarEvent(when.astimezone(UTC), currency.upper(), title))
    return sorted(events)


def countdown(when: datetime, now: datetime) -> str:
    seconds = (when - now).total_seconds()
    if seconds <= 0:
        return '已發布'
    minutes = ceil(seconds / 60)
    if minutes <= 1:
        return '1 分鐘內'
    days, remaining = divmod(minutes, 1440)
    hours, minutes = divmod(remaining, 60)
    if days:
        return f'{days} 天 {hours} 小時後'
    if hours:
        return f'{hours} 小時 {minutes} 分後'
    return f'{minutes} 分鐘後'


class EconomicCalendar(QObject):
    changed = Signal()
    received = Signal(object)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.events: list[CalendarEvent] = []
        self.fetched_at: datetime | None = None
        self.error = ''
        self._last_attempt: datetime | None = None
        self._busy = False
        self._closed = False
        self.received.connect(self._apply)
        try:
            if path.stat().st_size <= MAX_BYTES:
                payload = json.loads(path.read_text(encoding='utf-8'))
                self.events = parse_events(payload['rows'])
                when = datetime.fromisoformat(payload['fetched_at'])
                self.fetched_at = when if when.tzinfo else None
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def is_fresh(self, now: datetime) -> bool:
        return bool(self.fetched_at and timedelta(0) <= now - self.fetched_at < timedelta(minutes=30))

    def refresh(self) -> None:
        now = datetime.now(UTC)
        if self._closed or self._busy or self.is_fresh(now):
            return
        if self._last_attempt and now - self._last_attempt < timedelta(minutes=15):
            return
        self._busy = True
        self._last_attempt = now
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self) -> None:
        try:
            request = Request(FEED_URL, headers={'User-Agent': 'TradingWorkflowHelper/0.1'})
            with urlopen(request, timeout=10) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('事件資料過大')
            events = parse_events(json.loads(raw.decode('utf-8-sig')))
            result = events, datetime.now(UTC), ''
        except (OSError, ValueError, TypeError) as exc:
            result = None, None, f'事件資料暫時無法更新：{type(exc).__name__}'
        if not self._closed:
            self.received.emit(result)

    @Slot(object)
    def _apply(self, result: tuple) -> None:
        if self._closed:
            return
        events, fetched_at, self.error = result
        self._busy = False
        if events is not None:
            self.events, self.fetched_at = events, fetched_at
            self._save_cache()
        self.changed.emit()

    def _save_cache(self) -> None:
        if self.fetched_at is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                'fetched_at': self.fetched_at.isoformat(),
                'rows': [dict(title=e.title, country=e.currency, date=e.when.isoformat(), impact='High')
                         for e in self.events],
            }, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    def close(self) -> None:
        self._closed = True

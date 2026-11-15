"""Public release schedules and dated central-bank announcements, read-only."""
from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal, Slot

FEED_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
BEA_URL = 'https://apps.bea.gov/API/signup/release_dates.json'
FED_URL = 'https://www.federalreserve.gov/feeds/press_monetary.xml'
ECB_URL = 'https://www.ecb.europa.eu/rss/press.html'
UTC = timezone.utc
MAX_BYTES = 1_000_000
SOURCE_URLS = {'ff': FEED_URL, 'bea': BEA_URL, 'fed': FED_URL, 'ecb': ECB_URL}
SOURCE_NAMES = {'ff': 'Forex Factory', 'bea': 'BEA', 'fed': 'Fed', 'ecb': 'ECB'}
SOURCE_TTLS = {'ff': timedelta(minutes=30), 'bea': timedelta(hours=6),
               'fed': timedelta(minutes=15), 'ecb': timedelta(minutes=15)}


@dataclass(frozen=True, order=True)
class CalendarEvent:
    when: datetime
    currency: str
    title: str
    source: str = 'Forex Factory'


@dataclass(frozen=True, order=True)
class Announcement:
    when: datetime
    source: str
    title: str


def aware_date(raw: str) -> datetime:
    when = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    if when.tzinfo is None:
        raise ValueError('事件時間缺少時區')
    return when.astimezone(UTC)


def parse_bea_schedule(rows: object) -> list[CalendarEvent]:
    if not isinstance(rows, dict):
        raise ValueError('BEA 排程格式不符')
    events = set()
    for key, title in (('Gross Domestic Product', '美國 GDP'),
                       ('Personal Income and Outlays', '美國個人所得與支出（含 PCE）')):
        record = rows.get(key, {})
        dates = record.get('release_dates', []) if isinstance(record, dict) else []
        if not isinstance(dates, list) or len(dates) > 1000:
            raise ValueError('BEA 日期格式不符')
        for date in dates:
            try:
                events.add(CalendarEvent(aware_date(str(date)), 'USD', title, 'BEA'))
            except ValueError:
                continue
    if not events:
        raise ValueError('BEA 沒有可識別的排程')
    return sorted(events)


def parse_announcements(raw: bytes, source: str) -> list[Announcement]:
    if len(raw) > MAX_BYTES or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('公告格式不符')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError('公告 XML 格式不符') from exc
    if root.find('channel') is None:
        raise ValueError('不是 RSS 公告')
    items = set()
    for row in root.findall('./channel/item')[:200]:
        title = (row.findtext('title') or '').strip()
        if not title or len(title) > 300:
            continue
        try:
            when = parsedate_to_datetime(row.findtext('pubDate') or '')
            if when.tzinfo is not None:
                items.add(Announcement(when.astimezone(UTC), source, title))
        except (ValueError, TypeError, OverflowError):
            continue
    return sorted(items, reverse=True)


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
        self.news: list[Announcement] = []
        self._events_by_source = {'ff': [], 'bea': []}
        self._news_by_source = {'fed': [], 'ecb': []}
        self.source_times: dict[str, datetime] = {}
        self.source_errors: dict[str, str] = {}
        self.fetched_at: datetime | None = None
        self.error = ''
        self._last_attempt: dict[str, datetime] = {}
        self._busy = False
        self._closed = False
        self.received.connect(self._apply)
        try:
            if path.stat().st_size <= MAX_BYTES:
                payload = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(payload, dict):
                    raise ValueError('事件快取格式不符')
                if payload.get('version') == 2:
                    for key, rows in payload['sources'].items():
                        if key not in SOURCE_URLS or not isinstance(rows, list) or len(rows) > 1000:
                            continue
                        self.source_times[key] = aware_date(payload['times'][key])
                        if key in self._events_by_source:
                            self._events_by_source[key] = [CalendarEvent(aware_date(row['when']),
                                row['currency'], str(row['title'])[:180], SOURCE_NAMES[key]) for row in rows]
                        else:
                            self._news_by_source[key] = [Announcement(aware_date(row['when']),
                                SOURCE_NAMES[key], str(row['title'])[:300]) for row in rows]
                else:
                    self._events_by_source['ff'] = parse_events(payload['rows'])
                    self.source_times['ff'] = aware_date(payload['fetched_at'])
                self._combine()
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def is_fresh(self, now: datetime) -> bool:
        return all(key in self.source_times and timedelta(0) <= now - self.source_times[key] < SOURCE_TTLS[key]
                   for key in SOURCE_URLS)

    def refresh(self) -> None:
        now = datetime.now(UTC)
        if self._closed or self._busy:
            return
        due = [key for key in SOURCE_URLS
               if (key not in self.source_times or not timedelta(0) <= now-self.source_times[key] < SOURCE_TTLS[key])
               and (key not in self._last_attempt or now-self._last_attempt[key] >= timedelta(minutes=15))]
        if not due:
            return
        self._busy = True
        self._last_attempt.update({key: now for key in due})
        threading.Thread(target=self._fetch, args=(due,), daemon=True).start()

    def _read_source(self, key):
        try:
            request = Request(SOURCE_URLS[key], headers={'User-Agent': 'TradingWorkflowHelper/0.1'})
            with urlopen(request, timeout=8) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('事件資料過大')
            if key == 'ff':
                data = parse_events(json.loads(raw.decode('utf-8-sig')))
            elif key == 'bea':
                data = parse_bea_schedule(json.loads(raw.decode('utf-8-sig')))
            else:
                data = parse_announcements(raw, SOURCE_NAMES[key])
            return key, data, datetime.now(UTC), ''
        except (OSError, ValueError, TypeError) as exc:
            return key, None, None, type(exc).__name__

    def _fetch(self, keys=None) -> None:
        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(self._read_source, keys or SOURCE_URLS))
        if not self._closed:
            self.received.emit(result)

    @Slot(object)
    def _apply(self, result: object) -> None:
        if self._closed:
            return
        # Retain a legacy/manual FF snapshot when that source is offline.
        if not self._events_by_source['ff'] and self.events:
            self._events_by_source['ff'] = [e for e in self.events if e.source == 'Forex Factory']
        self._busy = False
        for key, data, fetched_at, error in result:
            if error:
                self.source_errors[key] = error
            else:
                self.source_errors.pop(key, None)
                self.source_times[key] = fetched_at
                (self._events_by_source if key in self._events_by_source else self._news_by_source)[key] = data
        self.error = '；'.join(f'{SOURCE_NAMES[key]}：{error}' for key, error in self.source_errors.items())
        self._combine()
        self._save_cache()
        self.changed.emit()

    def _combine(self):
        self.events = sorted(set(e for rows in self._events_by_source.values() for e in rows))
        self.news = sorted(set(e for rows in self._news_by_source.values() for e in rows), reverse=True)
        self.fetched_at = max(self.source_times.values(), default=None)

    def status_lines(self, now):
        lines = []
        for key, name in SOURCE_NAMES.items():
            when = self.source_times.get(key)
            state = ('無法更新' if key in self.source_errors else
                     '待更新' if when is None or not timedelta(0) <= now-when < SOURCE_TTLS[key] else '已連線')
            stamp = f' · {when.astimezone():%m/%d %H:%M}' if when else ''
            lines.append(name + '：' + state + stamp)
        return lines

    def _save_cache(self) -> None:
        if self.fetched_at is None:
            return
        try:
            if not self._events_by_source['ff'] and self.events:
                self._events_by_source['ff'] = [e for e in self.events if e.source == 'Forex Factory']
            if not self.source_times:
                self.source_times['ff'] = self.fetched_at
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                'version': 2,
                'times': {key: value.isoformat() for key, value in self.source_times.items()},
                'sources': {key: [dict(when=e.when.isoformat(), title=e.title,
                                    **({'currency': e.currency} if isinstance(e, CalendarEvent) else {})) for e in rows]
                            for key, rows in {**self._events_by_source, **self._news_by_source}.items()
                            if key in self.source_times},
            }, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    def close(self) -> None:
        self._closed = True

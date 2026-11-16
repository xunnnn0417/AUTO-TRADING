"""Public release schedules and dated central-bank announcements, read-only."""
from __future__ import annotations

import json
import re
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
from .headline_language import local_title, translate_title, valid_translation

FEED_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
BEA_URL = 'https://apps.bea.gov/API/signup/release_dates.json'
FED_URL = 'https://www.federalreserve.gov/feeds/press_monetary.xml'
ECB_URL = 'https://www.ecb.europa.eu/rss/press.html'
RTHK_FINANCE_URL = 'https://rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml'
RTHK_WORLD_URL = 'https://rthk.hk/rthk/news/rss/c_expressnews_cinternational.xml'
UTC = timezone.utc
TAIPEI = timezone(timedelta(hours=8))
MAX_BYTES = 1_000_000
SOURCE_URLS = {'ff': FEED_URL, 'bea': BEA_URL, 'fed': FED_URL, 'ecb': ECB_URL,
               'rthk_finance': RTHK_FINANCE_URL, 'rthk_world': RTHK_WORLD_URL}
SOURCE_NAMES = {'ff': 'Forex Factory', 'bea': 'BEA', 'fed': 'Fed', 'ecb': 'ECB',
                'rthk_finance': '香港電台財經', 'rthk_world': '香港電台國際'}
SOURCE_TTLS = {'ff': timedelta(minutes=30), 'bea': timedelta(hours=6),
               'fed': timedelta(minutes=15), 'ecb': timedelta(minutes=15),
               'rthk_finance': timedelta(minutes=5), 'rthk_world': timedelta(minutes=5)}
MARKET_TOPICS = re.compile(
    '黃金|金價|貴金屬|美元|美匯|美債|國債|收益率|孳息|聯儲|聯準|鮑威爾|央行|利率|減息|加息|'
    '通脹|通膨|物價|非農|就業|失業|零售|GDP|PCE|CPI|PPI|PMI|特朗普|川普|關稅|'
    '制裁|戰爭|空襲|停火|導彈|核武|伊朗|以色列|烏克蘭|俄羅斯|霍爾木茲|中東|油價|金融危機', re.I)


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
        if not isinstance(row, dict):
            continue
        if row.get('impact') != 'High' and not (row.get('impact') == 'Medium' and row.get('country') == 'USD'):
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


def parse_market_news(raw: bytes, source: str) -> list[Announcement]:
    return [item for item in parse_announcements(raw, source) if MARKET_TOPICS.search(item.title)]


def calendar_week(rows):
    """Retain the loaded weekly period, including low-impact rows filtered from UI."""
    dates = []
    if not isinstance(rows, list) or len(rows) > 5000:
        return None
    for row in rows:
        try:
            dates.append(aware_date(str(row.get('date', ''))).astimezone(TAIPEI))
        except (AttributeError, ValueError):
            continue
    if not dates:
        return None
    latest = max(dates)
    begin = (latest-timedelta(days=latest.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = begin+timedelta(days=7)
    return (begin, end) if all(begin <= when < end for when in dates) else None


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
        return f'{days} 天 {hours} 小時 {minutes} 分後'
    if hours:
        return f'{hours} 小時 {minutes} 分後'
    return f'{minutes} 分鐘後'


class EconomicCalendar(QObject):
    changed = Signal()
    received = Signal(object)
    translated = Signal(object)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.events: list[CalendarEvent] = []
        self.news: list[Announcement] = []
        self._events_by_source = {'ff': [], 'bea': []}
        self._news_by_source = {key: [] for key in SOURCE_URLS if key not in self._events_by_source}
        self.translations = {}
        self._translation_busy = False
        self._translation_enabled = False
        self._translation_attempts = set()
        self._translation_day = ''
        self._translation_chars = 0
        self.source_times: dict[str, datetime] = {}
        self.source_errors: dict[str, str] = {}
        self._ff_coverage = None
        self.fetched_at: datetime | None = None
        self.error = ''
        self._last_attempt: dict[str, datetime] = {}
        self._busy = False
        self._closed = False
        self.received.connect(self._apply)
        self.translated.connect(self._apply_translations)
        try:
            if path.stat().st_size <= MAX_BYTES:
                payload = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(payload, dict):
                    raise ValueError('事件快取格式不符')
                if payload.get('version') == 2:
                    coverage = payload.get('ff_coverage')
                    if isinstance(coverage, list) and len(coverage) == 2 and all(isinstance(v, str) for v in coverage):
                        begin, end = map(aware_date, coverage)
                        if timedelta(days=6) <= end-begin <= timedelta(days=8):
                            self._ff_coverage = (begin, end)
                    translations = payload.get('translations', {})
                    if not isinstance(translations, dict) or len(translations) > 500:
                        translations = {}
                    self.translations = {title: text for title, text in translations.items()
                                         if len(title) <= 300 and valid_translation(title, text)}
                    self._translation_day = str(payload.get('translation_day', ''))
                    self._translation_chars = max(0, int(payload.get('translation_chars', 0)))
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

    def covers_day(self, start, end, now):
        fetched = self.source_times.get('ff')
        return bool(self._ff_coverage and fetched and 'ff' not in self.source_errors
                    and timedelta(0) <= now-fetched < SOURCE_TTLS['ff']
                    and self._ff_coverage[0] <= start and end <= self._ff_coverage[1])

    def refresh(self, *, force: bool = False) -> None:
        now = datetime.now(UTC)
        if self._closed or self._busy:
            return
        self._translation_enabled = True
        self._translate_missing()
        due = [key for key in SOURCE_URLS
               if force or ((key not in self.source_times or not timedelta(0) <= now-self.source_times[key] < SOURCE_TTLS[key])
               and (key not in self._last_attempt or now-self._last_attempt[key] >= min(SOURCE_TTLS[key], timedelta(minutes=15))))]
        if not due:
            return
        self._busy = True
        self._last_attempt.update({key: now for key in due})
        self.changed.emit()
        threading.Thread(target=self._fetch, args=(due,), daemon=True).start()

    def _read_source(self, key):
        try:
            request = Request(SOURCE_URLS[key], headers={'User-Agent': 'TradingWorkflowHelper/0.1'})
            with urlopen(request, timeout=8) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('事件資料過大')
            if key == 'ff':
                rows = json.loads(raw.decode('utf-8-sig'))
                data = parse_events(rows)
                return key, data, datetime.now(UTC), '', calendar_week(rows)
            elif key == 'bea':
                data = parse_bea_schedule(json.loads(raw.decode('utf-8-sig')))
            elif key.startswith('rthk_'):
                data = parse_market_news(raw, SOURCE_NAMES[key])
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
        for record in result:
            key, data, fetched_at, error = record[:4]
            if error:
                self.source_errors[key] = error
            else:
                if key == 'ff':
                    self._ff_coverage = record[4] if len(record) > 4 else None
                self.source_errors.pop(key, None)
                self.source_times[key] = fetched_at
                (self._events_by_source if key in self._events_by_source else self._news_by_source)[key] = data
        self.error = '；'.join(f'{SOURCE_NAMES[key]}：{error}' for key, error in self.source_errors.items())
        self._combine()
        self._save_cache()
        self.changed.emit()
        if self._translation_enabled:
            self._translate_missing()

    def title(self, original):
        return local_title(original) if local_title(original) != original else self.translations.get(original, original)

    def _translate_missing(self):
        if self._closed or self._translation_busy:
            return
        now = datetime.now(UTC)
        day = now.date().isoformat()
        if day != self._translation_day:
            self._translation_day, self._translation_chars = day, 0
            self._translation_attempts.clear()
        candidates = [e.title for e in self.events if now < e.when <= now+timedelta(days=14)]
        candidates += [e.title for e in self.news if now-timedelta(days=7) <= e.when <= now]
        titles = []
        for title in dict.fromkeys(candidates):
            if (title in self.translations or title in self._translation_attempts or local_title(title) != title
                    or re.search(r'[\u3400-\u9fff]', title) or len(title.encode('utf-8')) > 500):
                continue
            if len(titles) >= 8 or self._translation_chars+len(title) > 4000:
                break
            titles.append(title)
            self._translation_chars += len(title)
            self._translation_attempts.add(title)
        if titles:
            self._translation_busy = True
            self._save_cache()
            threading.Thread(target=self._translate_titles, args=(titles,), daemon=True).start()

    def _translate_titles(self, titles):
        result = {}
        for title in titles:
            if self._closed:
                return
            translated = translate_title(title)
            if translated:
                result[title] = translated
        if not self._closed:
            self.translated.emit(result)

    @Slot(object)
    def _apply_translations(self, result):
        if self._closed:
            return
        self._translation_busy = False
        self.translations.update(result)
        self._save_cache()
        self.changed.emit()
        self._translate_missing()

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
            stamp = f' · {when.astimezone(TAIPEI):%m/%d %H:%M:%S}' if when else ''
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
                'ff_coverage': [value.isoformat() for value in self._ff_coverage] if self._ff_coverage else None,
                'translations': dict(list(self.translations.items())[-500:]),
                'translation_day': self._translation_day,
                'translation_chars': self._translation_chars,
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

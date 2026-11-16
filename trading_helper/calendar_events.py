"""Public release schedules and dated central-bank announcements, read-only."""
from __future__ import annotations

import json
import hashlib
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.client import HTTPException

from PySide6.QtCore import QObject, Signal, Slot, QTimer, Qt
from .headline_language import local_title, translate_title, valid_translation
from .news_probe import append_probe

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
NEWS_POLL_MS = 30_000  # Temporary observation trial; backoff always takes precedence.
SOURCE_TTLS = {'ff': timedelta(minutes=30), 'bea': timedelta(hours=6),
               'fed': timedelta(milliseconds=NEWS_POLL_MS), 'ecb': timedelta(milliseconds=NEWS_POLL_MS),
               'rthk_finance': timedelta(milliseconds=NEWS_POLL_MS), 'rthk_world': timedelta(milliseconds=NEWS_POLL_MS)}
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
    announcements = Signal(object)

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
        self._validators = {}
        self._source_failures = {}
        self._retry_at = {}
        self._seen_news = {}
        self._probe_log_error = False
        self.refresh_timer = QTimer(self)
        self._polling_enabled = False
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setTimerType(Qt.PreciseTimer)
        self.refresh_timer.timeout.connect(lambda: self._poll())

        self.received.connect(self._apply)
        self.translated.connect(self._apply_translations)
        try:
            if path.stat().st_size <= MAX_BYTES:
                payload = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(payload, dict):
                    raise ValueError('事件快取格式不符')
                if payload.get('version') == 2:
                    seen = payload.get('seen_announcements', [])
                    if isinstance(seen, list):
                        self._seen_news = dict.fromkeys(v for v in seen[-500:]
                            if isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v))
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

    def start(self) -> None:
        # App-owned: automatic checks continue when the sidebar is collapsed/hidden.
        if not self._closed:
            self._polling_enabled = True
            self.refresh_timer.start(NEWS_POLL_MS)

    def _poll(self) -> None:
        self.refresh()
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._closed or not self._polling_enabled:
            return
        now = datetime.now(UTC)
        deadlines = [max(
            self._last_attempt.get(key, self.source_times.get(key, now-SOURCE_TTLS[key]))+SOURCE_TTLS[key],
            self._retry_at.get(key, now),
        ) for key in SOURCE_URLS]
        delay = 1000 if self._busy else max(250, min(NEWS_POLL_MS, ceil((min(deadlines)-now).total_seconds()*1000)))
        self.refresh_timer.start(delay)

    def refresh(self, *, force: bool = False) -> None:
        now = datetime.now(UTC)
        if self._closed or self._busy:
            return
        self._translation_enabled = True
        self._translate_missing()
        due = [key for key in SOURCE_URLS
               if now >= self._retry_at.get(key, now)
               and (force or key not in self.source_times
                    or not timedelta(0) <= now-self._last_attempt.get(key, self.source_times[key]) < SOURCE_TTLS[key])]
        if not due:
            return
        self._busy = True
        self._last_attempt.update({key: now for key in due})
        self.changed.emit()
        threading.Thread(target=self._fetch, args=(due,),
                         kwargs={'entry_point': 'manual' if force else 'automatic'}, daemon=True).start()

    def _read_source(self, key, *, entry_point='automatic'):
        started_at, started = datetime.now(UTC), time.perf_counter()
        details = {'http_status': None, 'bytes': 0}
        result = self._download_source(key, details)
        data, error = result[1], result[3]
        failure_kind = details.pop('failure_kind', 'http_error')
        outcome = failure_kind if error else ('unchanged' if data is None else 'downloaded')
        self._probe_log_error = not append_probe(self.path.with_name('news-poll.jsonl'), {
            'event': 'news_poll_result', 'request_id': uuid.uuid4().hex,
            'entry_point': entry_point, 'source': key,
            'started_at': started_at.isoformat(timespec='milliseconds'),
            'finished_at': datetime.now(UTC).isoformat(timespec='milliseconds'),
            'duration_ms': round((time.perf_counter()-started)*1000, 2),
            'outcome': outcome, 'parsed_items': len(data) if data is not None else None,
            'content_changed': (data != (self._events_by_source if key in self._events_by_source
                               else self._news_by_source)[key]) if data is not None else False,
            'error_type': error or None, **details,
        })
        return result

    def _download_source(self, key, details):
        try:
            headers = {'User-Agent': 'TradingWorkflowHelper/0.1'}
            headers.update(self._validators.get(key, {}))
            request = Request(SOURCE_URLS[key], headers=headers)
            with urlopen(request, timeout=8) as response:
                status = getattr(response, 'status', 200)
                details['http_status'] = status if isinstance(status, int) else 200
                raw = response.read(MAX_BYTES + 1)
                details['bytes'] = len(raw)
                validators = {}
                for name, conditional in (('ETag', 'If-None-Match'), ('Last-Modified', 'If-Modified-Since')):
                    value = response.headers.get(name)
                    if isinstance(value, str) and 0 < len(value) <= 512 and '\r' not in value and '\n' not in value:
                        validators[conditional] = value
            if len(raw) > MAX_BYTES:
                raise ValueError('事件資料過大')
            if key == 'ff':
                rows = json.loads(raw.decode('utf-8-sig'))
                data = parse_events(rows)
                return key, data, datetime.now(UTC), '', calendar_week(rows), validators
            elif key == 'bea':
                data = parse_bea_schedule(json.loads(raw.decode('utf-8-sig')))
            elif key.startswith('rthk_'):
                data = parse_market_news(raw, SOURCE_NAMES[key])
            else:
                data = parse_announcements(raw, SOURCE_NAMES[key])
            return key, data, datetime.now(UTC), '', None, validators
        except HTTPError as exc:
            details['http_status'] = exc.code
            exc.close()
            if exc.code == 304 and key in self.source_times:
                return key, None, datetime.now(UTC), ''
            retry = exc.headers.get('Retry-After', '') if exc.headers else ''
            return key, None, None, f'HTTP {exc.code}', None, retry
        except (OSError, HTTPException) as exc:
            details['failure_kind'] = 'network_error'
            return key, None, None, type(exc).__name__
        except (ET.ParseError, ValueError, TypeError) as exc:
            details['failure_kind'] = 'parse_error'
            return key, None, None, type(exc).__name__

    def _fetch(self, keys=None, *, entry_point='automatic') -> None:
        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(lambda key: self._read_source(key, entry_point=entry_point),
                                   keys or SOURCE_URLS))
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
        alerts = []
        for record in result:
            key, data, fetched_at, error = record[:4]
            if error:
                self.source_errors[key] = error
                failures = min(7, self._source_failures.get(key, 0)+1)
                self._source_failures[key] = failures
                delay = timedelta(seconds=min(3600, 60 * 2**(failures-1)))
                retry = record[5] if len(record) > 5 else ''
                now = datetime.now(UTC)
                retry_time = now+delay
                if isinstance(retry, str) and len(retry) <= 100:
                    try:
                        requested = (now+timedelta(seconds=int(retry)) if retry.isdigit()
                                     else parsedate_to_datetime(retry))
                        if requested.tzinfo is not None:
                            retry_time = max(retry_time, requested.astimezone(UTC))
                    except (ValueError, TypeError, OverflowError):
                        pass
                self._retry_at[key] = retry_time
            else:
                if data is not None and key in self._news_by_source:
                    alerts.extend(self._new_announcements(key, data))
                self._source_failures.pop(key, None)
                self._retry_at.pop(key, None)
                if len(record) > 5 and isinstance(record[5], dict):
                    self._validators[key] = record[5]
                if key == 'ff' and data is not None:
                    self._ff_coverage = record[4] if len(record) > 4 else None
                self.source_errors.pop(key, None)
                self.source_times[key] = fetched_at
                if data is not None:  # HTTP 304 confirms the existing data unchanged.
                    (self._events_by_source if key in self._events_by_source else self._news_by_source)[key] = data
        self.error = '；'.join(f'{SOURCE_NAMES[key]}：{error}' for key, error in self.source_errors.items())
        self._combine()
        self._save_cache()
        self.changed.emit()
        if alerts:
            self.announcements.emit(sorted(set(alerts), reverse=True))
        self._schedule_refresh()
        if self._translation_enabled:
            self._translate_missing()

    def _new_announcements(self, key, rows):
        from .event_summary import relevant_announcement
        now = datetime.now(UTC)
        primed = key in self.source_times
        previous = set(self._news_by_source[key])
        alerts = []
        for item in rows:
            identity = hashlib.sha256(f'{item.source}\n{item.when.isoformat()}\n{item.title}'.encode()).hexdigest()
            if (primed and item not in previous and identity not in self._seen_news
                    and now-timedelta(minutes=15) <= item.when <= now
                    and (bool(MARKET_TOPICS.search(item.title)) or relevant_announcement(item.title))):
                alerts.append(item)
            self._seen_news[identity] = None
        self._seen_news = dict(list(self._seen_news.items())[-500:])
        return alerts

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
            retry = self._retry_at.get(key)
            if retry is not None and retry > now:
                stamp += f' · {retry.astimezone(TAIPEI):%H:%M:%S} 後重試'
            lines.append(name + '：' + state + stamp)
        if self._probe_log_error:
            lines.append('診斷記錄無法寫入；消息檢查仍會繼續。')
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
                'seen_announcements': list(self._seen_news),
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
        self._polling_enabled = False
        self.refresh_timer.stop()
        self._closed = True

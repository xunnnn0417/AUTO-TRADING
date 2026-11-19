"""User-owned Taipei rest schedule. Reminders only; no trading operations."""
import re
from datetime import datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))


def normalize_settings(value):
    if not isinstance(value, dict):
        raise ValueError('請重新設定休市提醒。')
    enabled = value.get('enabled', False)
    clock = value.get('time', '06:00')
    minutes = value.get('minutes', [60, 30])
    days = value.get('days', [1, 2, 3, 4, 5])
    if type(enabled) is not bool:
        raise ValueError('請重新設定休市提醒。')
    if not isinstance(clock, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
        raise ValueError('請選擇有效的休市時間。')
    if (not isinstance(minutes, list) or not 1 <= len(minutes) <= 8
            or any(type(n) is not int or not 1 <= n <= 1440 for n in minutes)):
        raise ValueError('提前分鐘請填 1–1440，最多 8 個，以逗號分隔。')
    if (not isinstance(days, list) or not days
            or any(type(n) is not int or not 0 <= n <= 6 for n in days)):
        raise ValueError('請至少選擇一個休市日。')
    return dict(enabled=enabled, time=clock, minutes=sorted(set(minutes), reverse=True), days=sorted(set(days)))


def rest_occurrences(value, now):
    try:
        settings = normalize_settings(value)
    except ValueError:
        return []
    if not settings['enabled']:
        return []
    hour, minute = map(int, settings['time'].split(':'))
    today = now.astimezone(TAIPEI).date()
    return [datetime.combine(day, datetime.min.time(), TAIPEI).replace(hour=hour, minute=minute)
            for day in (today+timedelta(days=n) for n in range(-1, 9))
            if day.weekday() in settings['days']]

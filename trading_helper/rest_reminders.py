"""User-owned Taipei rest schedule. Reminders only; no trading operations."""
from datetime import datetime, timedelta, timezone
from .trading_day import is_us_dst

TAIPEI = timezone(timedelta(hours=8))


def normalize_settings(value):
    if not isinstance(value, dict):
        raise ValueError('請重新設定休市提醒。')
    enabled = value.get('enabled', False)
    minutes = value.get('minutes', [60, 30])
    if type(enabled) is not bool:
        raise ValueError('請重新設定休市提醒。')
    if (not isinstance(minutes, list) or not 1 <= len(minutes) <= 8
            or any(type(n) is not int or not 1 <= n <= 1440 for n in minutes)):
        raise ValueError('提前分鐘請填 1–1440，最多 8 個，以逗號分隔。')
    custom = value.get('custom', any(n not in (30, 60, 90, 120) for n in minutes))
    if type(custom) is not bool:
        raise ValueError('請重新設定提醒時間。')
    # v0.1.75's manual time/days are retired; keep enabled and advance offsets.
    return dict(enabled=enabled, minutes=sorted(set(minutes), reverse=True), custom=custom)


def rest_occurrences(value, now):
    try:
        settings = normalize_settings(value)
    except ValueError:
        return []
    if not settings['enabled']:
        return []
    today = now.astimezone(TAIPEI).date()
    times = []
    # Standard gold maintenance starts at 17:00 New York (CME GC 16:00 CT).
    # Taipei Tue–Sat: 05:00 US summer / 06:00 winter. Broker holidays may differ.
    for day in (today+timedelta(days=n) for n in range(-1, 9)):
        if day.weekday() in (0, 6):
            continue
        local = datetime.combine(day, datetime.min.time(), TAIPEI).replace(hour=12)
        times.append(local.replace(hour=5 if is_us_dst(local) else 6))
    return times

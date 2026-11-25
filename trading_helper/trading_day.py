from __future__ import annotations

from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


_NEW_YORK = None
_NEW_YORK_TRIED = False


def _new_york():
    """Look the zone up ONCE. Without tz data every lookup fails slowly
    (an import attempt each time) - that ran several times per 0.15 s on the
    GUI thread and made the spinner / dragging stutter."""
    global _NEW_YORK, _NEW_YORK_TRIED
    if not _NEW_YORK_TRIED:
        _NEW_YORK_TRIED = True
        if ZoneInfo is not None:
            try:
                _NEW_YORK = ZoneInfo("America/New_York")
            except Exception:
                _NEW_YORK = None
    return _NEW_YORK


def is_us_dst(moment: datetime) -> bool:
    """Return whether New York is in daylight saving time for this moment."""
    zone = _new_york()
    if zone is not None:
        try:
            ny_time = moment.astimezone(zone)
            return bool(ny_time.dst() and ny_time.dst().total_seconds())
        except Exception:
            pass

    year = moment.year
    march = datetime(year, 3, 1)
    first_sunday_march = march + timedelta(days=(6 - march.weekday()) % 7)
    dst_start = first_sunday_march + timedelta(days=7)
    november = datetime(year, 11, 1)
    dst_end = november + timedelta(days=(6 - november.weekday()) % 7)
    naive = moment.replace(tzinfo=None)
    return dst_start <= naive < dst_end


def trading_day_key(
    moment: datetime,
    *,
    summer_reset_hour: int = 6,
    winter_reset_hour: int = 7,
) -> tuple[str, str, int]:
    is_summer = is_us_dst(moment)
    reset_hour = summer_reset_hour if is_summer else winter_reset_hour
    trading_day = moment.date()
    if moment.hour < reset_hour:
        trading_day -= timedelta(days=1)
    season = "夏令" if is_summer else "冬令"
    return trading_day.isoformat(), season, reset_hour


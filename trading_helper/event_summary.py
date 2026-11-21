"""Read-only event wording for the helper's configured trading-day interval."""
from datetime import datetime, timedelta

from .calendar_events import TAIPEI, countdown, format_event_time
from .trading_day import trading_day_key
from .news_relevance import assess_headline


def trading_session(now, settings):
    local = now.astimezone(TAIPEI)
    hours = {}
    for key, default in (('summer_reset_hour', 6), ('winter_reset_hour', 7)):
        try:
            value = int(settings.get(key, default))
        except (TypeError, ValueError):
            value = default
        hours[key] = value if 0 <= value <= 23 else default
    day, _, hour = trading_day_key(local, **hours)
    start = datetime.fromisoformat(day).replace(hour=hour, tzinfo=TAIPEI)
    next_day = start+timedelta(days=1)
    _, _, next_hour = trading_day_key(next_day.replace(hour=12), **hours)
    end = next_day.replace(hour=next_hour)-timedelta(hours=1)
    return start, end


def relevant_announcement(title):
    return assess_headline(title).notify


def event_summary(events, now, settings, day_is_loaded, title=lambda text: text):
    start, end = trading_session(now, settings)
    ordered = sorted(events)
    today = [event for event in ordered if start <= event.when < end and event.source != '休市提醒']
    upcoming = [event for event in ordered if event.when > now]
    remaining_today = [event for event in today if event.when > now]
    if remaining_today or (upcoming and upcoming[0].source == '休市提醒'):
        event = upcoming[0]
        return f'再過 {countdown(event.when, now).removesuffix("後")} · {format_event_time(event.when)} · {title(event.title)}'
    prefix = ('今日排程尚未完整更新' if not day_is_loaded else
              '今日重大事件已公布' if today else '今日無已知重大排程')
    if not upcoming:
        return prefix+' · 下一場：待來源更新'
    event = upcoming[0]
    when = event.when.astimezone(TAIPEI)
    offset = (when.date()-now.astimezone(TAIPEI).date()).days
    day = '今日' if offset == 0 else '明日' if offset == 1 else when.strftime('%m/%d')
    remaining = countdown(event.when, now).removesuffix('後')
    return f'{prefix} · 下一場：{day} {format_event_time(event.when)} · 再過 {remaining}｜{title(event.title)}'

"""Display-only progress of 「填入兩邊」 for the phone's progress card.

Steps are reported from the existing workflow milestones (both forms filled,
each leg's confirmed fill, the verified SL/TP sync). Listeners only record
what already happened; nothing here triggers, retries or changes a trade.
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()
_LISTENERS: list = []

# Journal statuses that mean a step is done.
STEP_OF_STATUS = {
    "filled_internal": "entered_internal", "confirmed_internal": "entered_internal",
    "filled_external": "entered_external", "confirmed_external": "entered_external",
    "synchronized": "synced",
}


def add_listener(callback) -> None:
    with _LOCK:
        if callback not in _LISTENERS:
            _LISTENERS.append(callback)


def remove_listener(callback) -> None:
    with _LOCK:
        if callback in _LISTENERS:
            _LISTENERS.remove(callback)


def notify(step: str) -> None:
    with _LOCK:
        listeners = list(_LISTENERS)
    for callback in listeners:
        try:
            callback(step)
        except Exception:
            pass  # display only: never disturb the trading workflow


def notify_status(status: str) -> None:
    step = STEP_OF_STATUS.get(status)
    if step:
        notify(step)

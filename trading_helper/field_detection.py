"""Experimental, read-only UIA field discovery.

This module never clicks, focuses, types, submits orders, or saves calibration.
Only unambiguous *editable* fields may be reported as suggestions.
"""
from __future__ import annotations

import ctypes
import re
import time
from dataclasses import dataclass
from typing import Iterable

FIELD_NAMES = {
    "lot_input": re.compile(r"(?:\blots?\b|\bvolume\b|quantity|交易量|手數|手数|倉位)", re.I),
    "sl_input": re.compile(r"(?:\bsl\b|\bstop[ -]?loss\b|止損|止损)", re.I),
    "tp_input": re.compile(r"(?:\btp\b|\btake[ -]?profit\b|止盈)", re.I),
}
EDIT_TYPES = frozenset({"Edit", "Spinner"})
LABEL_TYPES = frozenset({"Text", "Static", "HeaderItem"})


@dataclass(frozen=True)
class Element:
    name: str
    kind: str
    rect: tuple[int, int, int, int]
    enabled: bool = True


@dataclass(frozen=True)
class FieldMatch:
    field: str
    rect: tuple[int, int, int, int]
    source: str


def _inside(rect: tuple[int, int, int, int], bounds: tuple[int, int, int, int]) -> bool:
    l, t, r, b = rect
    wl, wt, wr, wb = bounds
    x, y = (l + r) / 2, (t + b) / 2
    return (r - l >= 18 and b - t >= 12 and wl <= x <= wr and wt <= y <= wb)


def _label_distance(label: Element, edit: Element) -> float | None:
    l, t, r, b = label.rect
    el, et, er, eb = edit.rect
    center_y, label_y = (et + eb) / 2, (t + b) / 2
    # Typical form: label immediately to left of the input.
    if r <= el + 8 and abs(center_y - label_y) <= 22 and 0 <= el - r <= 125:
        return float(el - r + abs(center_y - label_y) * 2)
    # Some forms place the label directly above the input.
    center_x, label_x = (el + er) / 2, (l + r) / 2
    if b <= et + 6 and 0 <= et - b <= 34 and abs(center_x - label_x) <= 75:
        return float(et - b + abs(center_x - label_x) + 20)
    return None


def match_fields(
    elements: Iterable[Element],
    window_bounds: tuple[int, int, int, int],
) -> tuple[dict[str, FieldMatch], tuple[str, ...]]:
    """Conservatively match visible editable UIA controls to form labels.

    Equal/competing matches are rejected. Never match headings alone.
    """
    visible = [e for e in elements if e.enabled and _inside(e.rect, window_bounds)]
    edits = [e for e in visible if e.kind in EDIT_TYPES]
    labels = [e for e in visible if e.kind in LABEL_TYPES and e.name.strip()]
    proposals: dict[str, list[tuple[float, Element, str]]] = {k: [] for k in FIELD_NAMES}
    for edit in edits:
        direct = [key for key, rx in FIELD_NAMES.items() if rx.search(edit.name)]
        if len(direct) == 1:
            proposals[direct[0]].append((0, edit, "UIA 控制項名稱"))
            continue
        if direct:
            continue
        nearby: list[tuple[float, str]] = []
        for label in labels:
            named = [key for key, rx in FIELD_NAMES.items() if rx.search(label.name)]
            if len(named) != 1:
                continue
            distance = _label_distance(label, edit)
            if distance is not None:
                nearby.append((distance, named[0]))
        nearby.sort()
        if nearby and (len(nearby) == 1 or nearby[1][0] - nearby[0][0] > 20):
            proposals[nearby[0][1]].append((nearby[0][0] + 10, edit, "鄰近標籤"))
    found: dict[str, FieldMatch] = {}
    warnings = []
    for key, options in proposals.items():
        if len(options) == 1:
            score, element, source = options[0]
            found[key] = FieldMatch(key, element.rect, source)
        elif len(options) > 1:
            warnings.append(f"{key}: 有 {len(options)} 個可能欄位，不自動選擇")
    if len({v.rect for v in found.values()}) != len(found):
        warnings.append("多個欄位重疊，結果已捨棄")
        found.clear()
    for key in FIELD_NAMES:
        if key not in found and not any(x.startswith(key + ":") for x in warnings):
            warnings.append(f"{key}: 尚未可靠找到輸入欄")
    return found, tuple(warnings)


def inspect_uia_window(handle: int, max_elements: int = 1200, timeout: float = 15.0):
    """Inspect an already-open target window. Does not change its state.

    Returns (matched_fields, warnings, scanned_count).
    """
    if not isinstance(handle, int) or handle <= 0:
        raise ValueError("無效的交易視窗代碼")
    if ctypes.windll.user32.IsIconic(handle):
        return {}, ("交易平台目前最小化，請打開下單面板後再測試",), 0
    from pywinauto import Desktop

    window = Desktop(backend="uia").window(handle=handle)
    r = window.rectangle()
    bounds = (r.left, r.top, r.right, r.bottom)
    if not _inside((r.left, r.top, r.right, r.bottom), bounds):
        return {}, ("交易視窗尺寸無效",), 0
    start = time.monotonic()
    pending = [(window.element_info, 0)]
    observed: list[Element] = []
    scanned = 0
    while pending and scanned < max_elements and time.monotonic() - start < timeout:
        info, depth = pending.pop()
        scanned += 1
        try:
            rect = info.rectangle
            observed.append(Element(str(info.name or ""), str(info.control_type or ""),
                                    (rect.left, rect.top, rect.right, rect.bottom),
                                    bool(info.enabled)))
            if depth < 9:
                pending.extend((child, depth + 1) for child in info.children())
        except Exception:
            continue
    found, warnings = match_fields(observed, bounds)
    notices = list(warnings)
    if pending:
        notices.append("掃描達到時間或控制項上限，結果可能不完整")
    return found, tuple(notices), scanned

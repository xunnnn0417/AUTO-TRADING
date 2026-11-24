"""Close every position on both bound accounts with the platforms' own
close-all controls (the 全關 fields calibrated on each platform).

Only runs after the user's two-step confirmation (or the rest-close
countdown). Clicks exactly: cTrader 「全部平倉」 then that confirmation's Yes;
MT5 right-click on the positions list → 「批量操作」 → 「所有持倉平倉」.
Anything unexpected stops that side and is reported; nothing is retried.
"""
from __future__ import annotations

import re
import time

from .bulk_close_calibration import (
    ctrader_close_all_state, find_ctrader_confirmation, find_mt5_menu_item,
    hover_mt5_bulk_actions, last_mt5_match_enabled, open_mt5_context,
)
from .windows import AutomationError

SUPPORTED = ("cTrader", "MT5")
NOTHING_TO_CLOSE = re.compile(r'nothing to close|沒有可平倉|没有可平仓', re.I)


def missing_calibration(platform: str, points: dict) -> str:
    """Why this platform cannot be closed automatically yet ('' when ready)."""
    if platform not in SUPPORTED:
        return f"{platform} 尚未支援自動平倉。"
    if platform == "cTrader" and not points.get("bulk_close_button"):
        return "cTrader 還沒校準「全部平倉按鈕」。"
    if platform == "MT5" and not points.get("position_order_row"):
        return "MT5 還沒校準持倉列表（③ 持倉列表 SL 欄）。"
    return ""


def ctrader_position_text(main) -> str:
    """cTrader's close-all caption, e.g. 'Close 2' or 'Nothing to close'."""
    _rect, caption = ctrader_close_all_state(main)
    return caption


def _centre(rect):
    left, top, right, bottom = rect
    return (left + right) // 2, (top + bottom) // 2


def close_ctrader(controller, main, points, list_windows, pid_for_window, abort, click_at) -> str:
    window = controller.focus(main)
    abort.guard()
    rect, caption = ctrader_close_all_state(window)
    if caption and NOTHING_TO_CLOSE.search(caption):
        return "cTrader：沒有持倉，未操作。"
    if rect is not None:
        click_at(*_centre(rect))
    else:
        controller.click(window, points["bulk_close_button"])
    found = None
    deadline = time.monotonic() + 4
    while found is None and time.monotonic() < deadline:
        abort.guard()
        time.sleep(0.2)
        found = find_ctrader_confirmation(window, list_windows(), pid_for_window)
    if found is None:
        return ("cTrader：已按「全部平倉」，但沒有出現確認視窗"
                "（可能已直接平倉，或按鈕沒有反應），請到 cTrader 核對持倉。")
    abort.guard()
    click_at(*_centre(found["yes"]))
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        time.sleep(0.4)
        _rect, caption = ctrader_close_all_state(window)
        if caption and NOTHING_TO_CLOSE.search(caption):
            return "cTrader：已平倉，畫面顯示沒有持倉。"
    return "cTrader：已按確認平倉，但還讀得到持倉，請到 cTrader 核對。"


def close_mt5(controller, main, points, pid_for_window, abort, click_at, press_key) -> str:
    window = controller.focus(main)
    abort.guard()
    open_mt5_context(controller, window, points["position_order_row"])
    abort.guard()
    try:
        hover_mt5_bulk_actions(main, pid_for_window, click_at)
        rect = find_mt5_menu_item(main, "bulk_close_all", pid_for_window)
        if rect is None:
            raise AutomationError("MT5：子選單裡找不到「所有持倉平倉」，沒有平倉。")
        if not last_mt5_match_enabled():
            raise _NoPositions()
        abort.guard()
    except _NoPositions:
        for _ in range(3):
            press_key("esc")
        return "MT5：沒有持倉（選單項目是灰色），未操作。"
    except Exception:
        for _ in range(3):
            press_key("esc")
        raise
    click_at(*_centre(rect))
    return "MT5：已按「所有持倉平倉」，請到 MT5 核對持倉。"


class _NoPositions(Exception):
    pass

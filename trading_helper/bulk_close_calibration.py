"""Bulk-close calibration. Inspection never executes a close.

The close-all button/menu is part of the platform's own UI and is identical
whichever side (場內/場外) the platform plays, so each platform has ONE set of
fields. Which side's positions to close is a separate trading preference.
"""
import re
import time
from .calibration_scan import Candidate, Control, ScanReport
from .windows import AutomationError, WindowInfo

KEY_PREFIX = 'bulk_close_'
# Positions panel close-all button (cTrader 5.10, confirmed via UIA).
CTRADER_CLOSE_ALL_ID = 'TradeWatch_CloseAll_CloseAllButton'


def targets(platform):
    fields = (('button', '全部平倉按鈕'), ('confirm', '平倉確認視窗的 Yes')) if platform == 'cTrader' else (
        ('actions', '右鍵選單：批量操作'), ('all', '子選單：所有持倉平倉'))
    return tuple((KEY_PREFIX + key, caption) for key, caption in fields)


def is_bulk_key(key):
    return str(key or '').startswith(KEY_PREFIX)


def mt5_menu_handles(pid, pid_for_window):
    """Visible #32768 popup menus of one process, top-most first.

    Enumerated with Win32: the UIA desktop listing omits submenus that MT5
    opens later (e.g. the 「批量操作」 submenu), so it cannot be relied on.
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32')
    handles = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd, _):
        name = ctypes.create_unicode_buffer(16)
        user32.GetClassNameW(hwnd, name, 16)
        if name.value == '#32768' and user32.IsWindowVisible(hwnd):
            handles.append(int(hwnd))
        return True
    user32.EnumWindows(callback_type(collect), 0)
    return [h for h in handles if pid_for_window(h) == pid]


def platform_windows(main, windows, pid_for_window):
    """MT5's untitled popup menus are intentionally absent from normal app lists."""
    from pywinauto import Desktop
    pid = pid_for_window(main.handle)
    if not pid:
        raise AutomationError('無法確認平台程序。')
    found = {w.handle: w for w in windows if pid_for_window(w.handle) == pid}
    for handle in mt5_menu_handles(pid, pid_for_window):
        menu = Desktop(backend='uia').window(handle=handle)
        rect = menu.rectangle()
        found[handle] = WindowInfo(handle, str(menu.window_text() or ''), rect.left, rect.top, rect.right, rect.bottom)
    return list(found.values())


def match_controls(platform, requested, controls):
    report = ScanReport(platform, tuple(requested), scanned=len(controls))
    for key, _ in requested:
        field = key.rsplit('_', 1)[-1]
        matches = []
        for control in controls:
            # MT5 greys bulk items out while there are no positions; their
            # position is still fixed, and calibration only records position.
            if not control.visible or (not control.enabled and platform != 'MT5'):
                continue
            context = ' '.join(control.ancestors)
            name = control.name.replace('&', '').split('\t', 1)[0].strip()
            if platform == 'cTrader':
                if field == 'button':
                    # The caption changes ("Nothing to close", "Close 2"...);
                    # cTrader's automation id for this button does not.
                    by_id = (CTRADER_CLOSE_ALL_ID in (control.automation_id or '')
                             and control.kind in ('Button', 'Text'))
                    matched = by_id or (control.kind == 'Button' and re.fullmatch(
                        r'(?:Close\s*\d+|Close all(?: positions)?|Nothing to close|全部平倉|全部平仓)', name, re.I))
                else:
                    matched = (control.kind == 'Button' and re.fullmatch(r'Yes|是|確定|确定', name, re.I)
                               and re.search(r'Close selected positions|Close all positions|關閉.*持倉|关闭.*持仓', context, re.I))
            else:
                expression = r'批量操作|Bulk (?:Operations|Actions)' if field == 'actions' else r'所有持倉平倉|所有持仓平仓|Close all positions'
                matched = control.kind == 'MenuItem' and re.fullmatch(expression, name, re.I)
            if matched:
                matches.append(control)
        if len(matches) > 1 and any(c.kind == 'Button' for c in matches):
            # A button and its own caption text are one target; keep the button.
            matches = [c for c in matches if c.kind == 'Button']
        unique = {control.rect: control for control in matches}
        if len(unique) == 1:
            control = next(iter(unique.values()))
            report.candidates[key] = Candidate(key, control.rect, '同一平台程序內的唯一批量平倉控制項；範圍仍須核對')
        else:
            report.reasons[key] = '請開啟對應的平倉確認視窗' if platform == 'cTrader' and field == 'confirm' else '請展開對應選單；不猜測位置或方向'
    return report


def inspect_bulk_targets(main, platform, requested, windows, pid_for_window):
    """Inspect only visible windows of the already bound terminal process."""
    from pywinauto import Desktop
    pid = pid_for_window(main.handle)
    if not pid:
        raise AutomationError('無法確認批量校準的平台程序。')
    observed = []
    deadline = time.monotonic()+5
    for window in platform_windows(main, windows, pid_for_window):
        if pid_for_window(window.handle) != pid:
            continue
        root = Desktop(backend='uia').window(handle=window.handle)
        for node in root.descendants():
            if time.monotonic() >= deadline or len(observed) >= 2000:
                report = match_controls(platform, requested, observed)
                report.warnings = ('掃描未完整完成，請重掃；不儲存部分猜測。',)
                return report
            info = node.element_info
            if info.control_type not in ('Button', 'MenuItem'):
                continue
            rect = info.rectangle
            observed.append(Control(info.control_type, str(info.name or ''), str(info.automation_id or ''),
                                    (rect.left, rect.top, rect.right, rect.bottom),
                                    bool(info.enabled), bool(info.visible), (window.title,)))
    return match_controls(platform, requested, observed)


CTRADER_ACCOUNT_TYPE_ID = 'CTraderAccountTypeTextBlock_AId'
CTRADER_CLOSE_ALL_BUTTON_ID = 'TradeWatch_CloseAll_CloseAllButton__Button_ButtonContent_AId'


def _find_by_automation_id(handle, automation_id):
    """One element under a window by AutomationId, via UIA's native FindFirst.

    About 6x faster on cTrader than pywinauto's child_window() search, which
    walks the whole WPF tree in Python (that walk froze the preview ~1.5 s).
    """
    from pywinauto.uia_defines import IUIA
    uia = IUIA()
    root = uia.iuia.ElementFromHandle(handle)
    condition = uia.iuia.CreatePropertyCondition(uia.UIA_dll.UIA_AutomationIdPropertyId, automation_id)
    return root.FindFirst(uia.tree_scope['descendants'], condition)


def ctrader_close_all_rect(main):
    """Direct UIA lookup of the close-all button by its fixed id (fast;
    no full-window scan). Returns its rectangle or None."""
    try:
        element = _find_by_automation_id(main.handle, CTRADER_CLOSE_ALL_BUTTON_ID)
        if not element:
            return None
        rect = element.CurrentBoundingRectangle
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def ctrader_close_all_state(main):
    """(rect, caption) of cTrader's close-all button, or (None, '')."""
    try:
        element = _find_by_automation_id(main.handle, CTRADER_CLOSE_ALL_BUTTON_ID)
        if not element:
            return None, ''
        rect = element.CurrentBoundingRectangle
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None, ''
        return (rect.left, rect.top, rect.right, rect.bottom), str(element.CurrentName or '').strip()
    except Exception:
        return None, ''


def ctrader_account_type(main) -> str:
    """Account type shown in the bound cTrader window ("Demo" for demo)."""
    try:
        element = _find_by_automation_id(main.handle, CTRADER_ACCOUNT_TYPE_ID)
        return str(element.CurrentName or '').strip() if element else ''
    except Exception:
        return ''


def find_ctrader_confirmation(main, windows, pid_for_window):
    """Locate the close-positions confirmation's Yes and No/Cancel buttons.

    Returns {'yes': rect, 'cancel': rect or None} or None. Read-only.
    """
    from pywinauto import Desktop
    pid = pid_for_window(main.handle)
    for window in platform_windows(main, windows, pid_for_window):
        if pid_for_window(window.handle) != pid:
            continue
        # Yes only counts inside the confirmation window (matched by its
        # title below), so skip the large main window: scanning its
        # buttons is what made the cTrader preview pause.
        if not re.search(r'Close selected positions|Close all positions|關閉.*持倉|关闭.*持仓',
                         window.title or '', re.I):
            continue
        controls = []
        try:
            nodes = Desktop(backend='uia').window(handle=window.handle).descendants(control_type='Button')
        except Exception:
            continue
        for node in nodes[:400]:
            info = node.element_info
            rect = info.rectangle
            controls.append(Control('Button', str(info.name or ''), str(info.automation_id or ''),
                                    (rect.left, rect.top, rect.right, rect.bottom),
                                    bool(info.enabled), bool(info.visible), (window.title,)))
        yes = match_controls('cTrader', ((KEY_PREFIX + 'confirm', ''),), controls).candidates.get(KEY_PREFIX + 'confirm')
        if yes is None:
            continue
        cancels = [c for c in controls if c.visible and c.enabled
                   and re.fullmatch(r'No|Cancel|否|取消', c.name.strip(), re.I)]
        return {'yes': yes.rect, 'cancel': cancels[0].rect if len(cancels) == 1 else None}
    return None


def open_mt5_context(windows, main, row_point):
    """Open the saved SL-cell context menu only, never a menu action."""
    if not isinstance(row_point, dict) or not row_point:
        raise AutomationError('請先校準持倉列表 SL 欄，再校準批量平倉。')
    windows.right_click(main, row_point)


_LAST_MENU_ITEMS: list[str] = []
_LAST_MATCH_ENABLED = [True]


def last_mt5_match_enabled() -> bool:
    """Whether the item last returned by find_mt5_menu_item was enabled
    (MT5 greys the bulk items out while there are no positions)."""
    return bool(_LAST_MATCH_ENABLED[0])


def last_mt5_menu_items():
    """Names of the MT5 popup-menu items seen by the last search (diagnostics:
    tells us the real wording when an expected item is not recognised)."""
    return tuple(_LAST_MENU_ITEMS)


def find_mt5_menu_item(main, key, pid_for_window, timeout=1.5):
    """Rectangle of one bulk-close item in the bound MT5's open popup menu.

    Reads only that process's untitled #32768 menus (fast; the main window is
    not scanned). Returns None unless exactly one matching item is visible.
    """
    from pywinauto import Desktop
    pid = pid_for_window(main.handle)
    if not pid:
        return None
    deadline = time.monotonic() + timeout
    while True:
        seen = []
        # Desktop windows come top-most first. A menu left open by an earlier
        # search can still exist underneath; judging uniqueness per menu and
        # taking the top-most match stops it from blocking the search.
        for handle in mt5_menu_handles(pid, pid_for_window):
            controls = []
            try:
                nodes = Desktop(backend='uia').window(handle=handle).descendants(control_type='MenuItem')
            except Exception:
                continue
            for node in nodes:
                info = node.element_info
                rect = info.rectangle
                controls.append(Control(info.control_type, str(info.name or ''), '',
                                        (rect.left, rect.top, rect.right, rect.bottom),
                                        bool(info.enabled), bool(info.visible), ('',)))
            seen.extend(c.name for c in controls if c.visible and c.name)
            candidate = match_controls('MT5', ((key, ''),), controls).candidates.get(key)
            if candidate is not None:
                _LAST_MENU_ITEMS[:] = seen
                _LAST_MATCH_ENABLED[0] = next((c.enabled for c in controls if c.rect == candidate.rect), True)
                return candidate.rect
        _LAST_MENU_ITEMS[:] = seen
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.15)


def hover_mt5_bulk_actions(main, pid_for_window, click_at):
    """Open the 「批量操作」 submenu so 「所有持倉平倉」 becomes visible.

    Uses the menu item's own UIA Expand (opens the submenu, executes nothing);
    falls back to clicking the header. Only the uniquely matched, exactly
    named 「批量操作」 parent item is touched; 「所有持倉平倉」 is never clicked.
    """
    rect = find_mt5_menu_item(main, KEY_PREFIX + 'actions', pid_for_window)
    if rect is None:
        raise AutomationError('右鍵選單裡找不到唯一的「批量操作」，沒有點擊。')
    left, top, right, bottom = rect
    # The first Expand right after the menu appears is sometimes ignored by
    # MT5 (the submenu only opened on the second try). Confirm the submenu
    # really shows 「所有持倉平倉」; retry Expand once, then click the header.
    for attempt in range(3):
        if attempt < 2:
            opened = _expand_mt5_item(main, rect, pid_for_window)
        else:
            opened = False
        if not opened:
            click_at((left + right) // 2, (top + bottom) // 2)
        if find_mt5_menu_item(main, KEY_PREFIX + 'all', pid_for_window, timeout=0.6) is not None:
            return rect
    return rect


def _expand_mt5_item(main, rect, pid_for_window):
    from pywinauto import Desktop
    pid = pid_for_window(main.handle)
    for handle in mt5_menu_handles(pid, pid_for_window):
        try:
            nodes = Desktop(backend='uia').window(handle=handle).descendants(control_type='MenuItem')
        except Exception:
            continue
        for node in nodes:
            r = node.element_info.rectangle
            if (r.left, r.top, r.right, r.bottom) == tuple(rect):
                try:
                    node.expand()
                    return True
                except Exception:
                    return False
    return False

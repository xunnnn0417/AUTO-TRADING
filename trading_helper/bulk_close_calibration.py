"""Role-specific bulk-close calibration. Inspection never executes a close."""
import re
import time
from .calibration_scan import Candidate, Control, ScanReport
from .windows import AutomationError, WindowInfo

ROLES = {'internal': '場內', 'external': '場外'}


def targets(platform):
    fields = (('button', '全部平倉按鈕'), ('confirm', '平倉確認視窗的 Yes')) if platform == 'cTrader' else (
        ('actions', '右鍵選單：批量操作'), ('all', '子選單：所有持倉平倉'))
    return tuple((f'{role}_bulk_close_{key}', f'{label}：{caption}')
                 for role, label in ROLES.items() for key, caption in fields)


def role_for(key):
    return next((role for role in ROLES if key.startswith(role+'_bulk_close_')), None)


def platform_windows(main, windows, pid_for_window):
    """MT5's untitled popup menus are intentionally absent from normal app lists."""
    from pywinauto import Desktop
    pid = pid_for_window(main.handle)
    if not pid:
        raise AutomationError('無法確認平台程序。')
    found = {w.handle: w for w in windows if pid_for_window(w.handle) == pid}
    for menu in Desktop(backend='uia').windows(class_name='#32768', visible_only=True):
        handle = int(menu.handle)
        if pid_for_window(handle) != pid:
            continue
        rect = menu.rectangle()
        found[handle] = WindowInfo(handle, str(menu.window_text() or ''), rect.left, rect.top, rect.right, rect.bottom)
    return list(found.values())


def match_controls(platform, requested, controls):
    report = ScanReport(platform, tuple(requested), scanned=len(controls))
    for key, _ in requested:
        field = key.rsplit('_', 1)[-1]
        matches = []
        for control in controls:
            if not control.visible or not control.enabled:
                continue
            context = ' '.join(control.ancestors)
            name = control.name.replace('&', '').split('\t', 1)[0].strip()
            if platform == 'cTrader':
                if field == 'button':
                    matched = control.kind == 'Button' and re.fullmatch(r'(?:Close\s*\d+|Close all(?: positions)?|全部平倉|全部平仓)', name, re.I)
                else:
                    matched = (control.kind == 'Button' and re.fullmatch(r'Yes|是|確定|确定', name, re.I)
                               and re.search(r'Close selected positions|Close all positions|關閉.*持倉|关闭.*持仓', context, re.I))
            else:
                expression = r'批量操作|Bulk (?:Operations|Actions)' if field == 'actions' else r'所有持倉平倉|所有持仓平仓|Close all positions'
                matched = control.kind == 'MenuItem' and re.fullmatch(expression, name, re.I)
            if matched:
                matches.append(control)
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


def open_mt5_context(windows, main, row_point):
    """Open the saved SL-cell context menu only, never a menu action."""
    if not isinstance(row_point, dict) or not row_point:
        raise AutomationError('請先校準持倉列表 SL 欄，再校準批量平倉。')
    windows.right_click(main, row_point)

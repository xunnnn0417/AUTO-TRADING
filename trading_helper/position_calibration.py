"""Read-only, stage-specific calibration for OPEN DEMO positions.

One native position (not simply a row count) is required. These are provisional
rectangles for human review, never an instruction to click or submit.
"""
from __future__ import annotations
import re
from .calibration_scan import ScanReport, Candidate, inspect_all_targets

POSITION_GRID_KEYS = ("positions_entry_price","position_order_lot","position_order_row")
POSITION_EDIT_KEYS = ("position_sl_input","position_tp_input","position_modify_confirm")

def scan_position_grid(handle: int, platform: str, targets):
    from pywinauto import Desktop
    out=ScanReport(platform,tuple(targets))
    try:
        if platform=="cTrader":
            root=Desktop(backend="uia").window(handle=handle)
            grids=[
                x for x in root.descendants(control_type="DataGrid")
                if str(x.element_info.automation_id)=="PositionListDataGrid_AId"
                and x.is_visible()
            ]
            if len(grids)!=1:
                raise ValueError("無法確認唯一的 cTrader Positions 表格")
            grid=grids[0]
            rows=grid.descendants(control_type="DataItem")
            if len(rows)!=1:
                raise ValueError(f"需要恰好一筆持倉，目前辨識 {len(rows)} 筆")
            row=rows[0].rectangle()
            headers={}
            for h in grid.descendants(control_type="HeaderItem"):
                name=str(h.window_text() or "").strip().casefold()
                # cTrader positions grid includes two unnamed action
                # columns; neither is a field and both can share "".
                if not name:
                    continue
                if name in headers:
                    raise ValueError(f"重複欄位 {name}")
                headers[name]=h.rectangle()
            columns={
                "positions_entry_price": ("entry price",),
                "position_order_lot": ("quantity",),
                "position_order_row": ("tp",),
            }
            for key,label in targets:
                names=columns.get(key,())
                matches=[headers[n] for n in names if n in headers]
                if len(matches)!=1:
                    out.reasons[key]=f"找不到唯一的欄位標題 {names}"
                    continue
                h=matches[0]
                rect=(max(row.left,h.left),row.top,min(row.right,h.right),row.bottom)
                if rect[2]-rect[0]<10 or rect[3]-rect[1]<10:
                    out.reasons[key]="持倉列與欄位沒有有效交集"
                    continue
                out.candidates[key]=Candidate(key,rect,
                    "唯一 cTrader 持倉與欄位標題交集；僅候選，未自動雙擊／填入")
            out.scanned=len(headers)+len(rows)+len(grids)
        else:
            root=Desktop(backend="win32").window(handle=handle)
            views=[
                v for v in root.descendants()
                if v.class_name()=="SysListView32" and v.control_id()==10328
                and v.is_visible()
            ]
            if len(views)!=1:raise ValueError("MT5 Trade 清單不唯一或未顯示")
            view=views[0]
            if len(view.columns())<9:raise ValueError("MT5 持倉欄位不足")
            rows=[]
            unreadable=0
            for i in range(view.item_count()):
                cells=[str(view.get_item(i,j).text() or "").strip() for j in range(9)]
                if not any(cells):
                    unreadable+=1
                    continue
                if not cells[1].isdigit() or len(cells[1])<5:
                    raise ValueError("MT5 Trade 清單存在無法辨識的訂單列")
                rows.append(i)
            ownerdraw_preview=False
            if not rows and unreadable==2 and view.item_count()==2:
                # Owner-drawn MT5 can return two blank subitems despite a
                # visible single trade and the account balance summary.
                # The first rectangle is only an UNVERIFIED preview target;
                # NEVER treat this as an actual counted/confirmed position.
                rows=[0]
                ownerdraw_preview=True
            if len(rows)!=1:
                raise ValueError(
                    "MT5 清單無法確定唯一持倉，"
                    "候選不可靠；請用人工校準"
                )
            origin=view.rectangle()
            # Visual MT5 columns: symbol 0, order 1, time 2, type 3,
            # volume 4, entry 5, SL 6, TP 7.
            columns={"positions_entry_price":5,"position_order_lot":4,
                     "position_order_row":6}
            for key,label in targets:
                if key not in columns:continue
                raw=view.get_item(rows[0],columns[key]).rectangle()
                rect=(origin.left+raw.left,origin.top+raw.top,
                      origin.left+raw.right,origin.top+raw.bottom)
                if rect[2]-rect[0]<10 or rect[3]-rect[1]<10:
                    out.reasons[key]="持倉欄位沒有可預覽的矩形"
                    continue
                out.candidates[key]=Candidate(
                    key,rect,
                    ("低信度：MT5 原生清單文字無法讀回，僅按 1+摘要列結構"
                     "推測第一個可見列；可能不是持倉，必須人工黃框核對；"
                     "不可用於自動成交／空倉判斷。"
                     if ownerdraw_preview else
                     "唯一 MT5 Trade 持倉的原生欄位交集；"
                     "SL 雙擊候選，仍須黃框人工確認")
                )
            out.scanned=view.item_count()
    except Exception as exc:
        out.warnings=(f"持倉列表無法安全辨識：{exc}",)
        for key,_ in targets:
            out.reasons[key]="未確認唯一持倉；可使用手動擷取"
        out.candidates.clear()
    return out


def select_broker_main_window(
    selected, windows, platform, pid_lookup, *, binding_pattern=None
):
    """Choose one visible native broker main HWND, never its modify dialog.

    Regex-based window.find can return a modal whose title includes cTrader.
    Re-evaluate all visible bound windows instead of trusting that first hit.
    If there is not exactly one appropriate main HWND, fail closed.
    """
    windows=list(windows)
    bound_pids=set()
    try:
        selected_pid=pid_lookup(selected.handle)
        if selected_pid:
            bound_pids.add(selected_pid)
    except Exception:
        pass
    if binding_pattern:
        try:
            matched=re.compile(str(binding_pattern),re.I)
        except re.error:
            return None
        for win in windows:
            if matched.search(str(win.title or "")):
                try:
                    pid=pid_lookup(win.handle)
                    if pid:
                        bound_pids.add(pid)
                except Exception:
                    pass
    if not bound_pids:
        return None
    main=[]
    for win in windows:
        try:
            if pid_lookup(win.handle) not in bound_pids:
                continue
        except Exception:
            continue
        title=str(win.title or "")
        if platform=="cTrader":
            # Terminal title is sometimes suffixed by workspace/account text.
            # Never allow "Modify order or position - cTrader" or tooltips.
            valid=bool(re.match(
                r"^cTrader\s+\d+(?:\.\d+)+(?:\s*[-|].*)?$",title,re.I
            ))
        else:
            valid=bool(re.search(
                r"\[[\w.+-]+,\s*(?:M\d+|H\d+|D1|W1|MN1)\]",
                title,re.I))
        if valid:
            main.append(win)
    return main[0] if len(main)==1 else None


def select_modify_dialog(main,windows,platform,pid_lookup):
    """Identify one already OPEN native modify dialog of the SAME process."""
    candidates=[]
    main_pid=pid_lookup(main.handle)
    for win in windows:
        if win.handle==main.handle or pid_lookup(win.handle)!=main_pid:
            continue
        title=str(win.title or "")
        if platform=="cTrader":
            valid=bool(re.search(r"modif.*(?:position|order)|(?:position|order).*modif|修改.*(?:持倉|訂單)",title,re.I))
        else:
            # Avoid the normal New Order launcher: 'Order: XAUUSD' alone is
            # NOT enough to certify a position-modification dialog.
            valid=bool(re.search(
                r"modif|修改|變更持倉|position.*edit|"
                r"^(?:持倉|持仓|position)\s*:\s*#?\d{5,}\s+(?:buy|sell)\b",
                title,re.I))
        if valid:candidates.append(win)
    return candidates[0] if len(candidates)==1 else None


def scan_open_modify_dialog(handle: int,platform: str, targets):
    from pywinauto import Desktop
    requested=tuple(targets)
    # UIA generic rules require a "modify" named ancestor even when the
    # already-selected popup is itself the modify dialog. Scan ONLY exact
    # known controls there to avoid false 0/3 and 12-second timeouts.
    report=ScanReport(platform,requested)
    if platform in {"MT5","BYBIT MT5","原版MT5"}:
        # Native MT5 position modify dialog: live verified Win32 IDs:
        # 10334=Stop Loss PRICE, 10336=Take Profit PRICE,
        # 10351=Modify button (may be disabled before value changes).
        # Do NOT confuse IDs 10423/10345, which are PIPS fields.
        root=Desktop(backend="win32").window(handle=handle)
        native_controls=root.descendants()
        report.scanned=len(native_controls)
        mapping={
            "position_sl_input":("Edit",10334),
            "position_tp_input":("Edit",10336),
            "position_modify_confirm":("Button",10351),
        }
        for key,_ in requested:
            if key not in mapping:continue
            kind,control_id=mapping[key]
            matches=[]
            for control in native_controls:
                try:
                    if control.class_name()!=kind or control.control_id()!=control_id:
                        continue
                    rect=control.rectangle()
                    if rect.width()<=30 or rect.height()<=12:continue
                    matches.append(rect)
                except Exception:
                    continue
            if len(matches)==1:
                rect=matches[0]
                report.candidates[key]=Candidate(
                    key,(rect.left,rect.top,rect.right,rect.bottom),
                    "MT5 修改持倉視窗唯一原生控制項 ID "
                    +str(control_id)+("；按鈕可能暫時不可按，僅預覽校準"
                    if key=="position_modify_confirm" else "；價格欄，非點數欄；需人工確認")
                )
                report.reasons.pop(key,None)
        return report
    # In a cTrader Modify position modal, the first numeric box below
    # each Stop loss/Take profit heading contains PIPS, not the PRICE.
    # Only propose the second vertically aligned Edit as a LOW-confidence
    # price candidate after seeing both unique heading labels. The user
    # must preview and approve its rectangle; never save automatically.
    if platform=="cTrader":
        root=Desktop(backend="uia").window(handle=handle)
        all_controls=root.descendants()
        report.scanned=len(all_controls)
        labels={}
        for key,aid in (
            ("position_sl_input","CheckBoxStopLoss_AId"),
            ("position_tp_input","CheckBoxTakeProfit_AId"),
        ):
            headings=[]
            for node in all_controls:
                try:
                    if (node.is_visible()
                        and str(node.element_info.control_type)=="CheckBox"
                        and str(node.element_info.automation_id)==aid
                        and (key!="position_tp_input"
                             or str(node.window_text() or "").strip().casefold()
                                =="take profit 1")):
                        headings.append(node.rectangle())
                except Exception:
                    pass
            if len(headings)==1:labels[key]=headings[0]
        if len(labels)==2:
            for key,heading in labels.items():
                center_x=(heading.left+heading.right)//2
                other=next(v for k,v in labels.items() if k!=key)
                other_center=(other.left+other.right)//2
                candidates=[]
                for ctrl in all_controls:
                    try:
                        if (not ctrl.is_visible()
                            or str(ctrl.element_info.control_type)!="Edit"
                            or str(ctrl.element_info.automation_id)!="SpinnerContent_AId"):
                            continue
                        rect=ctrl.rectangle()
                        x=(rect.left+rect.right)//2
                        if (abs(x-center_x)<abs(x-other_center)
                            and abs(x-center_x)<=165
                            and heading.bottom<=rect.top<=heading.bottom+75
                            and rect.right-rect.left>=35):
                            candidates.append(rect)
                    except Exception:
                        pass
                candidates.sort(key=lambda x:(x.top,x.left))
                # Below header: 1st Edit -> Pips; 2nd Edit -> Price;
                # ambiguous pairs are left for manual coordinate capture.
                if (2<=len(candidates)<=3
                    and 19<=candidates[1].top-candidates[0].top<=40):
                    rect=candidates[1]
                    report.candidates[key]=Candidate(
                        key,(rect.left,rect.top,rect.right,rect.bottom),
                        "低信度：cTrader 修改視窗同欄第二個 Edit（價格，第一個是 Pips）；"
                        "請黃框確認後才儲存"
                    )
                    report.reasons.pop(key,None)
    # In cTrader the final action may be named Protect (not Modify).
    if platform=="cTrader" and "position_modify_confirm" in dict(requested):
        root=Desktop(backend="uia").window(handle=handle)
        buttons=[]
        for ctrl in root.descendants(control_type="Button"):
            try:
                if (ctrl.is_visible()
                    and str(ctrl.element_info.automation_id)=="ProtectButton_AId"
                    and str(ctrl.window_text() or "").strip().casefold()=="protect"):
                    buttons.append(ctrl)
            except Exception:
                continue
        if len(buttons)==1:
            rect=buttons[0].rectangle()
            report.candidates["position_modify_confirm"]=Candidate(
                "position_modify_confirm",
                (rect.left,rect.top,rect.right,rect.bottom),
                "已開啟 cTrader 修改視窗的唯一 Protect/Modify 按鈕；"
                "僅黃框預覽，需人工確認"
            )
            report.reasons.pop("position_modify_confirm",None)
    return report

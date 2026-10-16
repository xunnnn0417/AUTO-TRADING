"""P2 v5: read-only post-entry cTrader position inventory.

No orders, focus, clicks, keyboard, selection, login-value reads, or writes.
The user must open an existing / demo position and modification dialog.
"""
from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Iterable

from .calibration_scan import (
    Candidate, Control, _inside, _modify_confirmation_suggestion,
)

POST_ENTRY_TARGETS = (
    ("positions_entry_price", "持倉 Entry Price 欄位"),
    ("position_order_lot", "唯一持倉的手數欄位"),
    ("position_order_row", "唯一持倉的 TP 欄位（修改入口，僅預覽）"),
    ("position_sl_input", "持倉修改視窗 SL 價格輸入框"),
    ("position_tp_input", "持倉修改視窗 TP 價格輸入框"),
    ("position_modify_confirm", "修改 SL／TP 後的確認／套用按鈕（僅預覽）"),
)

@dataclass
class PostEntryReport:
    state: str = "unknown"
    count: int | None = None
    scanned: int = 0
    candidates: dict[str, Candidate] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def as_text(self) -> str:
        state_labels = {
            "empty": "尚未看到持倉，請在模擬帳戶或既有持倉出現後再試",
            "single": "偵測到唯一持倉；只提供候選，不修改持倉",
            "multiple": "偵測到多筆持倉：停止自動挑選，請自行指定目標",
            "unknown": "無法可靠確定持倉數量：停止，請確認 Positions 分頁可見",
        }
        lines = [
            "進場後校準｜cTrader（唯讀，不下單、不儲存）",
            state_labels.get(self.state, "狀態未知"),
            f"持倉數量：{self.count if self.count is not None else '未能確認'}",
            f"已檢查 UIA 節點：{self.scanned}",
            "",
        ]
        for key,label in POST_ENTRY_TARGETS:
            c=self.candidates.get(key)
            if c:
                l,t,r,b=c.rect
                lines.append(
                    f"{label} [{key}]：候選中心 {((l+r)//2,(t+b)//2)}；"
                    f"{c.evidence}"
                )
            else:
                lines.append(f"{label} [{key}]：尚未確認，需相關畫面及人工驗證")
        lines.extend(("", *self.notes,
                      "如要校準修改 SL／TP，請先自行開啟既有模擬持倉的修改視窗，再按重新掃描。",
                      "本功能不點擊 TP、不雙擊持倉、不輸入價格、不更改設定。"))
        return "\n".join(lines)

def _grid_rows(controls: list[Control]) -> tuple[str, list[Control]]:
    grids=[c for c in controls
           if c.kind=="DataGrid" and c.automation_id=="PositionListDataGrid_AId"]
    if len(grids)!=1:
        return "unknown", []
    grid=grids[0]
    rows=[
        c for c in controls if c.kind=="DataItem"
        and c.ancestors and c.ancestors[0].split(" ",1)[-1]=="PositionListDataGrid_AId"
        and c.rect[1]>=grid.rect[1] and c.rect[3]<=grid.rect[3]
        and c.rect[3]-c.rect[1]>=14
    ]
    # If UIA exposes a virtualized / nested hierarchy, prefer unknown to guessing.
    return ("empty" if len(rows)==0 else
            "single" if len(rows)==1 else "multiple"), rows

def _column_candidate(
    controls: list[Control], row: Control, key: str, names: str,
) -> Candidate | None:
    headers=[
        c for c in controls
        if c.kind=="HeaderItem"
        and re.search(names, c.name, re.I)
        and "PositionListDataGrid_AId" in " ".join(c.ancestors[:3])
    ]
    if len(headers)!=1:
        return None
    header=headers[0]
    x1=max(row.rect[0],header.rect[0])
    x2=min(row.rect[2],header.rect[2])
    if x2-x1<18:
        return None
    # A provisional cell intersection, not a proven editable field.
    return Candidate(key,(x1,row.rect[1],x2,row.rect[3]),
        "唯一持倉與對應欄標題的交會區（低信度、未驗證；不代表已讀取數值）")

def _modify_price_candidates(controls: list[Control]) -> dict[str, Candidate]:
    """Require explicit modification-pane parent AND named price Edit IDs.

    Never infer a price field solely from its screen coordinate or a generic
    SpinnerContent ID shared with the normal order pane.
    """
    matched: dict[str, Candidate] = {}
    for key, predicate in (
        ("position_sl_input", r"stop.?loss"),
        ("position_tp_input", r"take.?profit"),
    ):
        controls_found=[]
        for c in controls:
            if c.kind!="Edit":
                continue
            identity=c.name+" "+c.automation_id
            parents=" ".join(c.ancestors[:4])
            if not re.search(r"position.*modif|modif.*position|positionedit", parents, re.I):
                continue
            if not re.search(predicate, identity, re.I):
                continue
            controls_found.append(c)
        if len(controls_found)==1:
            c=controls_found[0]
            matched[key]=Candidate(key,c.rect,
                f"已開啟持倉修改介面的 Edit {c.automation_id}；仍須預覽確認")
    return matched


def classify_post_entry(
    controls: Iterable[Control],
    bounds: tuple[int,int,int,int],
) -> PostEntryReport:
    """Fail closed for unknown or 2+ positions; never select an arbitrary first."""
    visible=[c for c in controls if c.enabled and c.visible and _inside(c.rect,bounds)]
    state,rows=_grid_rows(visible)
    report=PostEntryReport(state=state)
    report.count=None if state=="unknown" else len(rows)
    if state=="unknown":
        report.notes=("找不到唯一的 PositionListDataGrid_AId；請顯示 Positions 分頁",)
        return report
    if state=="empty":
        report.notes=("沒有持倉時不執行第二階段校準。",)
        return report
    if state=="multiple":
        report.notes=("安全限制：多筆持倉不預設第一筆，全部候選保持未確認。",)
        return report
    row=rows[0]
    # This is a row candidate only. Entry/lot/TP are derived only from
    # unique corresponding header labels in the same position grid.
    for key,pattern in (
        ("positions_entry_price",r"\bentry(?:\s*price)?\b|進場價|開倉價"),
        ("position_order_lot",r"\b(?:volume|quantity|lots?)\b|手數|交易量"),
        ("position_order_row",r"\b(?:take\s*profit|tp)\b|止盈"),
    ):
        item=_column_candidate(visible,row,key,pattern)
        if item:report.candidates[key]=item
    report.candidates.update(_modify_price_candidates(visible))
    confirm = _modify_confirmation_suggestion(visible)
    if confirm is not None:
        report.candidates["position_modify_confirm"] = confirm
    report.notes=("只讀取唯一持倉的 UIA 表格幾何位置；不會輸出價格或手數數值。",
                  "修改視窗若尚未開啟、欄位識別不唯一，就不提供 SL／TP 修改欄位候選。")
    return report

def inspect_post_entry(
    handle: int, max_elements: int=1400, timeout: float=9,
) -> PostEntryReport:
    """Read UIA tree of an already-open cTrader window; no interaction."""
    if not isinstance(handle,int) or handle<=0:
        raise ValueError("找不到綁定的 cTrader 視窗")
    user32=ctypes.windll.user32
    if user32.IsIconic(handle):
        return PostEntryReport(notes=("目標視窗已最小化，請恢復後再掃描",))
    from pywinauto import Desktop
    root=Desktop(backend="uia").window(handle=handle).element_info
    r=root.rectangle
    bounds=(int(r.left),int(r.top),int(r.right),int(r.bottom))
    pending=[(root,0,())]
    observed=[]
    count=0
    start=time.monotonic()
    while pending and count<max_elements and time.monotonic()-start<timeout:
        node,depth,ancestors=pending.pop()
        count+=1
        try:
            rc=node.rectangle
            title=str(node.name or "")
            aid=str(node.automation_id or "")
            observed.append(Control(
                kind=str(node.control_type or ""),name=title,
                automation_id=aid,
                rect=(int(rc.left),int(rc.top),int(rc.right),int(rc.bottom)),
                enabled=bool(node.enabled),visible=bool(node.visible),
                ancestors=ancestors,
            ))
            if depth<10:
                token=(str(node.control_type or "")+" "+aid)[:110]
                pending.extend((child,depth+1,(token,)+ancestors[:3])
                               for child in node.children())
        except Exception:
            continue
    report=classify_post_entry(observed,bounds)
    report.scanned=count
    if pending:
        report.state="unknown"
        report.count=None
        report.candidates.clear()
        report.notes=("掃描超過控制項或時間上限，結果不完整；已拒絕判定持倉",)
        return report

    # A modify-position dialog can be a separate top-level window in the same
    # cTrader process. Look only at dialogs the user has ALREADY opened, and
    # only if exactly one position exists; no clicks, focus or keyboard input.
    if report.state == "single":
        try:
            from .calibration_scan import inspect_all_targets
            process_id=int(root.process_id)
            requested=tuple((k, label) for k,label in POST_ENTRY_TARGETS if k in {
                "position_sl_input", "position_tp_input", "position_modify_confirm"
            })
            ambiguous=set()
            for sibling in Desktop(backend="uia").windows(process=process_id):
                if int(sibling.handle) == handle:
                    continue
                if not ctypes.windll.user32.IsWindowVisible(sibling.handle):
                    continue
                if ctypes.windll.user32.IsIconic(sibling.handle):
                    continue
                title=str(sibling.window_text() or "")
                if not re.search(r"modif|edit.{0,20}position|position.{0,20}edit|修改", title, re.I):
                    continue
                extra=inspect_all_targets(
                    int(sibling.handle), "cTrader", requested,
                    max_elements=500, timeout=4.0, scan_related=False,
                )
                report.scanned += extra.scanned
                for key, candidate in extra.candidates.items():
                    if key in ambiguous:
                        continue
                    if key in report.candidates:
                        report.candidates.pop(key,None)
                        ambiguous.add(key)
                        continue
                    report.candidates[key] = candidate
            if ambiguous:
                report.notes += (
                    "多個持倉修改視窗出現相同功能按鈕；為避免選錯已拒絕辨識。",
                )
        except Exception:
            report.notes += (
                "獨立修改視窗掃描不可用，仍可在開啟該視窗後手動校準。",
            )
    return report

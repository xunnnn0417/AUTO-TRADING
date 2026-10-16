"""P2 read-only calibration inventory for existing cTrader and MT5 targets.

Inspect a currently OPEN target window. Never focus, click, type, submit an
order, move the cursor, save settings, or assume a suggested target is proven.
Users must explicitly accept/recalibrate in a later, independently reviewed step.
"""
from __future__ import annotations

import ctypes
import re
import time
from dataclasses import dataclass, field
from typing import Iterable

EDIT = frozenset({"Edit", "Spinner", "ComboBox"})
BUTTON = frozenset({"Button"})
CHECKBOX = frozenset({"CheckBox"})
TAB = frozenset({"TabItem"})
TEXT = frozenset({"Text", "Static"})

# Roles are restricted by UIA type. Matching visible names alone is insufficient:
# a text label named "Buy" cannot be used as a buy-button location.
RULES: dict[str, tuple[frozenset[str], str]] = {
    "lot_input": (EDIT, r"(?:quantityorvolumetextbox|\blots?\b|\bvolume\b|\bquantity\b|手數|手数|交易量)"),
    "sl_input": (EDIT, r"(?:stop.?loss|\bsl\b|止損|止损)"),
    "tp_input": (EDIT, r"(?:take.?profit|\btp\b|止盈)"),
    "position_sl_input": (EDIT, r"(?:stop.?loss|\bsl\b|止損|止损)"),
    "position_tp_input": (EDIT, r"(?:take.?profit|\btp\b|止盈)"),
    "sl_checkbox": (CHECKBOX, r"(?:stop.?loss|\bsl\b|止損|止损)"),
    "tp_checkbox": (CHECKBOX, r"(?:take.?profit|\btp\b|止盈)"),
    "buy_button": (BUTTON, r"(?:\bbuy\b|買入|买入)"),
    "sell_button": (BUTTON, r"(?:\bsell\b|賣出|卖出)"),
    "new_order_button": (BUTTON, r"(?:new.?order|新訂單|新订单)"),
    "trade_tab": (TAB, r"(?:\btrade\b|交易)"),
    "ask_price": (TEXT, r"(?:\bask\b|askprice)"),
    # Submission controls require *additional* trade-dialog context below.
    # A direction RadioButton or New Order launcher is never a submit target.
    "order_submit_button": (BUTTON, r"(?:place|submit|send|execute|confirm).{0,35}(?:market)?order|(?:market)?order.{0,30}(?:place|submit|send|execute|confirm)"),
    "order_submit_buy": (BUTTON, r"(?:buy\s+by\s+market|buyby(?:market|button)|marketbuybutton)"),
    "order_submit_sell": (BUTTON, r"(?:sell\s+by\s+market|sellby(?:market|button)|marketsellbutton)"),
    "position_modify_confirm": (BUTTON, r"(?:confirm|apply|save|submit|update|modify)"),
}
_COMPILED = {key: re.compile(expr, re.I) for key, (_, expr) in RULES.items()}
_POSITION = re.compile(r"(?:position|modify|orderedit|持倉|持仓|修改)", re.I)

# These UI positions are not guaranteed to expose a safe, unambiguous UIA role.
# They remain part of the complete inventory but require manual verification.
MANUAL_REASONS = {
    "account_number": "帳號顯示可能包含敏感資料；暫不推測位置",
    "positions_entry_price": "目前屬 OCR／持倉讀值流程，不能只用文字標籤認定",
    "position_order_lot": "持倉列表中可能有多筆訂單，不能隨意選第一個文字",
    "position_order_row": "雙擊目標必須確認是哪一筆持倉，不能自行推測",
}

@dataclass(frozen=True)
class Control:
    kind: str
    name: str
    automation_id: str
    rect: tuple[int, int, int, int]
    enabled: bool = True
    visible: bool = True
    ancestors: tuple[str, ...] = ()

@dataclass(frozen=True)
class Candidate:
    key: str
    rect: tuple[int, int, int, int]
    evidence: str

@dataclass
class ScanReport:
    platform: str
    targets: tuple[tuple[str, str], ...]
    scanned: int = 0
    candidates: dict[str, Candidate] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def as_text(self) -> str:
        lines = [
            f"{self.platform}｜完整校準項目唯讀掃描（未儲存、未填值、未下單）",
            f"已檢查 UIA 控制項：{self.scanned} 個",
            f"找到單一候選：{len(self.candidates)}/{len(self.targets)}；均尚未人工確認",
            "掃描只涵蓋目前已開啟的視窗；其他畫面仍需要切換後重掃。",
            "",
        ]
        for i, (key, label) in enumerate(self.targets, 1):
            match = self.candidates.get(key)
            if match:
                x1, y1, x2, y2 = match.rect
                lines.append(
                    f"{i:02}. {label} [{key}]\n"
                    f"    單一候選（未確認）：中心點 {(x1+x2)//2}, {(y1+y2)//2}；{match.evidence}"
                )
            else:
                lines.append(f"{i:02}. {label} [{key}]\n    未確認：{self.reasons.get(key, '目前視窗沒有唯一可辨識的 UIA 目標')}")
        if self.warnings:
            lines.extend(["", "掃描警示：", *[f"- {x}" for x in self.warnings]])
        lines.extend(["", "單純掃描與預覽不會覆寫既有校準。只有你預覽後勾選並明確確認，才會儲存已選的位置；未找到的項目仍需手動校準。"])
        return "\n".join(lines)

def _inside(rect: tuple[int, int, int, int], bounds: tuple[int, int, int, int]) -> bool:
    l, t, r, b = rect
    wl, wt, wr, wb = bounds
    return (
        r - l >= 8 and b - t >= 8 and r - l <= 3000 and b - t <= 3000
        and wl <= l < r <= wr and wt <= t < b <= wb
    )

def _is_position(control: Control) -> bool:
    # Only the immediate control's UIA identity and nearer ancestors are useful.
    # A generic top-level "Positions" window name is not a reliable distinction.
    identity = control.name + " " + control.automation_id + " " + " ".join(control.ancestors[:3])
    return bool(_POSITION.search(identity))

def _ctrader_order_suggestions(controls: list[Control]) -> dict[str, Candidate]:
    """Read-only candidates from an open cTrader market-order panel."""
    def unique(kind: str, aid: str, predicate=lambda c: True) -> Control | None:
        hits = [c for c in controls if c.kind == kind
                and c.automation_id == aid and predicate(c)]
        return hits[0] if len(hits) == 1 else None

    volume = unique("Edit", "QuantityOrVolumeTextBox_AId",
                    lambda c: not _is_position(c))
    if volume is None:
        return {}
    vl, vt, vr, vb = volume.rect
    result = {"lot_input": Candidate("lot_input", volume.rect,
              "cTrader 下單區 QuantityOrVolumeTextBox_AId；僅候選，未儲存")}

    for key, aid in (("buy_button", "AspNewMarketOrderBuyButton_AId"),
                     ("sell_button", "AspNewMarketOrderSellButton_AId")):
        button = unique("RadioButton", aid, lambda c:
            any("AspNewMarketOrderControl_AId" in p for p in c.ancestors)
            and 0 <= vt - c.rect[3] <= 220
            and abs((c.rect[0] + c.rect[2]) // 2 - (vl + vr) // 2) <= 400)
        if button:
            result[key] = Candidate(key, button.rect,
                         f"cTrader 下單區 RadioButton {aid}；僅候選")

    stop = unique("CheckBox", "CheckBoxStopLoss_AId", lambda c:
        0 <= c.rect[1] - vb <= 100 and abs(c.rect[0] - vl) <= 150)
    if stop is None:
        return result
    take = unique("CheckBox", "CheckBoxTakeProfit_AId", lambda c:
        abs(c.rect[1] - stop.rect[1]) <= 12
        and 30 <= c.rect[0] - stop.rect[0] <= 600)
    if take is None:
        return result

    for key, checkbox in (("sl_checkbox", stop), ("tp_checkbox", take)):
        result[key] = Candidate(key, checkbox.rect,
                      f"cTrader 與手數欄同一訂單區的 {checkbox.automation_id}；僅候選")

    for key, checkbox in (("sl_input", stop), ("tp_input", take)):
        l, t, r, b = checkbox.rect
        nearby = sorted((
            (c.rect[1] - b, c) for c in controls
            if c.kind == "Edit" and c.automation_id == "SpinnerContent_AId"
            and min(r, c.rect[2]) - max(l, c.rect[0]) >= 20
            and 4 <= c.rect[1] - b <= 60
        ), key=lambda item: item[0])
        if nearby and (len(nearby) == 1 or nearby[1][0] - nearby[0][0] >= 12):
            result[key] = Candidate(key, nearby[0][1].rect,
                          "低信度：同列 SL/TP 勾選框下方最近的 SpinnerContent_AId；"
                          "須確認是點數而非預估價格")
    return result


def _ctrader_submit_suggestion(controls: list[Control]) -> Candidate | None:
    """Locate cTrader's *actual* Place order button; never click.

    Verified from a read-only UIA traversal on the user's cTrader:
    Button Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId
      -> Custom AspPlaceOrderButton_AId
      -> Custom PropertySectionView_AId.
    The controls for BUY/SELL direction live elsewhere in
    AspNewMarketOrderControl_AId and are RadioButtons, not this submit action.
    """
    volume = [
        c for c in controls
        if c.kind == "Edit" and c.automation_id == "QuantityOrVolumeTextBox_AId"
        and "AspNewMarketOrderControl_AId" in " ".join(c.ancestors[:4])
    ]
    if len(volume) != 1:
        return None
    vl, vt, vr, vb = volume[0].rect
    valid = [
        c for c in controls
        if c.kind == "Button"
        and c.automation_id ==
            "Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId"
        and "AspPlaceOrderButton_AId" in " ".join(c.ancestors[:2])
        and "PropertySectionView_AId" in " ".join(c.ancestors[:4])
        and 50 <= c.rect[1] - vb <= 650
        and abs((c.rect[0] + c.rect[2] - vl - vr) // 2) <= 500
    ]
    if len(valid) != 1:
        return None
    return Candidate(
        "order_submit_button", valid[0].rect,
        "cTrader 唯一送單 Button："
        "Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId；"
        "父層 AspPlaceOrderButton_AId；僅候選，未點擊、未儲存",
    )


def _mt5_main_new_order_suggestion(
    controls: list[Control],
    bounds: tuple[int, int, int, int],
) -> tuple[Candidate | None, str]:
    """Identify the top-toolbar MT5 New Order launcher; never click it.

    On the user's current MT5 the visible toolbar New Order is a UIA
    MenuItem rather than Button. Only an exact named, unique toolbar item
    in the top portion of the bound main window is eligible.
    """
    left, top, right, bottom = bounds
    toolbar_limit = top + min(180, max(90, int((bottom-top)*.23)))
    found = [
        c for c in controls
        if c.kind in {"MenuItem", "Button"}
        and c.enabled and c.visible and _inside(c.rect, bounds)
        and re.search(r"new[\s-]*order|新訂單|新订单", c.name + " " + c.automation_id, re.I)
        and c.rect[1] < toolbar_limit and not _is_position(c)
    ]
    if len(found) == 1:
        candidate = found[0]
        return Candidate(
            "new_order_button", candidate.rect,
            f"MT5 主視窗頂部 {candidate.kind} 新訂單；唯讀候選，未點擊",
        ), ""
    if len(found) > 1:
        return None, f"同時找到 {len(found)} 個新訂單候選，無法唯一確認"
    return None, "找不到主視窗頂部的唯一新訂單 Button／MenuItem；請保持 MT5 主視窗可見"


def _mt5_order_dialog_labeled_edits(
    controls: list[Control],
) -> dict[str, Candidate]:
    """Conservative low-confidence suggestions for unnamed MT5 Edit fields.

    Some localized MT5 order dialogs expose an adjacent Text label but no
    AutomationId on the actual input. Use a field only when precisely one
    labeled text and one same-row, right-hand Edit match. The user MUST
    preview and manually tick the suggestion before it may be saved.
    """
    names = {
        "lot_input": r"^(?:volume|lots?|quantity|交易量|手數|手数)\s*[:：]?$",
        "sl_input": r"^(?:stop\s*loss|s\s*/\s*l|止損|止损)\s*[:：]?$",
        "tp_input": r"^(?:take\s*profit|t\s*/\s*p|止盈)\s*[:：]?$",
    }
    suggested = {}
    for key, pattern in names.items():
        labels = [c for c in controls if c.kind in {"Text", "Static"}
                  and re.search(pattern, c.name.strip(), re.I)
                  and not _is_position(c)]
        if len(labels) != 1:
            continue
        label = labels[0]
        l,t,r,b = label.rect
        center_y = (t+b)/2
        adjacent = [
            c for c in controls
            if c.kind in EDIT and not _is_position(c)
            and 0 <= c.rect[0]-r <= 380
            and abs((c.rect[1]+c.rect[3])/2-center_y) <= 12
            and c.rect[2]-c.rect[0] >= 24
        ]
        if len(adjacent) == 1:
            suggested[key] = Candidate(
                key, adjacent[0].rect,
                "低信度：MT5 下單視窗同列欄位標籤 + 唯一輸入框；"
                "需看黃色框人工確認，才可儲存",
            )
    return suggested


def _mt5_market_submit_suggestions(controls: list[Control]) -> dict[str, Candidate]:
    """Only a paired, uniquely named BUY and SELL in the order dialog.

    The MT5 dialog can expose just "Buy"/"Sell" or include a live quote
    after the control name. Do not confuse these with text labels or a
    main-window market shortcut. These remain UNSAVED preview candidates.
    """
    expressions = {
        "order_submit_buy": r"^(?:buy(?:\s+by\s+market)?|market\s+buy|市價買入|買入市價|市价买入|买入市价)(?:\s+[0-9][0-9,.]*)?$",
        "order_submit_sell": r"^(?:sell(?:\s+by\s+market)?|market\s+sell|市價賣出|賣出市價|市价卖出|卖出市价)(?:\s+[0-9][0-9,.]*)?$",
    }
    found = {
        key: [
            c for c in controls
            if c.kind == "Button" and not _is_position(c)
            and re.fullmatch(pattern, c.name.strip(), re.I)
        ] for key, pattern in expressions.items()
    }
    if any(len(hits) != 1 for hits in found.values()):
        return {}
    buy=found["order_submit_buy"][0]
    sell=found["order_submit_sell"][0]
    if abs((buy.rect[1]+buy.rect[3])-(sell.rect[1]+sell.rect[3])) > 44:
        return {}
    if buy.rect == sell.rect:
        return {}
    return {
        key: Candidate(key,hits[0].rect,
                       "低信度：MT5 下單視窗唯一成對的市價買賣 Button；"
                       "僅黃框候選，絕不自動點擊")
        for key,hits in found.items()
    }


def _mt5_current_price_suggestion(controls: list[Control]) -> Candidate | None:
    """A single visible price-with-number label, not an empty 'Price:' label.

    Reuses legacy ask_price key so the existing MT5 field-fill code uses a
    SINGLE reference quote for BUY and SELL without changing order logic.
    If multiple price numbers are exposed, require manual selection.
    """
    labels = []
    for c in controls:
        if c.kind not in {"Text", "Static"} or _is_position(c):
            continue
        text = (c.name + " " + c.automation_id).strip()
        if (re.search(r"\b(?:ask|current\s*price|market\s*price)\b|目前價格|當前價格|当前价格",text,re.I)
                and re.search(r"(?<!\d)\d{2,7}[.,]\d{1,6}(?!\d)",c.name)):
            labels.append(c)
    if len(labels) != 1:
        return None
    return Candidate(
        "ask_price",labels[0].rect,
        "低信度：MT5 唯一顯示數字的目前報價標籤；"
        "買／賣共用同一參考價格，僅供黃框預覽",
    )

def _modify_confirmation_suggestion(controls: list[Control]) -> Candidate | None:
    """Never mistake the 'open modify window' row button for final confirmation."""
    hits = []
    for c in controls:
        if c.kind != "Button":
            continue
        context = " ".join(c.ancestors[:4])
        if not re.search(r"position.*modif|modif.*position|positionedit|edit.*position|order.?modify|modify.?order", context, re.I):
            continue
        identity = c.name + " " + c.automation_id
        if re.search(r"cancel|close|remove|delete|reset|open", identity, re.I):
            continue
        # MT5 sometimes labels the *final* action simply "Modify".
        # Accept that label only inside an explicitly identified modify dialog.
        final_modify = (
            c.name.strip().casefold() in {"modify", "修改"}
            and re.search(r"order.?modify|modify.?order|modif(?:y|ication).*position|position.*modif", context, re.I)
        )
        if re.search(r"confirm|apply|save|submit|update", identity, re.I) or final_modify:
            hits.append(c)
    if len(hits) != 1:
        return None
    c = hits[0]
    return Candidate("position_modify_confirm", c.rect,
        f"已開啟持倉修改區內的 Button {_safe_id(c.automation_id)}；套用修改候選（未點擊）")


def _ctrader_account_number_target(
    controls: list[Control],
    bounds: tuple[int, int, int, int],
) -> Candidate | None:
    """Find the number *display*, not the account selector button or account value.

    Never expose the number itself. Require the exact WPF AutomationId and
    parent identity as observed from the authorized cTrader window.
    """
    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    matches = [
        ctrl for ctrl in controls
        if ctrl.kind == "Text"
        and ctrl.automation_id == "CTraderAccountNumberTextBlock_AId"
        and "CTraderAccountSelectorButton_AId" in " ".join(ctrl.ancestors[:3])
        and ctrl.rect[0] >= left + int(width * .52)
        and ctrl.rect[1] <= top + int(height * .17)
        and ctrl.rect[2] <= right
    ]
    if len(matches) != 1:
        return None
    return Candidate(
        "account_number", matches[0].rect,
        "cTrader 右上角帳號選單中的 CTraderAccountNumberTextBlock_AId；"
        "未讀取或顯示帳號數字，仍須人工確認",
    )


def match_all(
    platform: str,
    targets: Iterable[tuple[str, str]],
    controls: Iterable[Control],
    bounds: tuple[int, int, int, int],
) -> ScanReport:
    """Conservative read-only classification of all original calibration targets."""
    inventory = tuple(targets)
    result = ScanReport(platform, inventory)
    controls = [c for c in controls if c.enabled and c.visible and _inside(c.rect, bounds)]
    for key, label in inventory:
        if key in MANUAL_REASONS:
            result.reasons[key] = MANUAL_REASONS[key]
            continue
        rule = RULES.get(key)
        if not rule:
            result.reasons[key] = "尚無可靠的 UIA 類型及識別規則；保留手動校準"
            continue
        types, _ = rule
        matches = []
        for ctrl in controls:
            if ctrl.kind not in types:
                continue
            identity = ctrl.name + " " + ctrl.automation_id
            if not _COMPILED[key].search(identity):
                continue
            position = _is_position(ctrl)
            if key.startswith("position_") and not position:
                continue
            if key in {"lot_input", "sl_input", "tp_input"} and position:
                continue
            # For the value-only label "Ask", require a more specific UIA id.
            if key == "ask_price" and not re.search(r"ask", ctrl.automation_id, re.I):
                continue
            evidence = (
                f"UIA AutomationId={_safe_id(ctrl.automation_id)} / {ctrl.kind}"
                if ctrl.automation_id else
                f"UIA 可見名稱符合「{label}」的候選 / {ctrl.kind}"
            )
            matches.append(Candidate(key, ctrl.rect, evidence))
        if len(matches) == 1:
            result.candidates[key] = matches[0]
        elif len(matches) > 1:
            result.reasons[key] = f"出現 {len(matches)} 個候選，無法唯一判斷；不自動選取"
        else:
            result.reasons[key] = "目前視窗未找到符合角色與 UIA 類型的唯一控制項"
    if platform == "cTrader" and any(
        c.automation_id == "QuantityOrVolumeTextBox_AId" for c in controls
    ):
        # For the known cTrader order pane, do not fall back to potentially
        # ambiguous generic names for these seven related controls.
        specialized = _ctrader_order_suggestions(controls)
        for key in ("lot_input", "sl_checkbox", "tp_checkbox", "sl_input",
                    "tp_input", "buy_button", "sell_button"):
            if key in dict(inventory):
                result.candidates.pop(key, None)
                result.reasons[key] = "此訂單面板的 UIA 識別或相對位置未能唯一確認"
        for key, candidate in specialized.items():
            if key in dict(inventory):
                result.candidates[key] = candidate
                result.reasons.pop(key, None)
    # Distinguish final trade submission from direction toggles. Never use a
    # generic nearby button or a price/position-area row as a fallback.
    if platform == "cTrader" and "order_submit_button" in dict(inventory):
        result.candidates.pop("order_submit_button", None)
        candidate = _ctrader_submit_suggestion(controls)
        if candidate:
            result.candidates["order_submit_button"] = candidate
            result.reasons.pop("order_submit_button", None)
        else:
            result.reasons["order_submit_button"] = (
                "目前未看到可唯一驗證的 cTrader 真正送單 Button（方向切換鍵不算）"
            )
    if platform in {"MT5", "BYBIT MT5", "原版MT5"}:
        if "new_order_button" in dict(inventory):
            result.candidates.pop("new_order_button", None)
            candidate, reason = _mt5_main_new_order_suggestion(controls, bounds)
            if candidate is not None:
                result.candidates["new_order_button"] = candidate
                result.reasons.pop("new_order_button", None)
            else:
                result.reasons["new_order_button"] = reason
        if "ask_price" in dict(inventory) and "ask_price" not in result.candidates:
            current_price=_mt5_current_price_suggestion(controls)
            if current_price is not None:
                result.candidates["ask_price"]=current_price
                result.reasons.pop("ask_price",None)
        # In the separate MT5 order dialog, localized input fields can
        # have an empty UIA name. Offer only uniquely adjacent labeled edits,
        # as explicitly LOW CONFIDENCE yellow-box preview candidates.
        for key, candidate in _mt5_order_dialog_labeled_edits(controls).items():
            if (key in dict(inventory) and key not in result.candidates
                    and not result.reasons.get(key, "").startswith("出現 ")):
                result.candidates[key] = candidate
                result.reasons.pop(key, None)
        suggested = _mt5_market_submit_suggestions(controls)
        for key in ("order_submit_buy", "order_submit_sell"):
            if key not in dict(inventory):
                continue
            result.candidates.pop(key, None)
            if key in suggested:
                result.candidates[key] = suggested[key]
                result.reasons.pop(key, None)
            else:
                result.reasons[key] = "未找到唯一的市價 Buy/Sell 送單按鈕；需先自行開啟 MT5 下單視窗"
    if "position_modify_confirm" in dict(inventory):
        result.candidates.pop("position_modify_confirm", None)
        match = _modify_confirmation_suggestion(controls)
        if match:
            result.candidates["position_modify_confirm"] = match
            result.reasons.pop("position_modify_confirm", None)
        else:
            result.reasons["position_modify_confirm"] = "未看到已開啟的持倉修改視窗內唯一確認鍵；不猜測"
    if platform == "cTrader" and "account_number" in dict(inventory):
        account_target = _ctrader_account_number_target(controls, bounds)
        if account_target is not None:
            result.candidates["account_number"] = account_target
            result.reasons.pop("account_number", None)
        else:
            result.reasons["account_number"] = (
                "未能唯一確認右上角 CTraderAccountNumberTextBlock_AId"
            )
    # Never assign the same UIA rectangle to multiple roles.
    seen: dict[tuple[int, int, int, int], str] = {}
    for key, candidate in list(result.candidates.items()):
        if candidate.rect in seen:
            other = seen.pop(candidate.rect)
            result.candidates.pop(key, None)
            result.candidates.pop(other, None)
            for conflict in (key, other):
                result.reasons[conflict] = "多個校準角色共用相同 UIA 外框，辨識有歧義"
        else:
            seen[candidate.rect] = key
    return result

def _safe_id(value: str) -> str:
    return re.sub(r"\d{4,}", "[digits]", str(value or ""))[:90]

def _resolve_mt5_capture_origin(
    image_size: tuple[int, int],
    window_bounds: tuple[int, int, int, int],
    client_size: tuple[int, int],
    client_origin: tuple[int, int],
) -> tuple[int, int] | None:
    """Map Pillow screenshot pixels to absolute desktop coordinates.

    On Windows ImageGrab.grab(window=HWND) may return only CLIENT pixels;
    the UIA window bounds include the title bar. Ignoring this shifts every
    yellow rectangle upward by the nonclient title-bar height (~36px).
    Fail closed if neither capture geometry is confirmed.
    """
    w, h = image_size
    left, top, right, bottom = window_bounds
    if abs(w - client_size[0]) <= 2 and abs(h - client_size[1]) <= 2:
        return client_origin
    if abs(w - (right-left)) <= 2 and abs(h - (bottom-top)) <= 2:
        return (left, top)
    return None


def _mt5_client_geometry(handle: int) -> tuple[tuple[int,int],tuple[int,int]]:
    from ctypes import wintypes
    client = wintypes.RECT()
    origin = wintypes.POINT(0, 0)
    user32 = ctypes.windll.user32
    if not user32.GetClientRect(handle, ctypes.byref(client)):
        raise RuntimeError("讀取 MT5 訂單視窗用戶區尺寸失敗")
    if not user32.ClientToScreen(handle, ctypes.byref(origin)):
        raise RuntimeError("無法取得 MT5 訂單視窗用戶區的實際螢幕座標")
    return (client.right-client.left,client.bottom-client.top),(origin.x,origin.y)


def inspect_all_targets(
    handle: int,
    platform: str,
    targets: Iterable[tuple[str, str]],
    max_elements: int = 1200,
    timeout: float = 12.0,
    scan_related: bool = True,
) -> ScanReport:
    """Scan an existing visible window's UIA tree, without any input or write.

    MT5 submit/modify buttons may live in separately opened dialog windows.
    Optionally inspect only already-visible sibling broker windows of the same
    PID, never opening them or activating another program.
    """
    targets = tuple(targets)
    empty = ScanReport(platform, targets)
    if not isinstance(handle, int) or handle <= 0:
        raise ValueError("交易平台視窗識別碼無效")
    if platform not in {"cTrader", "MT5", "BYBIT MT5", "原版MT5"}:
        raise ValueError("目前完整掃描原型只支援 cTrader 和 MT5 系列")
    if ctypes.windll.user32.IsIconic(handle):
        empty.warnings = ("交易平台已最小化；請先開啟要校準的畫面，再執行掃描",)
        return empty
    from pywinauto import Desktop
    win = Desktop(backend="uia").window(handle=handle)
    root = win.element_info
    r = root.rectangle
    bounds = (int(r.left), int(r.top), int(r.right), int(r.bottom))
    start = time.monotonic()
    pending = [(root, 0, ())]
    observed: list[Control] = []
    count = 0
    while pending and count < max_elements and time.monotonic() - start < timeout:
        info, depth, ancestors = pending.pop()
        count += 1
        try:
            rect = info.rectangle
            title = str(info.name or "")
            automation_id = str(info.automation_id or "")
            kind = str(info.control_type or "")
            observed.append(Control(
                kind, title, automation_id,
                (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
                bool(info.enabled), bool(info.visible), ancestors,
            ))
            if depth < 9:
                parent_identity = (title + " " + automation_id)[:100]
                children = info.children()
                pending.extend((child, depth + 1, (parent_identity,) + ancestors[:2]) for child in children)
        except Exception:
            continue
    report = match_all(platform, targets, observed, bounds)
    report.scanned = count
    # MT5 sometimes draws the live quote and both market buttons as pixels,
    # with no usable UIA element. An optional SCREENSHOT-ONLY fallback
    # proposes low-confidence visual regions; all must still pass the
    # normal yellow-outline preview and explicit manual save.
    requested = {key for key, _ in targets}
    missed = requested.intersection({
        "ask_price", "order_submit_buy", "order_submit_sell",
    }).difference(report.candidates)
    if (platform in {"MT5", "BYBIT MT5", "原版MT5"} and missed
            and re.search(r"order|訂單|订单|下單", str(win.window_text()), re.I)):
        try:
            from PIL import ImageGrab
            from .mt5_visual_scan import detect_order_dialog_regions
            # Window-only grab: Pillow may capture just CLIENT contents.
            # Determine the real origin of those pixels; do NOT incorrectly
            # add the UIA whole-window top (includes title bar).
            try:
                screenshot = ImageGrab.grab(window=handle)
                client_size, client_origin = _mt5_client_geometry(handle)
                capture_origin = _resolve_mt5_capture_origin(
                    screenshot.size, bounds, client_size, client_origin,
                )
            except (TypeError, OSError):
                screenshot = ImageGrab.grab(bbox=bounds, all_screens=True)
                capture_origin = bounds[:2]
            if capture_origin is None:
                report.warnings += (
                    "MT5 截圖範圍與視窗尺寸不符，無法安全對齊黃框；請改手動校準。",
                )
            else:
                candidates = detect_order_dialog_regions(screenshot)
                for key in missed:
                    visual_rect = candidates.get(key)
                    if visual_rect is None:
                        continue
                    xa,ya,xb,yb = visual_rect
                    candidate = Candidate(
                        key,
                        (xa + capture_origin[0], ya + capture_origin[1],
                         xb + capture_origin[0], yb + capture_origin[1]),
                        "低信度：MT5 紅 Sell／藍 Buy 與單一參考價格的"
                        "用戶區座標已對齊候選；仍須黃框人工核對（從未點擊）",
                    )
                    report.candidates[key] = candidate
                    report.reasons.pop(key, None)
                # A LOW-CONFIDENCE visual match is still a valid PREVIEW
                # candidate, not a scan failure. Keep the caution in each
                # candidate's evidence (and checkbox label), NOT in warnings:
                # the preview dialog intentionally blocks selection whenever
                # report.warnings is non-empty. Real capture/geometry errors
                # remain in warnings and continue to block saving.
        except Exception:
            report.warnings += (
                "畫面擷取不可用，保留手動校準，不會猜測任何按鈕位置。",
            )
    if pending:
        report.warnings = ("UIA 掃描達到時間或控制項上限；結果可能不完整",)
    if scan_related and platform in {"MT5", "BYBIT MT5", "原版MT5", "cTrader"}:
        related_keys = {
            "order_submit_buy", "order_submit_sell", "order_submit_button",
            "position_modify_confirm",
        }
        remaining = tuple((key,label) for key,label in targets if key in related_keys)
        if remaining:
            try:
                process_id = int(root.process_id)
                # Only current PID, already-open visible *dialog* windows.
                # Never inspect unrelated windows or activate broker controls.
                for sibling in Desktop(backend="uia").windows(process=process_id):
                    if sibling.handle == handle:
                        continue
                    if not ctypes.windll.user32.IsWindowVisible(sibling.handle):
                        continue
                    if ctypes.windll.user32.IsIconic(sibling.handle):
                        continue
                    title = str(sibling.window_text() or "")
                    if not re.search(r"(?:\border\b|modify|position|下單|交易|修改)", title, re.I):
                        continue
                    extra = inspect_all_targets(
                        int(sibling.handle), platform, remaining,
                        max_elements=600, timeout=5.0, scan_related=False,
                    )
                    report.scanned += extra.scanned
                    for key, candidate in extra.candidates.items():
                        if key in report.candidates:
                            report.candidates.pop(key, None)
                            report.reasons[key] = "多個可見視窗都出現符合條件的按鈕；拒絕自動挑選"
                        elif not report.reasons.get(key, "").startswith("多個可見視窗"):
                            report.candidates[key] = candidate
                            report.reasons.pop(key, None)
            except Exception:
                report.warnings += ("額外下單／修改視窗的唯讀檢查不可用；請開啟視窗後手動校準",)
    return report

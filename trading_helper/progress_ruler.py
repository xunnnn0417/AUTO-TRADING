"""Read-only account milestone computations and a compact PySide6 ruler.

Never sends orders or writes sheet values. All firm-specific limits and
contract value assumptions must be configured explicitly per profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Mapping

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


FIELDS = (
    ("initial_balance", "帳號初始餘額"),
    ("maximum_loss", "最大虧損"),
    ("daily_max_loss", "每日最大虧損"),
    ("daily_profit_goal", "今天獲利目標"),
    ("account_profit_goal", "帳號獲利目標"),
    ("cash_per_price_unit", "每手價差 1 的損益金額"),
)


def decimal_value(value: object) -> Decimal | None:
    try:
        out = Decimal(str(value).replace(",", "").strip())
        return out if out.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def approximate_orders(distance: Decimal, single: Decimal, *, win: bool) -> str:
    """Display-only hint, NOT number of trades needed to breach a limit."""
    if distance <= 0:
        return "已達目標" if win else "已觸及限制"
    if single <= 0:
        return "無法估算"
    ratio = distance / single
    base = int(ratio.to_integral_value(rounding=ROUND_FLOOR))
    part = ratio - Decimal(base)
    if win:
        count = base if part <= Decimal("0.3") else base + 1
        if count == 0:
            count = 1
    else:
        count = base
        # The user explicitly wants 0.4 remaining SLs displayed near 0.
        if count == 0 and part < Decimal("0.4"):
            return "不足 1 單"
    return f"接近 {count} 單"


@dataclass(frozen=True)
class RulerState:
    markers: tuple[tuple[str, Decimal], ...]
    balance: Decimal
    win_hint: str
    loss_hint: str
    win_crossing: int
    loss_crossing: int
    tp_cash: Decimal
    sl_cash: Decimal


def prioritized_markers(
    *,
    initial: Decimal,
    maximum_floor: Decimal,
    daily_floor: Decimal,
    balance: Decimal,
    today_goal: Decimal,
    account_goal: Decimal,
) -> tuple[tuple[str, Decimal], ...]:
    """Preserve all six named values, even when two share a plotted tick.

    The UI co-locates grouped thresholds; calculation separately uses the
    stricter effective boundary, without hiding the other source value.
    """
    return (
        ("最大虧損", maximum_floor),
        ("每日最大虧損", daily_floor),
        ("當前餘額", balance),
        ("帳號初始餘額", initial),
        ("今天獲利目標", today_goal),
        ("帳號獲利目標", account_goal),
    )


def display_groups(
    markers: tuple[tuple[str, Decimal], ...],
) -> list[tuple[Decimal, tuple[tuple[str, Decimal], ...]]]:
    """One physical tick per applicable boundary; keep every source label."""
    values = dict(markers)
    coords = dict(values)
    if values["每日最大虧損"] <= values["最大虧損"]:
        coords["每日最大虧損"] = values["最大虧損"]
    if values["今天獲利目標"] >= values["帳號獲利目標"]:
        coords["今天獲利目標"] = values["帳號獲利目標"]
    groups: dict[Decimal, list[tuple[str, Decimal]]] = {}
    for name, value in markers:
        groups.setdefault(coords[name], []).append((name, value))
    return [(anchor, tuple(nodes)) for anchor, nodes in sorted(groups.items())]


def calculate_ruler(
    settings: Mapping[str, object],
    *,
    balance: Decimal | None,
    daily_pnl: Decimal | None,
    lot: Decimal,
    tp_distance: Decimal,
    sl_distance: Decimal,
) -> tuple[RulerState | None, str]:
    vals = {k: decimal_value(settings.get(k, "")) for k, _ in FIELDS}
    missing = [label for k, label in FIELDS if vals[k] is None]
    if balance is None or daily_pnl is None:
        return None, "請先讀取場內餘額及每日盈虧"
    if missing:
        return None, "請設定考核門檻與每手價差換算：" + "、".join(missing)
    if any(v <= 0 for v in vals.values()) or balance < 0 or lot <= 0:
        return None, "進度尺設定須為正數，且須有有效的場內手數"
    initial = vals["initial_balance"]
    daily_start = balance - daily_pnl
    maximum_floor = initial - vals["maximum_loss"]
    daily_floor = daily_start - vals["daily_max_loss"]
    today_goal = daily_start + vals["daily_profit_goal"]
    account_goal = initial + vals["account_profit_goal"]
    tp_cash = abs(tp_distance) * lot * vals["cash_per_price_unit"]
    sl_cash = abs(sl_distance) * lot * vals["cash_per_price_unit"]
    if tp_cash <= 0 or sl_cash <= 0:
        return None, "本單場內 TP／SL 無法換算為有效金額"

    win_distance = min(today_goal, account_goal) - balance
    loss_distance = balance - max(daily_floor, maximum_floor)
    win_crossing = max(0, int((win_distance / tp_cash).to_integral_value(rounding=ROUND_CEILING)))
    loss_crossing = max(0, int((loss_distance / sl_cash).to_integral_value(rounding=ROUND_CEILING)))
    return RulerState(
        markers=prioritized_markers(
            initial=initial, maximum_floor=maximum_floor,
            daily_floor=daily_floor, balance=balance,
            today_goal=today_goal, account_goal=account_goal,
        ),
        balance=balance,
        win_hint=approximate_orders(win_distance, tp_cash, win=True),
        loss_hint=approximate_orders(loss_distance, sl_cash, win=False),
        win_crossing=win_crossing,
        loss_crossing=loss_crossing,
        tp_cash=tp_cash,
        sl_cash=sl_cash,
    ), ""


SHEET_RULER_REFERENCES = {
    "運算區": ("B2", "F7", "F6", "B9", "C20"),
    "主要計算區": ("E2", "F2"),
}


def calculate_ruler_from_sheet(
    source: Mapping[str, Mapping[str, object]],
    *,
    balance: Decimal | None,
    daily_pnl: Decimal | None,
) -> tuple[RulerState | None, str]:
    """Read balance thresholds and single-trade P/L directly from sheet cells.

    F7 and B9 are absolute equity levels, never amounts subtracted/added to B2.
    F6 and C20 are amounts relative to the day's starting balance.
    """
    if balance is None or daily_pnl is None:
        return None, "請先讀取場內餘額及每日盈虧"
    if not balance.is_finite() or not daily_pnl.is_finite() or balance < 0:
        return None, "場內餘額或今日盈虧不是有效數字"
    calc = source.get("運算區", {})
    main = source.get("主要計算區", {})
    labels = {
        "B2": "初始餘額",
        "F7": "最大虧損餘額",
        "F6": "每日最大虧損金額",
        "B9": "帳號目標餘額",
        "C20": "今日獲利目標金額",
    }
    values = {cell: decimal_value(calc.get(cell)) for cell in labels}
    values["E2"] = decimal_value(main.get("E2"))
    values["F2"] = decimal_value(main.get("F2"))
    missing = [
        f"{'運算區' if cell in labels else '主要計算區'} {cell}"
        for cell, amount in values.items() if amount is None
    ]
    if missing:
        return None, "試算表資料不完整：" + "、".join(missing)
    initial, maximum_floor, daily_limit, target_balance, daily_target = (
        values["B2"], values["F7"], values["F6"], values["B9"], values["C20"]
    )
    raw_loss, raw_win = values["E2"], values["F2"]
    if (
        initial <= 0 or maximum_floor < 0 or daily_limit <= 0
        or target_balance <= 0 or daily_target <= 0
        or raw_loss >= 0 or raw_win <= 0
    ):
        return None, "考核門檻必須有效，且主要計算區 E2 應為負、F2 應為正"
    daily_start = balance - daily_pnl
    daily_floor = daily_start - daily_limit
    today_target = daily_start + daily_target
    sl_cash, tp_cash = abs(raw_loss), raw_win
    win_remaining = min(today_target, target_balance) - balance
    loss_remaining = balance - max(daily_floor, maximum_floor)
    win_crossing = max(0, int((win_remaining / tp_cash).to_integral_value(rounding=ROUND_CEILING)))
    loss_crossing = max(0, int((loss_remaining / sl_cash).to_integral_value(rounding=ROUND_CEILING)))
    return RulerState(
        markers=prioritized_markers(
            initial=initial, maximum_floor=maximum_floor,
            daily_floor=daily_floor, balance=balance,
            today_goal=today_target, account_goal=target_balance,
        ),
        balance=balance,
        win_hint=approximate_orders(win_remaining, tp_cash, win=True),
        loss_hint=approximate_orders(loss_remaining, sl_cash, win=False),
        win_crossing=win_crossing,
        loss_crossing=loss_crossing,
        tp_cash=tp_cash,
        sl_cash=sl_cash,
    ), ""


class AccountRuler(QWidget):
    """Read-only, hover-aware account ruler with grouped threshold labels.

    The source amounts are all displayed. When the account target supersedes
    today's goal (or the total loss line supersedes the daily line), both
    names/amounts attach to ONE geometric marker without misleading renaming.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state: RulerState | None = None
        self.placeholder = "等待試算表的帳號進度資料"
        self._hot_anchor: Decimal | None = None
        self._hot_segment: str | None = None
        self._hit_regions: list[tuple[QRectF, Decimal]] = []
        self._segment_regions: list[tuple[QRectF, str]] = []
        self.setMouseTracking(True)
        # Keep enough room for two labels at the SAME amount (for example
        # current balance == initial balance), without cropping the last row.
        self.setMinimumHeight(206)

    def set_state(self, state: RulerState | None, reason: str = "") -> None:
        self.state = state
        self.placeholder = reason or "尚未設定"
        self._hot_anchor = None
        self._hot_segment = None
        self.setToolTip(
            "\n".join(f"{name}：{money(v)}" for name, v in state.markers)
            if state else self.placeholder
        )
        self.update()

    @staticmethod
    def _short_label(name: str) -> str:
        return {
            "帳號初始餘額": "初始餘額",
            "帳號獲利目標": "帳號獲利目標",
            "今天獲利目標": "今日獲利目標",
        }.get(name, name)

    @staticmethod
    def _segment_text(hint: str, *, win: bool) -> str:
        event = "場外止損" if win else "場外止盈"
        if hint.startswith("已"):
            return f"{event} · {hint}"
        if hint.startswith("接近"):
            return f"{event} · {hint}結束"
        return f"{event} · {hint}"

    @staticmethod
    def _label_positions(items: list[tuple[float, tuple]], width: int) -> tuple[float, list[float]]:
        if not items:
            return 100, []
        n = len(items)
        pad = 5
        gap = 5
        label_width = min(140, max(74, (width - 2 * pad - (n - 1) * gap) / n))
        out: list[float] = []
        for x, _ in items:
            intended = max(pad, min(width - pad - label_width, x - label_width / 2))
            out.append(max(intended, out[-1] + label_width + gap if out else pad))
        if out and out[-1] + label_width > width - pad:
            out[-1] = width - pad - label_width
            for i in range(n - 2, -1, -1):
                out[i] = min(out[i], out[i + 1] - label_width - gap)
        return label_width, out

    def _geometry(self):
        if not self.state:
            return [], {}, lambda v: 0.0
        groups = display_groups(self.state.markers)
        all_anchors = [anchor for anchor, _ in groups]
        min_anchor = min(all_anchors)
        span = max(all_anchors) - min_anchor
        if span <= 0:
            span = Decimal(1)
        inset = 37
        extent = max(self.width() - 2 * inset, 1)
        def x_for(value):
            return inset + float((value - min_anchor) / span) * extent
        return groups, {anchor: x_for(anchor) for anchor, _ in groups}, x_for

    def mouseMoveEvent(self, event) -> None:
        px, py = event.position().x(), event.position().y()
        hovered = next(
            (anchor for bounds, anchor in reversed(self._hit_regions)
             if bounds.contains(px, py)), None)
        segment = next(
            (side for bounds, side in self._segment_regions if bounds.contains(px, py)),
            None
        )
        if (hovered, segment) != (self._hot_anchor, self._hot_segment):
            self._hot_anchor, self._hot_segment = hovered, segment
            if hovered is not None and self.state:
                nodes = next((nodes for anchor, nodes in display_groups(self.state.markers)
                              if anchor == hovered), ())
                self.setToolTip("\n".join(f"{name}：{money(v)}" for name, v in nodes))
            else:
                self.setToolTip("將滑鼠移到刻度或區間，可查看相對位置")
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hot_anchor = None
        self._hot_segment = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        """Short tick marks and one connected, two-color interval bracket."""
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._hit_regions = []
        self._segment_regions = []
        if not self.state:
            p.setPen(QColor("#9995a7"))
            p.drawText(QRectF(4, 24, self.width()-8, self.height()-40),
                       Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)
            p.end()
            return

        groups, coordinates, x_for = self._geometry()
        amounts = dict(self.state.markers)
        risk = max(amounts["最大虧損"], amounts["每日最大虧損"])
        goal = min(amounts["今天獲利目標"], amounts["帳號獲利目標"])
        balance = self.state.balance
        width = self.width()
        axis = 89
        p.setPen(QPen(QColor("#65616e"), 1.8))
        # Endpoints sit exactly on the outermost milestone dots: no tails.
        minimum_x = coordinates[groups[0][0]]
        maximum_x = coordinates[groups[-1][0]]
        p.drawLine(int(minimum_x), axis, int(maximum_x), axis)

        upper, lower = [], []
        for anchor, nodes in groups:
            record = coordinates[anchor], (anchor, nodes)
            if any(name in ("當前餘額", "帳號初始餘額") for name, _ in nodes):
                lower.append(record)
            else:
                upper.append(record)
        upper.sort(key=lambda e: e[0])
        lower.sort(key=lambda e: e[0])

        for lane, items in (("upper", upper), ("lower", lower)):
            label_width, label_starts = self._label_positions(items, width)
            for (x, (anchor, nodes)), label_x in zip(items, label_starts):
                active = self._hot_anchor == anchor
                current = any(name == "當前餘額" for name, _ in nodes)
                # Initial equity is historical context, not an action boundary.
                # Keep shared nodes prominent if an actual limit overlaps it.
                initial_only = (
                    len(nodes) == 1 and nodes[0][0] == "帳號初始餘額"
                )
                # Colors convey hierarchy: selected text stays off-white;
                # the saturated violet belongs to the current dot/line.
                ink = QColor("#ffffff") if active else (
                    QColor("#f1eef9") if current else (
                        QColor("#908b9a") if initial_only else QColor("#b6b0c2")
                    ))
                if lane == "upper":
                    # Two grouped goal rows need more space than ordinary
                    # labels, but every line remains SHORT at the tick.
                    top_y = 2 if len(nodes) > 1 else 34
                    start, end = axis-11, axis-7
                else:
                    top_y = 140
                    start, end = axis+7, axis+10

                p.setPen(QPen(QColor("#ffffff") if active else (
                    QColor("#57535f") if initial_only else QColor("#726b7e")),
                              1.4 if active else (0.8 if initial_only else 1.05)))
                p.drawLine(int(x), start, int(x), end)
                p.setPen(QPen(ink, 1.8 if active else 1.2))
                p.drawLine(int(x), axis-6, int(x), axis+6)
                # A deeper, more saturated amethyst with a thin silver rim
                # reads clearly on black. Hover changes the center to white.
                dot_size = 10 if active else (9 if current else (4 if initial_only else 6))
                if current:
                    p.setPen(QPen(QColor("#ddd2ff"), 1.0))
                p.setBrush(QColor("#ffffff") if active else (
                    QColor("#7752ed") if current else (
                        QColor("#67626f") if initial_only else QColor("#b9b3c2"))))
                p.drawEllipse(QRectF(x-dot_size/2, axis-dot_size/2,
                                     dot_size, dot_size))

                p.setFont(QFont("Microsoft JhengHei UI", 8,
                                QFont.DemiBold if active or current
                                else QFont.Normal))
                for i, (name, value) in enumerate(nodes):
                    yy = top_y+i*27
                    p.setPen(ink)
                    p.drawText(QRectF(label_x, yy, label_width, 13),
                               Qt.AlignCenter, self._short_label(name))
                    p.setPen(QColor("#ffffff") if active else (
                        QColor("#a9a3b1") if initial_only else QColor("#ddd7e7")))
                    p.drawText(QRectF(label_x, yy+13, label_width, 14),
                               Qt.AlignCenter, money(value))
                self._hit_regions.append((
                    QRectF(label_x-2, top_y-1, label_width+4,
                           len(nodes)*27+2), anchor))
                self._hit_regions.append((
                    QRectF(x-11, axis-11, 22, 22), anchor))

        # ONE continuous line, colored by the active risk/profit intervals.
        # Place captions immediately above/below this line, not on a second
        # bracket or on long leaders extending into empty space.
        current_x = x_for(balance)
        loss_x = x_for(risk)
        win_x = x_for(goal)
        # Scheme B: violet highlights the desired outside-TP / loss-side
        # interval; the opposite direction stays neutral silver-grey.
        # Both captions keep the SAME neutral text color.
        intervals = (
            ("loss", loss_x, current_x, self.state.loss_hint, False,
             QColor("#9279e7")),
            ("win", current_x, win_x, self.state.win_hint, True,
             QColor("#cbc9d1")),
        )
        for side, begin, end, hint, is_win, base in intervals:
            left, right = sorted((begin, end))
            hovering = self._hot_segment == side
            color = QColor("#ffffff") if hovering else base
            p.setPen(QPen(color, 2.8 if hovering else 2.2))
            # Highlight only the corresponding portion of the actual scale.
            p.drawLine(int(left), axis, int(right), axis)
            # A tiny midpoint tick visually ties the short caption back to
            # its actual segment; there is no extra horizontal line.
            middle = (left + right) / 2
            p.setPen(QPen(color, 1.25))
            if side == "loss":
                p.drawLine(int(middle), axis+4, int(middle), axis+8)
            else:
                p.drawLine(int(middle), axis-8, int(middle), axis-4)

            title = self._segment_text(hint, win=is_win)
            p.setFont(QFont("Microsoft JhengHei UI", 8,
                            QFont.DemiBold if hovering else QFont.Normal))
            target_w = p.fontMetrics().horizontalAdvance(title) + 10
            label_w = min(max(104, target_w), max(104, width - 10))
            # Alternate sides of ONE ruler: win above, loss below.
            # Even when the profit segment is short, its caption stays on
            # the same scale with a four-pixel midpoint tick.
            text_y = 102 if side == "loss" else 65
            label_left = max(3, min(width - label_w - 3,
                                    middle - label_w / 2))
            rect = QRectF(label_left, text_y, label_w, 16)
            # Both explanatory sentences have the same typographic color.
            # The interval itself, not one randomly colored caption,
            # distinguishes the profit side from the loss side.
            p.setPen(QColor("#ffffff") if hovering else QColor("#e1dfea"))
            p.drawText(rect, Qt.AlignCenter, title)
            self._segment_regions.append((
                QRectF(min(left, label_left), min(text_y, axis-4),
                       max(right, label_left+label_w) - min(left,label_left),
                       max(text_y+16, axis+6) - min(text_y, axis-4)),
                side,
            ))
        # Repaint the historical initial marker above the active segment:
        # otherwise the purple risk line would falsely make it a focus dot.
        initial = amounts["帳號初始餘額"]
        initial_nodes = next(
            (nodes for anchor, nodes in groups if anchor == initial), ()
        )
        if len(initial_nodes) == 1 and initial_nodes[0][0] == "帳號初始餘額":
            initial_hot = self._hot_anchor == initial
            initial_x = x_for(initial)
            size = 7 if initial_hot else 4
            p.setPen(QPen(QColor("#ffffff") if initial_hot else QColor("#77717e"), 0.8))
            p.setBrush(QColor("#ffffff") if initial_hot else QColor("#67626f"))
            p.drawEllipse(QRectF(initial_x-size/2, axis-size/2, size, size))
        # Draw the current-equity marker LAST so the crossing colored
        # segments cannot cover its violet center. This is the focal point.
        highlighted = self._hot_anchor == balance
        p.setPen(QPen(QColor("#e3d9ff"), 1.0))
        p.setBrush(QColor("#ffffff") if highlighted else QColor("#7752ed"))
        diameter = 10 if highlighted else 9
        p.drawEllipse(QRectF(current_x-diameter/2, axis-diameter/2,
                             diameter, diameter))
        p.end()

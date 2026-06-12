from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from .models import SideValues, TradeInstruction
from .windows import AutomationError, EmergencyController, WindowController


Log = Callable[[str], None]

REQUIRED_POINTS = {
    "cTrader": [
        "lot_input",
        "sl_checkbox",
        "sl_input",
        "tp_checkbox",
        "tp_input",
    ],
    "MT5": ["lot_input", "sl_input", "tp_input"],
}

TRADINGVIEW_REQUIRED_POINTS = [
    "long_tool",
    "short_tool",
    "position_placement",
    "entry_input",
    "sl_input",
    "tp_input",
    "confirm_button",
]


class PlatformAutomation:
    def __init__(
        self,
        config: dict[str, Any],
        windows: WindowController,
        emergency: EmergencyController,
        log: Log,
    ):
        self.config = config
        self.windows = windows
        self.emergency = emergency
        self.log = log

    def fill(
        self,
        platform: str,
        role: str,
        instruction: TradeInstruction,
    ) -> None:
        self.emergency.guard()
        profile = self.config["platforms"][platform]
        points = profile.get("points", {})
        missing = [name for name in REQUIRED_POINTS[platform] if name not in points]
        if missing:
            raise AutomationError(
                f"{platform} 尚未完成以下校準：{', '.join(missing)}"
            )
        pattern = profile["window_title"][role]
        window = self.windows.find(pattern)
        role_text = "場內" if role == "internal" else "場外"
        self.log(f"已找到{role_text} {platform} 視窗：{window.title}")

        should_open_panel = platform == "MT5" or profile.get(
            "open_panel_before_fill"
        )
        if should_open_panel and "new_order_button" in points:
            panel_is_open = self.windows.point_window_exists(
                profile, role, points["lot_input"]
            )
            if panel_is_open:
                self.log(f"{platform} 下單面板已開啟，直接填入。")
            else:
                self.log(f"正在開啟 {platform} 下單面板。")
                opener_window = self._window_for_point(
                    profile, role, points["new_order_button"]
                )
                self.windows.click(opener_window, points["new_order_button"])
                self.windows.wait_for_point_window(
                    profile, role, points["lot_input"], timeout=3.0
                )

        side: SideValues = getattr(instruction, role)
        direction = (
            instruction.internal_direction
            if role == "internal"
            else instruction.external_direction
        )
        if platform == "cTrader":
            direction_point = (
                "buy_button" if direction == "BUY" else "sell_button"
            )
            if direction_point not in points:
                raise AutomationError(
                    "cTrader 尚未校準"
                    f"{'買入' if direction == 'BUY' else '賣出'}方向按鈕。"
                )
            self.log(
                f"正在選擇{role_text} cTrader "
                f"{'買入' if direction == 'BUY' else '賣出'}方向。"
            )
            direction_window = self._window_for_point(
                profile, role, points[direction_point]
            )
            self.windows.click(direction_window, points[direction_point])
        if platform == "MT5":
            self._fill_field(
                profile,
                role,
                points,
                role_text,
                platform,
                "lot_input",
                "手數",
                _plain(side.lot),
            )
        current_price = None
        if platform == "MT5":
            price_point_name = self._mt5_price_point(role, direction)
            if price_point_name in points:
                price_window = self._window_for_point(
                    profile, role, points[price_point_name]
                )
                current_price = self.windows.read_number(
                    price_window, points[price_point_name]
                )
                self.log(f"已讀取{role_text} MT5 目前價格：{current_price}")
            elif instruction.estimated_price is None:
                raise AutomationError(
                    f"MT5 尚未校準 {price_point_name}，也沒有設定備用估算價格。"
                )
        values = self._field_values(
            platform,
            direction,
            side,
            instruction,
            current_price,
        )
        if platform == "cTrader":
            self._ensure_ctrader_risk_fields(profile, role, points)
        for point_name, label, value in values:
            if platform == "MT5" and point_name == "lot_input":
                continue
            self._fill_field(
                profile,
                role,
                points,
                role_text,
                platform,
                point_name,
                label,
                value,
            )
        self.log(f"{role_text} {platform} 欄位已填妥，沒有送出訂單。")

    def _fill_field(
        self,
        profile: dict[str, Any],
        role: str,
        points: dict[str, dict[str, Any]],
        role_text: str,
        platform: str,
        point_name: str,
        label: str,
        value: str,
    ) -> None:
        self.emergency.guard()
        self.log(f"正在填入{role_text} {platform} 的{label}：{value}")
        field_window = self._window_for_point(profile, role, points[point_name])
        point = points[point_name]
        calibrated_size = (
            int(point.get("window_width", field_window.width)),
            int(point.get("window_height", field_window.height)),
        )
        current_size = (field_window.width, field_window.height)
        if calibrated_size != current_size:
            self.log(
                f"{label}校準尺寸為 {calibrated_size[0]}×{calibrated_size[1]}，"
                f"目前為 {current_size[0]}×{current_size[1]}，將使用比例位置。"
            )
        self.windows.click_and_type(field_window, point, value)

    @staticmethod
    def _mt5_price_point(role: str, direction: str) -> str:
        return "ask_price"

    def _ensure_ctrader_risk_fields(
        self,
        profile: dict[str, Any],
        role: str,
        points: dict[str, dict[str, Any]],
    ) -> None:
        for point_name, label in (
            ("sl_checkbox", "止損"),
            ("tp_checkbox", "止盈"),
        ):
            checkbox_window = self._window_for_point(
                profile, role, points[point_name]
            )
            if self.windows.ensure_checkbox_checked(
                checkbox_window, points[point_name]
            ):
                self.log(f"已自動勾選 cTrader {label}。")
            else:
                self.log(f"cTrader {label}已勾選。")

    def _window_for_point(
        self,
        profile: dict[str, Any],
        role: str,
        point: dict[str, Any],
    ):
        point_pattern = str(point.get("window_title", "")).strip()
        patterns = [
            point_pattern,
            str(profile["window_title"][role]).strip(),
        ]
        if profile is self.config["platforms"].get("TradingView"):
            patterns.append(r"/\s*常用$")
        last_error: AutomationError | None = None
        for pattern in dict.fromkeys(value for value in patterns if value):
            try:
                return self.windows.find(pattern)
            except AutomationError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise AutomationError("視窗標題規則不可空白。")

    def _field_values(
        self,
        platform: str,
        direction: str,
        side: SideValues,
        instruction: TradeInstruction,
        base_price: Decimal | None = None,
    ) -> list[tuple[str, str, str]]:
        if platform == "cTrader":
            sl_value = side.sl_points / instruction.point_size
            tp_value = side.tp_points / instruction.point_size
            return [
                ("lot_input", "手數", _plain(side.lot)),
                ("sl_input", "止損點數", _plain(sl_value)),
                ("tp_input", "止盈點數", _plain(tp_value)),
            ]
        sl_price, tp_price = instruction.estimated_prices(
            direction, side, base_price
        )
        return [
            ("lot_input", "手數", _plain(side.lot)),
            ("sl_input", "估算止損價", instruction.format_price(sl_price)),
            ("tp_input", "估算止盈價", instruction.format_price(tp_price)),
        ]

    def draw_tradingview(
        self,
        instruction: TradeInstruction,
        *,
        internal_platform: str,
        entry_price_override: Decimal | None = None,
    ) -> None:
        self.emergency.guard()
        if entry_price_override is not None:
            entry_price = entry_price_override
            self.log(
                "使用手動場內實際進場價："
                f"{instruction.format_price(entry_price)}"
            )
        else:
            entry_price = self._read_internal_entry_price(
                instruction, internal_platform
            )
        sl_price, tp_price = instruction.estimated_prices(
            instruction.external_direction,
            instruction.external,
            entry_price,
        )

        profile = self.config["platforms"]["TradingView"]
        points = profile.get("points", {})
        missing = [
            name for name in TRADINGVIEW_REQUIRED_POINTS if name not in points
        ]
        if missing:
            raise AutomationError(
                "TradingView 尚未完成以下校準："
                + ", ".join(missing)
            )

        tradingview_window = self._window_for_point(
            profile, "external", points["position_placement"]
        )
        self.windows.hotkey(tradingview_window, "alt", "shift", "right")
        self.log("已用 Alt + Shift + → 前往 TradingView 最新價格。")
        self.windows.wait(1.0)
        tool_name = (
            "long_tool"
            if instruction.external_direction == "BUY"
            else "short_tool"
        )
        self._click_profile_point(profile, "external", points[tool_name])
        self._click_profile_point(
            profile, "external", points["position_placement"]
        )
        self.windows.wait(0.7)
        self.windows.double_click(
            self._window_for_point(
                profile, "external", points["position_placement"]
            ),
            points["position_placement"],
        )
        self.windows.wait(0.35)
        settings_window = self._window_for_point(
            profile, "external", points["entry_input"]
        )
        original_entry_price = self.windows.read_number(
            settings_window, points["entry_input"]
        )
        take_profit_is_valid = (
            tp_price > original_entry_price
            if instruction.external_direction == "BUY"
            else tp_price < original_entry_price
        )
        if take_profit_is_valid:
            field_order = (
                ("tp_input", tp_price, "止盈"),
                ("entry_input", entry_price, "進場"),
                ("sl_input", sl_price, "止損"),
            )
        else:
            field_order = (
                ("sl_input", sl_price, "止損"),
                ("entry_input", entry_price, "進場"),
                ("tp_input", tp_price, "止盈"),
            )
        self.log(
            f"TradingView 場外"
            f"{'多頭' if instruction.external_direction == 'BUY' else '空頭'}，"
            "原始進場價："
            f"{instruction.format_price(original_entry_price)}；"
            f"將依序輸入 {' → '.join(label for _, _, label in field_order)}。"
        )
        for point_name, value, _ in field_order:
            self._fill_profile_point(
                profile,
                "external",
                points[point_name],
                instruction.format_price(value),
            )
        self._click_profile_point(
            profile, "external", points["confirm_button"]
        )
        self.log(
            "TradingView 場外"
            f"{'多頭' if instruction.external_direction == 'BUY' else '空頭'}"
            f"部位已繪製：進場 {instruction.format_price(entry_price)}，"
            f"止損 {instruction.format_price(sl_price)}，"
            f"止盈 {instruction.format_price(tp_price)}。"
        )

    def sync_external_sl_tp(
        self,
        instruction: TradeInstruction,
        *,
        internal_platform: str,
        external_platform: str,
        entry_price_override: Decimal | None = None,
    ) -> None:
        self.emergency.guard()
        if entry_price_override is not None:
            entry_price = entry_price_override
            self.log(
                "使用手動場內實際進場價："
                f"{instruction.format_price(entry_price)}"
            )
        else:
            entry_price = self._read_internal_entry_price(
                instruction, internal_platform
            )
        sl_price, tp_price = instruction.estimated_prices(
            instruction.external_direction,
            instruction.external,
            entry_price,
        )

        profile = self.config["platforms"][external_platform]
        points = profile.get("points", {})
        if external_platform == "MT5":
            required = ["position_sl_input", "position_tp_input"]
        else:
            required = ["sl_input", "tp_input"]
            required.extend(["sl_checkbox", "tp_checkbox"])
        missing = [name for name in required if name not in points]
        if missing:
            raise AutomationError(
                f"{external_platform} 尚未完成以下校準：{', '.join(missing)}"
            )

        if external_platform == "MT5":
            if not self.windows.point_window_exists(
                profile, "external", points["position_sl_input"]
            ):
                position_point = points.get("positions_entry_price")
                if position_point is None:
                    raise AutomationError(
                        "MT5 修改視窗未開啟，且尚未校準持倉成交價位置。"
                    )
                self.log("正在從 MT5 場外持倉列開啟修改視窗。")
                position_window = self._window_for_point(
                    profile, "external", position_point
                )
                self.windows.double_click(position_window, position_point)
                self.windows.wait_for_point_window(
                    profile,
                    "external",
                    points["position_sl_input"],
                    timeout=3.0,
                )
            values = (
                (
                    "position_sl_input",
                    "正式止損價",
                    instruction.format_price(sl_price),
                ),
                (
                    "position_tp_input",
                    "正式止盈價",
                    instruction.format_price(tp_price),
                ),
            )
        else:
            self._ensure_ctrader_risk_fields(profile, "external", points)
            values = (
                (
                    "sl_input",
                    "止損點數",
                    _plain(instruction.external.sl_points / instruction.point_size),
                ),
                (
                    "tp_input",
                    "止盈點數",
                    _plain(instruction.external.tp_points / instruction.point_size),
                ),
            )

        for point_name, label, value in values:
            self._fill_field(
                profile,
                "external",
                points,
                "場外",
                external_platform,
                point_name,
                label,
                value,
            )
        self.log(
            f"場外 {external_platform} 止盈止損已填入："
            f"場內成交價 {instruction.format_price(entry_price)}，"
            f"止損 {instruction.format_price(sl_price)}，"
            f"止盈 {instruction.format_price(tp_price)}。"
            "程式沒有按下最後確認按鈕。"
        )

    def _read_internal_entry_price(
        self,
        instruction: TradeInstruction,
        internal_platform: str,
    ) -> Decimal:
        internal_profile = self.config["platforms"][internal_platform]
        internal_points = internal_profile.get("points", {})
        entry_point = internal_points.get("positions_entry_price")
        if entry_point is None:
            raise AutomationError(
                f"{internal_platform} 尚未校準持倉成交價位置。"
            )
        entry_window = self._window_for_point(
            internal_profile, "internal", entry_point
        )
        if internal_platform == "cTrader":
            entry_price = self.windows.read_hover_number(
                entry_window, entry_point
            )
        else:
            entry_price = self.windows.read_number(entry_window, entry_point)
        self.log(
            f"已讀取場內 {internal_platform} 實際進場價："
            f"{instruction.format_price(entry_price)}"
        )
        return entry_price

    def _click_profile_point(
        self,
        profile: dict[str, Any],
        role: str,
        point: dict[str, Any],
    ) -> None:
        self.windows.click(self._window_for_point(profile, role, point), point)

    def _fill_profile_point(
        self,
        profile: dict[str, Any],
        role: str,
        point: dict[str, Any],
        value: str,
    ) -> None:
        self.windows.click_and_type(
            self._window_for_point(profile, role, point),
            point,
            value,
        )

def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")

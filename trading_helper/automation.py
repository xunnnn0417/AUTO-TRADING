from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from .models import SideValues, TradeInstruction
from .windows import AutomationError, EmergencyController, WindowController


Log = Callable[[str], None]

REQUIRED_POINTS = {
    "GooeyTrade": [
        "lot_input",
        "sl_checkbox",
        "sl_input",
        "tp_checkbox",
        "tp_input",
    ],
    "cTrader": [
        "lot_input",
        "sl_checkbox",
        "sl_input",
        "tp_checkbox",
        "tp_input",
    ],
    "MT5": ["lot_input", "sl_input", "tp_input"],
    "BYBIT MT5": ["lot_input", "sl_input", "tp_input"],
    "原版MT5": ["lot_input", "sl_input", "tp_input"],
}

TRADINGVIEW_REQUIRED_POINTS = [
    "auto_scale_button",
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

        should_open_panel = _is_mt5(platform) or profile.get(
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
        if _is_ctrader(platform):
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
        if _is_mt5(platform):
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
        if _is_mt5(platform):
            price_point_name = self._mt5_price_point(role, direction)
            if price_point_name in points:
                price_window = self._window_for_point(
                    profile, role, points[price_point_name]
                )
                try:
                    current_price = self.windows.read_number(
                        price_window, points[price_point_name]
                    )
                    self.log(f"已讀取{role_text} MT5 目前價格：{current_price}")
                except AutomationError as exc:
                    if instruction.estimated_price is None:
                        raise
                    current_price = instruction.estimated_price
                    self.log(
                        f"{role_text} MT5 目前價格辨識失敗，"
                        f"改用表格估算價格：{current_price}。原因：{exc}"
                    )
            elif instruction.estimated_price is None:
                raise AutomationError(
                    f"MT5 尚未校準 {price_point_name}，也沒有設定備用估算價格。"
                )
        ctrader_uses_point_size = (
            self._ctrader_uses_point_size(platform, profile, role, points)
            if _is_ctrader(platform)
            else False
        )
        values = self._field_values(
            platform,
            direction,
            side,
            instruction,
            current_price,
            ctrader_uses_point_size=ctrader_uses_point_size,
        )
        if _is_ctrader(platform):
            self._ensure_ctrader_risk_fields(profile, role, points)
        for point_name, label, value in values:
            if _is_mt5(platform) and point_name == "lot_input":
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
        if profile is self.config["platforms"].get("TradingView"):
            patterns = [
                point_pattern,
                str(profile["window_title"][role]).strip(),
                r"/\s*常用$",
            ]
        elif profile is self.config["platforms"].get("MT5"):
            patterns = [
                point_pattern,
                str(profile["window_title"][role]).strip(),
            ]
        else:
            patterns = [str(profile["window_title"][role]).strip()]
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
        *,
        ctrader_uses_point_size: bool = False,
    ) -> list[tuple[str, str, str]]:
        if _is_ctrader(platform):
            uses_point_size = platform == "GooeyTrade" or ctrader_uses_point_size
            sl_value = (
                side.sl_points / instruction.point_size
                if uses_point_size
                else side.sl_points
            )
            tp_value = (
                side.tp_points / instruction.point_size
                if uses_point_size
                else side.tp_points
            )
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
        draw_internal: bool = False,
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
        tv_direction = (
            instruction.internal_direction
            if draw_internal
            else instruction.external_direction
        )
        tv_side = instruction.internal if draw_internal else instruction.external
        tv_side_label = "場內" if draw_internal else "場外"
        sl_price, tp_price = instruction.estimated_prices(
            tv_direction,
            tv_side,
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
        self.windows.click(
            tradingview_window, points["position_placement"]
        )
        self.windows.wait(0.25)
        self.windows.hotkey(
            tradingview_window,
            "alt",
            "shift",
            "right",
            interval=0.08,
        )
        self.log("已用 Alt + Shift + → 前往 TradingView 最新價格。")
        self.windows.wait(1.0)
        self._click_profile_point(
            profile, "external", points["auto_scale_button"]
        )
        self.log("已開啟 TradingView 自動適應價格模式。")
        self.windows.wait(0.7)
        tool_name = (
            "long_tool"
            if tv_direction == "BUY"
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
            if tv_direction == "BUY"
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
            f"TradingView {tv_side_label}"
            f"{'多頭' if tv_direction == 'BUY' else '空頭'}，"
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
        self.windows.wait(0.35)
        self._click_profile_point(
            profile, "external", points["auto_scale_button"]
        )
        self.log("已關閉 TradingView 自動適應價格模式。")
        self.log(
            f"TradingView {tv_side_label}"
            f"{'多頭' if tv_direction == 'BUY' else '空頭'}"
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
        if _is_mt5(external_platform):
            required = [
                "position_sl_input",
                "position_tp_input",
                "position_order_lot",
                "position_order_lot_next",
                "position_order_row",
            ]
        else:
            required = ["sl_input", "tp_input"]
            required.extend(["sl_checkbox", "tp_checkbox"])
        missing = [name for name in required if name not in points]
        if missing:
            raise AutomationError(
                f"{external_platform} 尚未完成以下校準：{', '.join(missing)}"
            )

        if _is_mt5(external_platform):
            if not self.windows.point_window_exists(
                profile, "external", points["position_sl_input"]
            ):
                expected_lot = instruction.external.lot
                matched_row = self._find_mt5_position_row(
                    profile,
                    points,
                    expected_lot,
                    max_rows=30,
                )
                if matched_row is None:
                    raise AutomationError(
                        "找不到手數符合的 MT5 場外訂單，已停止修改。"
                        f"試算表要求 {expected_lot}。"
                    )
                position_point = self._offset_position_point(
                    points["position_order_row"],
                    points["position_order_lot"],
                    points["position_order_lot_next"],
                    matched_row,
                )
                self.log(
                    f"已找到第 {matched_row + 1} 筆手數相符的 MT5 場外訂單，"
                    "正在雙擊開啟修改視窗。"
                )
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
            external_values = self._field_values(
                external_platform,
                instruction.external_direction,
                instruction.external,
                instruction,
                ctrader_uses_point_size=self._ctrader_uses_point_size(
                    external_platform, profile, "external", points
                ),
            )
            values = (
                (
                    "sl_input",
                    "止損點數",
                    next(
                        value
                        for point_name, _, value in external_values
                        if point_name == "sl_input"
                    ),
                ),
                (
                    "tp_input",
                    "止盈點數",
                    next(
                        value
                        for point_name, _, value in external_values
                        if point_name == "tp_input"
                    ),
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

    def _find_mt5_position_row(
        self,
        profile: dict[str, Any],
        points: dict[str, dict[str, Any]],
        expected_lot: Decimal,
        *,
        max_rows: int,
    ) -> int | None:
        first_lot = points["position_order_lot"]
        next_lot = points["position_order_lot_next"]
        for row_index in range(max_rows):
            self.emergency.guard()
            lot_point = self._offset_position_point(
                first_lot, first_lot, next_lot, row_index
            )
            lot_window = self._window_for_point(
                profile, "external", lot_point
            )
            try:
                detected_lot = self.windows.read_number(lot_window, lot_point)
            except AutomationError:
                self.log(
                    f"MT5 場外第 {row_index + 1} 筆無法辨識手數，"
                    "停止往下搜尋。"
                )
                return None
            self.log(
                f"MT5 場外第 {row_index + 1} 筆手數："
                f"{detected_lot}，預期 {expected_lot}。"
            )
            if detected_lot == expected_lot:
                return row_index
        return None

    @staticmethod
    def _offset_position_point(
        point: dict[str, Any],
        first_row: dict[str, Any],
        next_row: dict[str, Any],
        row_index: int,
    ) -> dict[str, Any]:
        result = dict(point)
        if "y_px" in result and "y_px" in first_row and "y_px" in next_row:
            row_height_px = int(next_row["y_px"]) - int(first_row["y_px"])
            result["y_px"] = int(result["y_px"]) + row_height_px * row_index
        if "y" in result and "y" in first_row and "y" in next_row:
            row_height = float(next_row["y"]) - float(first_row["y"])
            result["y"] = float(result["y"]) + row_height * row_index
        return result

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
        self.log(
            f"正在依場內平台選擇讀取視窗：{internal_platform}，"
            f"視窗：{entry_window.title}"
        )
        if _is_ctrader(internal_platform):
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

    @staticmethod
    def _ctrader_uses_point_size(
        platform: str,
        profile: dict[str, Any],
        role: str,
        points: dict[str, dict[str, Any]],
    ) -> bool:
        if platform == "GooeyTrade":
            return True
        if platform != "cTrader":
            return False
        texts: list[str] = [str(profile.get("window_title", {}).get(role, ""))]
        for point_name in (
            "lot_input",
            "sl_input",
            "tp_input",
            "sl_checkbox",
            "tp_checkbox",
        ):
            point = points.get(point_name, {})
            texts.extend(
                [
                    str(point.get("window_title", "")),
                    str(point.get("calibration_window_title", "")),
                ]
            )
        return any("GooeyTrade" in text for text in texts)

def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def _is_ctrader(platform: str) -> bool:
    return platform in {"GooeyTrade", "cTrader"}


def _is_mt5(platform: str) -> bool:
    return platform in {"MT5", "BYBIT MT5", "原版MT5"}

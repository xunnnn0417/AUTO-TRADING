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
    "latest_price_button",
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
        return self.windows.find(
            point_pattern or profile["window_title"][role]
        )

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
        external_platform: str,
    ) -> None:
        self.emergency.guard()
        if external_platform != "MT5":
            raise AutomationError(
                "TradingView 部位目前需要場外平台為 MT5，才能讀取 Ask。"
            )

        mt5_profile = self.config["platforms"]["MT5"]
        mt5_points = mt5_profile.get("points", {})
        if "ask_price" not in mt5_points:
            raise AutomationError("MT5 尚未校準 Ask 價格位置。")
        ask_window = self._window_for_point(
            mt5_profile, "external", mt5_points["ask_price"]
        )
        entry_price = self.windows.read_number(
            ask_window, mt5_points["ask_price"]
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

        self._click_profile_point(
            profile, "external", points["latest_price_button"]
        )
        tool_name = (
            "long_tool"
            if instruction.external_direction == "BUY"
            else "short_tool"
        )
        self._click_profile_point(profile, "external", points[tool_name])
        self._click_profile_point(
            profile, "external", points["position_placement"]
        )
        self.windows.double_click(
            self._window_for_point(
                profile, "external", points["position_placement"]
            ),
            points["position_placement"],
        )
        self._fill_profile_point(
            profile,
            "external",
            points["entry_input"],
            instruction.format_price(entry_price),
        )
        self._fill_profile_point(
            profile,
            "external",
            points["sl_input"],
            instruction.format_price(sl_price),
        )
        self._fill_profile_point(
            profile,
            "external",
            points["tp_input"],
            instruction.format_price(tp_price),
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

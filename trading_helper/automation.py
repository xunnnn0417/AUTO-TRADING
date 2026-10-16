from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .config import ctrader_mode_for_profile
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


class CTraderDecimalInputSuggestion(AutomationError):
    """Two confirmed truncated decimal writes; let GUI offer opt-in.

    The fill operation MUST stop here. No automatic mode change, retry,
    broker order submission, or cross-side continuation is performed.
    """
    def __init__(self, role_text: str, label: str, expected: str, actual: str):
        self.role_text = role_text
        self.label = label
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{role_text} cTrader {label}連續兩次輸入小數後只保留整數部分："
            f"預期 {expected}、讀回 {actual}。已停止填寫。"
        )


class PlatformAutomation:
    def __init__(
        self,
        config: dict[str, Any],
        windows: WindowController,
        emergency: EmergencyController,
        log: Log,
        profile_name: str = "",
    ):
        self.profile_name = profile_name
        self.config = config
        self.windows = windows
        self.emergency = emergency
        self.log = log
        # Only values read back after the CURRENT fill operation qualify
        # as expected SL/TP for its later final pre-submit check. Never
        # rely solely on non-zero SL/TP or on a previous order's settings.
        self._last_verified_fills: dict[tuple[str, str], dict] = {}

    def fill(
        self,
        platform: str,
        role: str,
        instruction: TradeInstruction,
    ) -> None:
        self._last_verified_fills.pop((platform, role), None)
        self.emergency.guard()
        profile = self.config["platforms"][platform]
        points = profile.get("points", {})
        required=list(REQUIRED_POINTS[platform])
        if _is_ctrader(platform):
            required.extend(("buy_button","sell_button"))
        missing = [name for name in required if name not in points]
        if missing:
            raise AutomationError(
                f"{platform} 尚未完成以下校準：{', '.join(missing)}"
            )
        pattern = profile["window_title"][role]
        if _is_ctrader(platform) and isinstance(self.windows, WindowController):
            window = self.windows.find_calibrated_main(
                pattern, points["lot_input"], platform=platform
            )
        else:
            window = self.windows.find(pattern)
        bound_window = window
        role_text = "場內" if role == "internal" else "場外"
        self.log(f"已找到{role_text} {platform} 視窗：{window.title}")
        if _is_ctrader(platform):
            self._verify_ctrader_account(platform, profile, role, window)

        mt5_order_window = None
        should_open_panel = _is_mt5(platform) or profile.get(
            "open_panel_before_fill"
        )
        if _is_mt5(platform):
            # Reuse an already-open, independently verified native order modal.
            # Waiting for a foreground-window CHANGE falsely fails when
            # the same MT5 order window was open before this fill began.
            from .demo_broker_port import DemoUiBrokerPort
            port = DemoUiBrokerPort(self, self.log)
            port.set_expected_symbol(instruction.symbol)
            _, mt5_order_window = port._form_window(
                platform, role, allow_absent=True
            )
            if mt5_order_window is not None:
                self.log(
                    f"{role_text} {platform} 新訂單視窗已開啟，"
                    "沿用現有視窗，不重複點擊新訂單。"
                )
            else:
                if "new_order_button" not in points:
                    raise AutomationError(
                        f"{role_text} MT5 新訂單視窗未開啟且尚未校準新訂單按鈕。"
                    )
                self.windows.click(bound_window, points["new_order_button"])
                deadline = time.monotonic() + 2.5
                while time.monotonic() < deadline:
                    self.emergency.guard()
                    _, mt5_order_window = port._form_window(
                        platform, role, allow_absent=True
                    )
                    if mt5_order_window is not None:
                        break
                    time.sleep(0.05)
                if mt5_order_window is None:
                    raise AutomationError(
                        f"{role_text} MT5 點擊新訂單後未找到唯一、"
                        "商品與校準尺寸均符合的訂單視窗；"
                        "不以主視窗或過時標題代替，已停止填寫。"
                    )
            self.log(f"{role_text} {platform} 訂單視窗：{mt5_order_window.title}")
        elif should_open_panel and "new_order_button" in points:
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
                forced_window=mt5_order_window,
            )
        current_price = None
        if _is_mt5(platform):
            price_point_name = self._mt5_price_point(role, direction)
            if price_point_name in points:
                price_window = mt5_order_window or self._window_for_point(
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
                forced_window=mt5_order_window if _is_mt5(platform) else None,
            )
        self._verify_filled_side(
            profile, role, platform, role_text, points, window,
            mt5_order_window, direction, values,
        )
        # The MT5 prices here are the actual values written and checked
        # using this fill's quote (not a later recalculation from a moved
        # quote). cTrader native/gooey point modes have already been
        # applied by _field_values. A failed fill never reaches this line.
        self._last_verified_fills[(platform, role)] = {
            "direction": direction,
            "symbol": instruction.symbol,
            "values": {
                key: self._normalize_numeric_input(value)
                for key, _, value in values
            },
        }
        self.log(f"{role_text} {platform} 欄位全部讀回核對正確，沒有送出訂單。")

    @staticmethod
    def _normalize_numeric_input(
        raw: str, expected: Decimal | None = None
    ) -> Decimal:
        """Compare numeric UIA values, honoring the expected decimal format."""
        value=str(raw).strip()
        value=value.replace("−","-").replace("\u00a0","")
        value=value.replace("\u202f","").replace(" ","").replace("'","")
        # Decimal comma: 0,74 -> 0.74. Thousands grouping: 4,117.46.
        if "," in value and "." in value:
            if value.rfind(",") > value.rfind("."):
                value=value.replace(".","").replace(",",".")
            else:
                value=value.replace(",","")
        elif "," in value:
            bits=value.split(",")
            if len(bits)==2 and len(bits[1])==3 and len(bits[0])>=1:
                # "0,740" is a decimal comma for some locale settings,
                # while "3,378" may be a thousands group. The known
                # expected numeric value disambiguates the two safely.
                decimal_form=Decimal(value.replace(",","."))
                if expected is not None and decimal_form==expected:
                    value=value.replace(",",".")
                else:
                    value="".join(bits)
            else:
                value=value.replace(",",".")
        try:
            result=Decimal(value)
        except (InvalidOperation,ValueError) as exc:
            raise AutomationError(
                f"讀回值「{raw}」不是可確認的純數字，已停止；不會猜測。"
            ) from exc
        if not result.is_finite():
            raise AutomationError("欄位讀回不是有效有限數字，已停止。")
        return result

    def _verify_filled_side(
        self,
        profile: dict[str, Any],
        role: str,
        platform: str,
        role_text: str,
        points: dict[str, dict[str, Any]],
        bound_window,
        mt5_order_window,
        direction: str,
        values: list[tuple[str,str,str]],
    ) -> None:
        """Verify each side AFTER all initial writes, then repair mismatches.

        Each field is written at most THREE times TOTAL (initial + two
        repairs). UIA access failure != confirmed value mismatch; stop rather
        than risking blind repeat input or order clicks.
        """
        attempts={key:1 for key,_,_ in values}
        expected={key:self._normalize_numeric_input(value)
                  for key,_,value in values}
        verified={}
        max_cycles=3*len(values)+1
        for _ in range(max_cycles):
            self.emergency.guard()
            # A native controller can read every UIA control once per
            # verification cycle. Old fakes/adapters retain the original
            # checked per-field readback as a compatibility fallback.
            batch=None
            if hasattr(self.windows,"read_fill_snapshot"):
                common_window=(
                    mt5_order_window if _is_mt5(platform) else bound_window
                )
                if common_window is None:
                    raise AutomationError(
                        f"{role_text} {platform} 找不到唯一的下單視窗，已停止。"
                    )
                try:
                    batch=self.windows.read_fill_snapshot(
                        common_window,points,ctrader=_is_ctrader(platform)
                    )
                except AutomationError as exc:
                    raise AutomationError(
                        f"{role_text} {platform} 整側 UIA 核對失敗：{exc}"
                        "。已停止，未重填。"
                    ) from exc
            if _is_ctrader(platform) and batch is None:
                actual_direction=self.windows.read_ctrader_direction(
                    bound_window,points
                )
                if actual_direction!=direction:
                    raise AutomationError(
                        f"{role_text} {platform} 方向錯誤：預期 {direction}，"
                        f"實際 {actual_direction}；已停止。"
                    )
                for name,label in (
                    ("sl_checkbox","止損"),("tp_checkbox","止盈")
                ):
                    checkbox_window=self._window_for_point(
                        profile,role,points[name]
                    )
                    if not self.windows.read_ctrader_checkbox_checked(
                        checkbox_window,points[name],name
                    ):
                        raise AutomationError(
                            f"{role_text} {platform} {label}勾選已關閉，"
                            "已停止；請重新檢查下單面板。"
                        )
            if _is_ctrader(platform) and batch is not None:
                if batch["direction"]!=direction:
                    raise AutomationError(
                        f"{role_text} {platform} 方向錯誤：預期 {direction}，"
                        f"實際 {batch['direction']}；已停止。"
                    )
                for name,label in (
                    ("sl_checkbox","止損"),("tp_checkbox","止盈")
                ):
                    if not batch["checks"].get(name,False):
                        raise AutomationError(
                            f"{role_text} {platform} {label}勾選已關閉，"
                            "已停止；請重新檢查下單面板。"
                        )
            mismatches=[]
            for point_name,label,value in values:
                self.emergency.guard()
                try:
                    if batch is not None:
                        readback=batch["values"][point_name]
                    else:
                        field_window=(mt5_order_window if _is_mt5(platform)
                                      else self._window_for_point(
                                          profile,role,points[point_name]
                                      ))
                        readback=self.windows.read_edit_value(
                            field_window,points[point_name]
                        )
                    observed=self._normalize_numeric_input(
                        readback,expected[point_name]
                    )
                except (AutomationError, KeyError, TypeError) as exc:
                    raise AutomationError(
                        f"{role_text} {platform} {label} 無法讀回確認：{exc}"
                        "。已停止；未執行重填。"
                    ) from exc
                if observed != expected[point_name]:
                    mismatches.append((point_name,label,value,readback))
                else:
                    verified[point_name]=readback
            if not mismatches:
                self.log(
                    f"{role_text} {platform} 核對通過："
                    + "、".join(
                        f"{label}={verified[key]}"
                        for key,label,_ in values
                    )
                    + ("，方向與 SL/TP 勾選狀態正常"
                       if _is_ctrader(platform) else "")
                )
                return
            # Repair just ONE wrong field then reread the ENTIRE side: a
            # platform may recompute another field when this one changes.
            point_name,label,value,readback=mismatches[0]
            count=attempts[point_name]
            if (
                platform == "cTrader"
                and ctrader_mode_for_profile(self.config, self.profile_name)
                    == "native"
                and point_name in ("sl_input", "tp_input")
                and count >= 2
            ):
                # Suggest conversion ONLY for a verified fractional value
                # whose entire fractional part vanished on 2 writes.
                # Unreadable data, unrelated mismatches, MT5 and GooeyTrade
                # do not trigger the suggestion.
                target=expected[point_name]
                got=self._normalize_numeric_input(
                    readback, expected[point_name]
                )
                if (
                    target != target.to_integral_value()
                    and got == Decimal(int(target))
                ):
                    raise CTraderDecimalInputSuggestion(
                        role_text, label, value, readback
                    )
            if count>=3:
                raise AutomationError(
                    f"{role_text} {platform} {label} 核對失敗（三次填入）。"
                    f"預期 {value}，實際讀回「{readback}」。"
                    "已停止後續場別操作，未送出訂單。"
                )
            self.log(
                f"{role_text} {platform} {label} 不一致："
                f"預期 {value}、實際「{readback}」。"
                f"重新填入第 {count+1}/3 次，接著重查整側。"
            )
            self._fill_field(
                profile,role,points,role_text,platform,
                point_name,label,value,
                forced_window=(mt5_order_window if _is_mt5(platform) else None),
            )
            attempts[point_name]+=1
        raise AutomationError(
            f"{role_text} {platform} 多欄相互變動，三次修正內無法穩定確認，"
            "已停止；未送出訂單。"
        )

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
        *,
        forced_window=None,
    ) -> None:
        self.emergency.guard()
        self.log(f"正在填入{role_text} {platform} 的{label}：{value}")
        field_window = forced_window or self._window_for_point(
            profile, role, points[point_name]
        )
        point = points[point_name]
        calibrated_size = (
            int(point.get("window_width", field_window.width)),
            int(point.get("window_height", field_window.height)),
        )
        current_size = (field_window.width, field_window.height)
        if calibrated_size != current_size:
            self.log(
                f"{label}校準尺寸為 {calibrated_size[0]}×{calibrated_size[1]}，"
                f"目前為 {current_size[0]}×{current_size[1]}。"
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
            clicks = self.windows.refresh_checkbox_checked(
                checkbox_window, points[point_name], point_name
            )
            if clicks == 2:
                self.log(f"cTrader {label}原本已勾選，已關閉後重新打開。")
            else:
                self.log(f"cTrader {label}原本未勾選，已打開。")

    def _verify_ctrader_account(
        self,
        platform: str,
        profile: dict[str, Any],
        role: str,
        window,
    ) -> None:
        expected = str(
            profile.get("account_number", {}).get(role, "")
        ).strip()
        expected_digits = "".join(re.findall(r"\d+", expected))
        point = profile.get("points", {}).get("account_number")
        if not expected_digits or not point:
            return
        role_text = "場內" if role == "internal" else "場外"
        detected = self.windows.read_account_number(window, point)
        if detected != expected_digits:
            raise AutomationError(
                f"{role_text} cTrader 帳號不符：目前偵測到 {detected}，"
                f"綁定帳號是 {expected_digits}。請更改{role_text}帳號。"
            )
        self.log(f"已確認{role_text} cTrader 帳號：{detected}")

    def _window_for_point(
        self,
        profile: dict[str, Any],
        role: str,
        point: dict[str, Any],
    ):
        point_pattern = str(point.get("window_title", "")).strip()
        calibration_pattern = str(point.get("calibration_window_title", "")).strip()
        if profile is self.config["platforms"].get("TradingView"):
            patterns = [
                point_pattern,
                calibration_pattern,
                str(profile["window_title"][role]).strip(),
                r"/\s*常用$",
            ]
        elif profile is self.config["platforms"].get("MT5"):
            patterns = [
                point_pattern,
                calibration_pattern,
                str(profile["window_title"][role]).strip(),
            ]
        else:
            patterns = [str(profile["window_title"][role]).strip()]
        # Every cTrader/GooeyTrade field and position-read entrypoint uses
        # one canonical calibrated MAIN window resolver, not the first
        # same-title modal from Win32's Z-order.
        if (
            isinstance(self.windows, WindowController)
            and (profile is self.config["platforms"].get("cTrader")
                 or profile is self.config["platforms"].get("GooeyTrade"))
        ):
            platform = (
                "GooeyTrade"
                if profile is self.config["platforms"].get("GooeyTrade")
                else "cTrader"
            )
            return self.windows.find_calibrated_main(
                str(profile["window_title"][role]), point, platform=platform
            )
        last_error: AutomationError | None = None
        for pattern in dict.fromkeys(value for value in patterns if value):
            try:
                matches = (
                    self.windows.find_all(pattern)
                    if hasattr(self.windows, "find_all")
                    else [self.windows.find(pattern)]
                )
                for window in matches:
                    if self._window_matches_role_binding(profile, role, window.title):
                        return window
                last_error = AutomationError(
                    f"Window matched {pattern}, but not the bound role."
                )
            except AutomationError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise AutomationError("視窗標題規則不可空白。")

    def _window_matches_role_binding(
        self,
        profile: dict[str, Any],
        role: str,
        title: str,
    ) -> bool:
        platforms = self.config.get("platforms", {})
        if profile not in (
            platforms.get("cTrader"),
            platforms.get("GooeyTrade"),
        ):
            return True
        role_pattern = str(profile.get("window_title", {}).get(role, "")).strip()
        if "GooeyTrade" in role_pattern:
            return "GooeyTrade" in title
        if "cTrader" in role_pattern and "GooeyTrade" not in role_pattern:
            return "GooeyTrade" not in title
        return True

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
            if ctrader_uses_point_size:
                sl_value = side.sl_points / instruction.point_size
                tp_value = side.tp_points / instruction.point_size
            else:
                sl_value = side.sl_points
                tp_value = side.tp_points
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
        self.windows.wait(0.35)
        self.windows.hotkey(
            tradingview_window,
            "alt",
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

        self._add_tradingview_price_alerts(
            tradingview_window,
            instruction,
            tp_price,
            sl_price,
        )

    def _add_tradingview_price_alerts(
        self,
        tradingview_window: WindowInfo,
        instruction: TradeInstruction,
        tp_price: Decimal,
        sl_price: Decimal,
    ) -> None:
        for label, price in (("止盈", tp_price), ("止損", sl_price)):
            self.emergency.guard()
            self.windows.hotkey(
                tradingview_window,
                "alt",
                "a",
                interval=0.08,
            )
            self.windows.wait(0.35)
            text = instruction.format_price(price)
            self.windows.paste_text(tradingview_window, text)
            self.windows.wait(0.1)
            self.windows.press(tradingview_window, "enter")
            self.windows.wait(0.35)
            self.log(f"TradingView 已新增{label}價格鬧鐘：{text}")

    def _legacy_sync_external_sl_tp(
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

    def sync_external_sl_tp(
        self,
        instruction: TradeInstruction,
        *,
        internal_platform: str,
        external_platform: str,
        entry_price_override: Decimal | None = None,
    ) -> None:
        self.emergency.guard()
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
            required = ["sl_input", "tp_input", "sl_checkbox", "tp_checkbox"]
        missing = [name for name in required if name not in points]
        if missing:
            raise AutomationError(
                f"{external_platform} missing calibration points: {', '.join(missing)}"
            )

        if _is_mt5(external_platform):
            matched_row = self._find_mt5_position_row(
                profile,
                points,
                instruction.external.lot,
                max_rows=30,
            )
            if matched_row is None:
                raise AutomationError(
                    "找不到手數符合的 MT5 場外訂單，已停止修改。"
                    f"試算表要求 {instruction.external.lot}。"
                )
            position_point = self._offset_position_point(
                points["position_order_row"],
                points["position_order_lot"],
                points["position_order_lot_next"],
                matched_row,
            )
            self.log(
                f"已找到第 {matched_row + 1} 筆手數相符的 MT5 場外訂單，"
                "正在雙擊開啟持倉修改視窗。"
            )
            self.windows.double_click(
                self._window_for_point(profile, "external", position_point),
                position_point,
            )
            self.windows.wait_for_point_window(
                profile,
                "external",
                points["position_sl_input"],
                timeout=3.0,
            )
            values = (
                ("position_sl_input", "止損點數", _plain(instruction.external.sl_points)),
                ("position_tp_input", "止盈點數", _plain(instruction.external.tp_points)),
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
            f"止損 {_plain(instruction.external.sl_points)} 點，"
            f"止盈 {_plain(instruction.external.tp_points)} 點。"
        )

    def sync_external_sl_tp(
        self,
        instruction: TradeInstruction,
        *,
        internal_platform: str,
        external_platform: str,
        entry_price_override: Decimal | None = None,
    ) -> dict[str, str] | None:
        self.emergency.guard()
        entry_price = (
            entry_price_override
            if entry_price_override is not None
            else self._read_internal_entry_price(instruction, internal_platform)
        )
        sl_price, tp_price = instruction.estimated_prices(
            instruction.external_direction,
            instruction.external,
            entry_price,
        )
        profile = self.config["platforms"][external_platform]
        points = profile.get("points", {})

        use_position_modify_flow = _uses_position_modify_flow(external_platform)
        if use_position_modify_flow:
            required = [
                "position_sl_input",
                "position_tp_input",
                "position_order_lot",
                "position_order_row",
            ]
        else:
            required = ["sl_input", "tp_input", "sl_checkbox", "tp_checkbox"]
        missing = [name for name in required if name not in points]
        if missing:
            raise AutomationError(
                f"{external_platform} missing calibration points: {', '.join(missing)}"
            )

        modify_window = None
        bound_window = None
        if use_position_modify_flow:
            if (_is_ctrader(external_platform)
                    and isinstance(self.windows, WindowController)):
                bound_window = self.windows.find_calibrated_main(
                    profile["window_title"]["external"],
                    points["position_order_row"], platform=external_platform
                )
            else:
                bound_window = self.windows.find(
                    profile["window_title"]["external"]
                )
            self.log(f"已找到場外 {external_platform} 視窗：{bound_window.title}")
            if _is_ctrader(external_platform):
                self._verify_ctrader_account(
                    external_platform, profile, "external", bound_window
                )
            if _is_mt5(external_platform):
                trade_tab = points.get("trade_tab")
                if trade_tab is not None:
                    self.log("正在切到 MT5 交易欄位。")
                    self.windows.click(bound_window, trade_tab)
                    self.windows.wait(0.2)
            lot_window = bound_window
            operation_points = points
            try:
                detected_lot = self.windows.read_number_near(
                    lot_window,
                    points["position_order_lot"],
                    instruction.external.lot,
                )
            except AutomationError:
                detected_lot = None

            if not (
                detected_lot is not None
                and _decimal_close(
                    detected_lot, instruction.external.lot, Decimal("0.001")
                )
            ):
                self.log(
                    f"{external_platform} 第一筆場外訂單手數不符合，"
                    "未開啟修改視窗；"
                    "已計算場外止盈止損價格供手動複製。"
                )
                return {
                    "entry": instruction.format_price(entry_price),
                    "sl": instruction.format_price(sl_price),
                    "tp": instruction.format_price(tp_price),
                    "expected_lot": _plain(instruction.external.lot),
                    "detected_lot": ""
                    if detected_lot is None
                    else _plain(detected_lot),
                }

            self.log(
                f"{external_platform} 第一筆場外訂單手數符合，"
                "正在開啟持倉修改視窗。"
            )
            row_window = bound_window
            self.windows.double_click(
                row_window,
                points["position_order_row"],
            )
            try:
                modify_window = self.windows.wait_for_active_window_change(
                    row_window,
                    timeout=3.0,
                )
            except AutomationError:
                self.log(
                    f"{external_platform} 修改視窗沒有自動切到最上層，"
                    "改用校準尺寸尋找並點擊輸入欄。"
                )
                modify_window = self.windows.wait_for_window_matching_point_size(
                    points["position_sl_input"],
                    timeout=3.0,
                    exclude_handles={row_window.handle},
                )
                self.windows.click(modify_window, points["position_sl_input"])
                modify_window = self.windows.active_window()
            self.log(
                f"已偵測到 {external_platform} 持倉修改視窗："
                f"{modify_window.title}"
            )
            values = (
                ("position_sl_input", "止損價格", instruction.format_price(sl_price)),
                ("position_tp_input", "止盈價格", instruction.format_price(tp_price)),
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
            operation_points = points

        for point_name, label, value in values:
            if modify_window is not None:
                self.emergency.guard()
                self.log(f"正在填入場外 {external_platform} 的{label}：{value}")
                self.windows.click_and_type(
                    modify_window,
                    operation_points[point_name],
                    value,
                )
            else:
                self._fill_field(
                    profile,
                    "external",
                    operation_points,
                    "場外",
                    external_platform,
                    point_name,
                    label,
                    value,
                )
        if use_position_modify_flow:
            self.log(
                f"場外 {external_platform} 持倉止盈止損價格已填入："
                f"止損 {instruction.format_price(sl_price)}，"
                f"止盈 {instruction.format_price(tp_price)}。"
            )
        else:
            self.log(
                f"場外 {external_platform} 止盈止損已填入："
                f"止損 {_plain(instruction.external.sl_points)} 點，"
                f"止盈 {_plain(instruction.external.tp_points)} 點。"
            )
        return None

    def _activate_mt5_trade_tab(
        self,
        profile: dict[str, Any],
        role: str,
        points: dict[str, dict[str, Any]],
    ) -> None:
        point = points.get("trade_tab")
        if point is None:
            return
        self.log("正在切到 MT5 交易欄位。")
        self._click_profile_point(profile, role, point)
        self.windows.wait(0.2)

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
                detected_lot = self.windows.read_number_near(
                    lot_window, lot_point, expected_lot
                )
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
            if _decimal_close(detected_lot, expected_lot, Decimal("0.001")):
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
            self._verify_ctrader_account(
                internal_platform, internal_profile, "internal", entry_window
            )
            trade_tab = internal_points.get("trade_tab")
            if trade_tab is None:
                raise AutomationError(
                    f"{internal_platform} 請先校準交易頁面按鈕。"
                )
            self.log(f"正在切到場內 {internal_platform} 交易頁面。")
            self.windows.click(entry_window, trade_tab)
            self.windows.wait(0.2)
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

    def _ctrader_uses_point_size(
        self,
        platform: str,
        profile: dict[str, Any],
        role: str,
        points: dict[str, dict[str, Any]],
    ) -> bool:
        if platform == "GooeyTrade":
            return True
        if platform == "cTrader" and ctrader_mode_for_profile(
            self.config, self.profile_name
        ) == "gooey":
            return True
        role_pattern = str(profile.get("window_title", {}).get(role, ""))
        return "GooeyTrade" in role_pattern

def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def _decimal_close(
    actual: Decimal,
    expected: Decimal,
    tolerance: Decimal,
) -> bool:
    return abs(actual - expected) <= tolerance


def _is_ctrader(platform: str) -> bool:
    return platform in {"GooeyTrade", "cTrader"}


def _is_mt5(platform: str) -> bool:
    return platform in {"MT5", "BYBIT MT5", "原版MT5"}


def _uses_position_modify_flow(platform: str) -> bool:
    return _is_mt5(platform) or _is_ctrader(platform)

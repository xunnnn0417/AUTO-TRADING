from __future__ import annotations

import ctypes
import re
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
SW_RESTORE = 9
GA_ROOT = 2
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
LWA_COLORKEY = 0x00000001
HWND_TOPMOST = -1
SW_SHOWNOACTIVATE = 4
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
PS_SOLID = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_LSHIFT = 0xA0
VK_LMENU = 0xA4
VK_RIGHT = 0x27


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("data", INPUTUNION),
    ]


WPARAM_T = ctypes.c_size_t
LPARAM_T = ctypes.c_ssize_t
LRESULT_T = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT_T,
    wintypes.HWND,
    wintypes.UINT,
    WPARAM_T,
    LPARAM_T,
)
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    WPARAM_T,
    LPARAM_T,
]
user32.DefWindowProcW.restype = LRESULT_T


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class AutomationError(RuntimeError):
    pass


class EmergencyStopped(AutomationError):
    pass


def _extract_decimal_candidates(texts: list[str]) -> list[Decimal]:
    ranked: list[tuple[int, Decimal]] = []
    for text in texts:
        normalized = (
            str(text)
            .replace(" ", "")
            .replace(",", "")
            .replace("O", "0")
            .replace("o", "0")
        )
        for match in re.finditer(
            r"(?<!\d)(\d{1,7}\.\d{1,6})(?!\d)", normalized
        ):
            token = match.group(1)
            try:
                value = Decimal(token)
            except InvalidOperation:
                continue
            digit_count = sum(char.isdigit() for char in token)
            ranked.append((digit_count, value))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [value for _, value in ranked]


def _alt_shift_right_events() -> list[tuple[int, int]]:
    return [
        (VK_LMENU, 0),
        (VK_LSHIFT, 0),
        (VK_RIGHT, KEYEVENTF_EXTENDEDKEY),
        (VK_RIGHT, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP),
        (VK_LSHIFT, KEYEVENTF_KEYUP),
        (VK_LMENU, KEYEVENTF_KEYUP),
    ]


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class EmergencyController:
    def __init__(self, callback: Callable[[], None]):
        self.event = threading.Event()
        self.callback = callback
        self._running = True
        self._thread = threading.Thread(target=self._poll_escape, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        first = not self.event.is_set()
        self.event.set()
        if first:
            self.callback()

    def reset(self) -> None:
        self.event.clear()

    def guard(self) -> None:
        if self.event.is_set():
            raise EmergencyStopped("緊急停止目前生效中。")

    def close(self) -> None:
        self._running = False

    def _poll_escape(self) -> None:
        was_down = False
        while self._running:
            down = bool(user32.GetAsyncKeyState(0x1B) & 0x8000)
            if down and not was_down:
                self.stop()
            was_down = down
            time.sleep(0.025)


class WindowController:
    _ocr_engine = None
    _ocr_lock = threading.Lock()

    def __init__(self, emergency: EmergencyController):
        self.emergency = emergency

    def list_windows(self) -> list[WindowInfo]:
        windows: list[WindowInfo] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(handle: int, _: int) -> bool:
            if not user32.IsWindowVisible(handle):
                return True
            length = user32.GetWindowTextLengthW(handle)
            if not length:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, length + 1)
            rect = wintypes.RECT()
            if user32.GetWindowRect(handle, ctypes.byref(rect)):
                windows.append(
                    WindowInfo(
                        handle,
                        buffer.value,
                        rect.left,
                        rect.top,
                        rect.right,
                        rect.bottom,
                    )
                )
            return True

        user32.EnumWindows(callback_type(callback), 0)
        return windows

    def find_calibrated_main(
        self, title_pattern: str, point: dict, platform: str = "cTrader"
    ) -> WindowInfo:
        """Identify one native broker MAIN HWND, never a same-title dialog.

        Shared by fill, independent SL/TP sync and Demo order submission.
        Resized main windows are identified, but saved point coordinates
        must STILL be revalidated by screen_point before any mouse action.
        This Win32 enumeration does not traverse the UIA tree.
        """
        self.emergency.guard()
        width = int(point.get("window_width", 0))
        height = int(point.get("window_height", 0))
        if width <= 0 or height <= 0:
            raise AutomationError(
                f"{platform} 缺少主視窗校準尺寸，禁止操作未知視窗。"
            )
        # MAIN identity and mouse-coordinate validity are separate facts.
        # Window size cannot identify a broker: maximize/DPI changes it,
        # and a popup might coincidentally share the old dimensions.
        # Match the native main-window title convention; reject dialogs
        # independently of Z-order or their geometry.
        main_title = (
            r"^GooeyTrade(?:\s|$)"
            if platform == "GooeyTrade"
            else r"^cTrader\s+\d+(?:\.\d+)+(?:\s*[-|].*)?$"
        )
        candidates = self.find_all(title_pattern)
        matches = [
            window for window in candidates
            if re.match(main_title, str(window.title or ""), re.IGNORECASE)
        ]
        if len(matches) != 1:
            raise AutomationError(
                f"{platform} 視窗標題符合 {len(candidates)} 個，"
                f"但可辨識的主交易視窗有 {len(matches)} 個。"
                "請確認真正主視窗可見並重新綁定；不操作。"
            )
        # Do NOT scale/guess calibrated mouse coordinates when resized.
        # screen_point() and click()/click_and_type() continue to enforce
        # exact calibrated geometry before any physical broker action.
        return matches[0]

    def find(self, title_pattern: str) -> WindowInfo:
        if not title_pattern.strip():
            raise AutomationError("視窗標題規則不可空白。")
        try:
            pattern = re.compile(title_pattern, re.IGNORECASE)
        except re.error as exc:
            raise AutomationError(f"視窗標題規則無效：{exc}") from exc
        matches = [window for window in self.list_windows() if pattern.search(window.title)]
        if not matches:
            raise AutomationError(f"找不到符合規則的可見視窗：{title_pattern}")
        return matches[0]

    def find_all(self, title_pattern: str) -> list[WindowInfo]:
        if not title_pattern.strip():
            raise AutomationError("Window title pattern is empty.")
        try:
            pattern = re.compile(title_pattern, re.IGNORECASE)
        except re.error as exc:
            raise AutomationError(f"Invalid window title pattern: {exc}") from exc
        matches = [
            window for window in self.list_windows() if pattern.search(window.title)
        ]
        if not matches:
            raise AutomationError(f"No visible window matched: {title_pattern}")
        return matches

    def try_find(self, title_pattern: str) -> WindowInfo | None:
        try:
            return self.find(title_pattern)
        except AutomationError:
            return None

    def active_window(self) -> WindowInfo:
        handle = user32.GetForegroundWindow()
        for window in self.list_windows():
            if window.handle == handle:
                return window
        raise AutomationError("無法辨識目前作用中的視窗。")

    def foreground_top_level_window(self) -> WindowInfo:
        """Visible foreground owner window, independent of mouse location.

        Used for explicit window binding only. Do not silently choose the
        first Z-order window when the foreground is unrecognised.
        """
        handle = user32.GetForegroundWindow()
        if not handle:
            raise AutomationError("目前沒有可辨識的前景視窗，請切換到交易平台再試。")
        root_handle = user32.GetAncestor(handle, GA_ROOT) or handle
        for window in self.list_windows():
            if window.handle == root_handle:
                return window
        raise AutomationError("無法辨識最前景視窗，請將交易平台切到最上層再試。")

    def window_at_cursor(self) -> WindowInfo:
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        handle = user32.WindowFromPoint(point)
        root_handle = user32.GetAncestor(handle, GA_ROOT)
        for window in self.list_windows():
            if window.handle == root_handle:
                return window
        raise AutomationError("無法辨識滑鼠游標下方的視窗。")

    def focus(self, window: WindowInfo) -> WindowInfo:
        self.emergency.guard()
        minimized=bool(user32.IsIconic(window.handle))
        # Most fill/verify operations target one already-active window.
        # Keep the exact refresh and calibration-size checks, but do not
        # wait 200ms after every field if the correct HWND is foreground.
        if not minimized and user32.GetForegroundWindow()==window.handle:
            return self._refresh(window.handle)
        if minimized:
            user32.ShowWindow(window.handle, SW_RESTORE)
        user32.SetForegroundWindow(window.handle)
        # SetForegroundWindow may succeed immediately. Poll only until the
        # desired HWND is active rather than sleeping 200ms unconditionally.
        deadline=time.monotonic()+0.22
        while user32.GetForegroundWindow()!=window.handle:
            self.emergency.guard()
            if time.monotonic()>=deadline:
                raise AutomationError(
                    "平台視窗無法取得焦點，停止填值／核對，避免操作錯誤視窗。"
                )
            time.sleep(0.015)
        return self._refresh(window.handle)

    def cursor_position(self) -> tuple[int, int]:
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def relative_point(self, window: WindowInfo, x: int, y: int) -> dict[str, float]:
        if window.width <= 0 or window.height <= 0:
            raise AutomationError("目標視窗的尺寸無效。")
        return {
            "x": round((x - window.left) / window.width, 6),
            "y": round((y - window.top) / window.height, 6),
            "x_px": x - window.left,
            "y_px": y - window.top,
            "window_width": window.width,
            "window_height": window.height,
        }

    def screen_point(self, window: WindowInfo, point: dict[str, float]) -> tuple[int, int]:
        calibrated_width = int(point.get("window_width", 0))
        calibrated_height = int(point.get("window_height", 0))
        same_size = (
            calibrated_width > 0
            and calibrated_height > 0
            and abs(window.width - calibrated_width) <= 2
            and abs(window.height - calibrated_height) <= 2
            and "x_px" in point
            and "y_px" in point
        )
        if same_size:
            x = window.left + int(point["x_px"])
            y = window.top + int(point["y_px"])
        else:
            self._raise_size_mismatch(window, point)
        return x, y

    def screen_point_for_display(
        self, window: WindowInfo, point: dict[str, float]
    ) -> tuple[int, int]:
        try:
            return self.screen_point(window, point)
        except AutomationError:
            if "x" not in point or "y" not in point:
                raise
            x = window.left + round(float(point["x"]) * window.width)
            y = window.top + round(float(point["y"]) * window.height)
            return x, y

    def read_fill_snapshot(
        self,
        window: WindowInfo,
        points: dict[str, dict[str, float]],
        *,
        ctrader: bool = False,
        _controls=None,
    ) -> dict[str, object]:
        """One FRESH UIA inventory to verify every input on the same window.

        Safe speed optimization: enumerate controls ONCE per verification
        round, not once per field / direction / checkbox. Values and toggle
        states are always fetched fresh. Never click, submit, type or reuse
        a previous round's values.
        """
        self.emergency.guard()
        from pywinauto import Desktop
        focused = self.focus(window)
        target_points = {
            name: points[name]
            for name in ("lot_input", "sl_input", "tp_input")
        }
        if ctrader:
            target_points.update({
                name: points[name] for name in (
                    "buy_button","sell_button","sl_checkbox","tp_checkbox"
                )
            })
        coords={}
        for key,point in target_points.items():
            self.emergency.guard()
            self._validate_calibrated_window(focused,point)
            coords[key]=self.screen_point(focused,point)
        try:
            # A final pre-click cTrader validation may supply its single,
            # newly captured inventory for account, instrument and form.
            controls=(
                _controls if _controls is not None
                else Desktop(backend="uia").window(
                    handle=focused.handle
                ).descendants()
            )
        except Exception as exc:
            raise AutomationError(
                f"無法一次讀取交易視窗欄位清單：{exc}"
            ) from exc
        self.emergency.guard()
        types={"Edit":[],"Spinner":[],"RadioButton":[],"CheckBox":[]}
        for ctrl in controls:
            try:
                kind=str(ctrl.element_info.control_type)
                if kind not in types:
                    continue
                if not ctrl.is_visible() or not ctrl.is_enabled():
                    continue
                box=ctrl.rectangle()
                rect=(box.left,box.top,box.right,box.bottom)
                types[kind].append((ctrl,rect))
            except Exception:
                continue

        def matching_edit(key: str):
            x,y=coords[key]
            unique={}
            for ctrl,rect in types["Edit"]+types["Spinner"]:
                a,b,c,d=rect
                if a-4<=x<=c+4 and b-4<=y<=d+4:
                    unique.setdefault(rect,ctrl)
            if len(unique)!=1:
                raise AutomationError(
                    f"{key} 沒有唯一可讀欄位（找到 {len(unique)} 個），"
                    "為安全起見不會盲目重填。"
                )
            return next(iter(unique.values()))

        values={}
        for key in ("lot_input","sl_input","tp_input"):
            self.emergency.guard()
            ctrl=matching_edit(key)
            try:
                text=str(ctrl.get_value()).strip()
            except Exception as exc:
                raise AutomationError(
                    f"{key} 不支援 UIA ValuePattern 讀回：{exc}"
                ) from exc
            if not text:
                raise AutomationError(f"{key} UIA 讀回空白，已停止。")
            values[key]=text
        result={"values":values, "direction":None, "checks":{}}
        if not ctrader:
            return result

        selected={}
        for side,key in (("BUY","buy_button"),("SELL","sell_button")):
            x,y=coords[key]
            matches=[]
            for ctrl,(l,t,r,b) in types["RadioButton"]:
                if l<=x<=r and t<=y<=b:
                    matches.append(ctrl)
            if len(matches)!=1:
                raise AutomationError(
                    f"cTrader {side} 找不到唯一方向按鈕（{len(matches)} 個）。"
                )
            try:
                selected[side]=bool(matches[0].is_selected())
            except Exception as exc:
                raise AutomationError(
                    f"cTrader {side} 方向狀態讀取失敗：{exc}"
                ) from exc
        if selected["BUY"]==selected["SELL"]:
            raise AutomationError(
                "cTrader 買賣方向沒有唯一選擇，已停止填寫。"
            )
        result["direction"]="BUY" if selected["BUY"] else "SELL"
        states={}
        for key,terms in (
            ("sl_checkbox",("stop loss","stoploss","止損","止损")),
            ("tp_checkbox",("take profit","takeprofit","止盈"))
        ):
            x,y=coords[key]
            matches=[]
            for ctrl,(l,t,r,b) in types["CheckBox"]:
                try:
                    name=(ctrl.window_text() or "").casefold().replace("-"," ")
                    if not any(term in name for term in terms):
                        continue
                    cx=(l+r)//2
                    cy=(t+b)//2
                    if abs(cx-x)<=42 and abs(cy-y)<=42:
                        matches.append(ctrl)
                except Exception:
                    continue
            if len(matches)!=1:
                raise AutomationError(
                    f"cTrader {key} 找不到唯一勾選框（{len(matches)} 個）。"
                )
            try:
                toggle=int(matches[0].get_toggle_state())
            except Exception as exc:
                raise AutomationError(
                    f"cTrader {key} 勾選狀態讀取失敗：{exc}"
                ) from exc
            if toggle not in (0,1):
                raise AutomationError(
                    f"cTrader {key} 勾選狀態不確定（{toggle}）。"
                )
            states[key]=bool(toggle)
        result["checks"]=states
        return result

    def read_edit_value(
        self,
        window: WindowInfo,
        point: dict[str, float],
    ) -> str:
        """Read a calibrated editable cell using native UIA ValuePattern.

        Do not click or use the clipboard (Ctrl+C from a misfocused window
        might copy unrelated text). Require exactly one matching UIA Edit
        or Spinner at the calibrated point. Failure is explicitly UNVERIFIED,
        never treated as a mismatch that would trigger blind rewrites.
        """
        self.emergency.guard()
        from pywinauto import Desktop

        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x,y=self.screen_point(focused,point)
        root=Desktop(backend="uia").window(handle=focused.handle)
        hits=[]
        try:
            controls=root.descendants()
        except Exception as exc:
            raise AutomationError(f"UIA 無法列舉交易欄位：{exc}") from exc
        for ctrl in controls:
            try:
                info=ctrl.element_info
                if str(info.control_type) not in ("Edit","Spinner"):
                    continue
                if not ctrl.is_visible() or not ctrl.is_enabled():
                    continue
                rect=ctrl.rectangle()
                if not (
                    rect.left-4 <= x <= rect.right+4
                    and rect.top-4 <= y <= rect.bottom+4
                ):
                    continue
                cx=(rect.left+rect.right)/2
                cy=(rect.top+rect.bottom)/2
                score=abs(cx-x)+abs(cy-y)
                hits.append((score,ctrl,(rect.left,rect.top,rect.right,rect.bottom)))
            except Exception:
                continue
        # Ignore equivalent nested Edit/Spinner geometry, but fail if
        # two DISTINCT editable controls cover the calibration point.
        by_rect={}
        for score,ctrl,rect in hits:
            if rect not in by_rect or score < by_rect[rect][0]:
                by_rect[rect]=(score,ctrl)
        if len(by_rect) != 1:
            raise AutomationError(
                "無法從校準點唯一定位可讀取的輸入欄位"
                f"（找到 {len(by_rect)} 個）。請重新校準；不會盲目重填。"
            )
        ctrl=next(iter(by_rect.values()))[1]
        try:
            value=str(ctrl.get_value()).strip()
        except Exception as exc:
            raise AutomationError(
                f"輸入欄位不支援可靠讀回（UIA ValuePattern）：{exc}。"
                "已停止，不會盲目重填。"
            ) from exc
        if not value:
            raise AutomationError("輸入欄位讀回空白，狀態不明，已停止。")
        return value

    def read_ctrader_direction(
        self,
        window: WindowInfo,
        points: dict[str, dict[str, float]],
    ) -> str:
        """Only claim BUY/SELL when exactly one of two UIA radios is selected."""
        from pywinauto import Desktop
        self.emergency.guard()
        focused=self.focus(window)
        root=Desktop(backend="uia").window(handle=focused.handle)
        try:
            radios=root.descendants(control_type="RadioButton")
        except Exception as exc:
            raise AutomationError(f"讀取 cTrader 多空方向失敗：{exc}") from exc
        selected={}
        for side,key in (("BUY","buy_button"),("SELL","sell_button")):
            if key not in points:
                raise AutomationError(f"缺少 cTrader {key} 校準")
            point=points[key]
            self._validate_calibrated_window(focused,point)
            x,y=self.screen_point(focused,point)
            hits=[]
            for radio in radios:
                try:
                    rr=radio.rectangle()
                    if (rr.left<=x<=rr.right and rr.top<=y<=rr.bottom
                            and radio.is_visible()):
                        hits.append(radio)
                except Exception:
                    continue
            if len(hits)!=1:
                raise AutomationError(
                    f"cTrader {side} 方向鈕無法唯一辨識（{len(hits)} 個），"
                    "已停止，不會把點擊視作方向確認。"
                )
            try:
                selected[side]=bool(hits[0].is_selected())
            except Exception as exc:
                raise AutomationError(f"cTrader {side} 方向狀態讀取失敗：{exc}") from exc
        if selected["BUY"] == selected["SELL"]:
            raise AutomationError("cTrader 買賣方向未呈現唯一已選狀態，已停止填寫。")
        return "BUY" if selected["BUY"] else "SELL"

    def read_ctrader_checkbox_checked(
        self, window: WindowInfo, point: dict[str,float], checkbox_key: str
    ) -> bool:
        """Read-only verified UIA checkbox status after entry values change."""
        from pywinauto import Desktop
        self.emergency.guard()
        focused=self.focus(window)
        self._validate_calibrated_window(focused,point)
        x,y=self.screen_point(focused,point)
        root=Desktop(backend="uia").window(handle=focused.handle)
        try:
            all_checks=root.descendants(control_type="CheckBox")
        except Exception as exc:
            raise AutomationError(f"cTrader {checkbox_key} 狀態讀取失敗：{exc}") from exc
        matches=[]
        for ctrl in all_checks:
            try:
                name=(ctrl.window_text() or "").casefold().replace("-"," ")
                label_match=(
                    any(t in name for t in ("stop loss","stoploss","止損","止损"))
                    if checkbox_key=="sl_checkbox"
                    else any(t in name for t in ("take profit","takeprofit","止盈"))
                )
                if not label_match:
                    continue
                rr=ctrl.rectangle()
                cx=(rr.left+rr.right)//2
                cy=(rr.top+rr.bottom)//2
                if abs(cx-x)<=42 and abs(cy-y)<=42 and ctrl.is_visible():
                    matches.append(ctrl)
            except Exception:
                continue
        if len(matches)!=1:
            raise AutomationError(
                f"cTrader {checkbox_key} 讀回找不到唯一勾選框，已停止填寫。"
            )
        try:
            state=int(matches[0].get_toggle_state())
        except Exception as exc:
            raise AutomationError(f"cTrader {checkbox_key} 勾選狀態不明：{exc}") from exc
        if state not in (0,1):
            raise AutomationError(f"cTrader {checkbox_key} 狀態不確定：{state}")
        return bool(state)

    def click_and_type(
        self,
        window: WindowInfo,
        point: dict[str, float],
        text: str,
    ) -> None:
        self.emergency.guard()
        try:
            import pyautogui
            import pyperclip
        except ImportError as exc:
            raise AutomationError(
                "尚未安裝 pyautogui，請先執行 install.bat。"
            ) from exc
        pyautogui.PAUSE = 0.08
        pyautogui.FAILSAFE = True
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        self.emergency.guard()
        pyautogui.click(x, y)
        self.emergency.guard()
        pyautogui.hotkey("ctrl", "a")
        self.emergency.guard()
        pyperclip.copy(str(text))
        pyautogui.hotkey("ctrl", "v")

    def click(self, window: WindowInfo, point: dict[str, float]) -> None:
        self.emergency.guard()
        try:
            import pyautogui
        except ImportError as exc:
            raise AutomationError("尚未安裝 pyautogui，請先執行 install.bat。") from exc
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        self.emergency.guard()
        pyautogui.click(x, y)

    def double_click(
        self,
        window: WindowInfo,
        point: dict[str, float],
    ) -> None:
        self.emergency.guard()
        try:
            import pyautogui
        except ImportError as exc:
            raise AutomationError("尚未安裝 pyautogui，請先執行 install.bat。") from exc
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        self.emergency.guard()
        pyautogui.doubleClick(x, y, interval=0.16)
        time.sleep(0.2)

    def wait(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.emergency.guard()
            time.sleep(min(0.05, deadline - time.monotonic()))

    def point_window_exists(
        self,
        profile: dict,
        role: str,
        point: dict[str, float],
    ) -> bool:
        title_pattern = str(point.get("window_title", "")).strip()
        if not title_pattern:
            title_pattern = profile["window_title"][role]
        return self.try_find(title_pattern) is not None

    def wait_for_point_window(
        self,
        profile: dict,
        role: str,
        point: dict[str, float],
        timeout: float,
    ) -> WindowInfo:
        title_pattern = str(point.get("window_title", "")).strip()
        if not title_pattern:
            title_pattern = profile["window_title"][role]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.emergency.guard()
            window = self.try_find(title_pattern)
            if window is not None:
                return window
            time.sleep(0.05)
        raise AutomationError("MT5 新訂單視窗未在期限內出現，已停止填入。")

    def wait_for_active_window_change(
        self,
        previous_window: WindowInfo,
        *,
        timeout: float,
    ) -> WindowInfo:
        deadline = time.monotonic() + timeout
        last_window = previous_window
        while time.monotonic() < deadline:
            self.emergency.guard()
            try:
                current = self.active_window()
            except AutomationError:
                time.sleep(0.05)
                continue
            last_window = current
            if current.handle != previous_window.handle:
                return current
            time.sleep(0.05)
        raise AutomationError(
            "MT5 持倉修改視窗已要求開啟，但沒有切換到新的視窗；"
            f"目前作用視窗：{last_window.title}"
        )

    def wait_for_window_matching_point_size(
        self,
        point: dict[str, float],
        *,
        timeout: float,
        exclude_handles: set[int] | None = None,
    ) -> WindowInfo:
        required = {"window_width", "window_height"}
        if not required.issubset(point):
            raise AutomationError("校準資料缺少視窗尺寸，無法用尺寸尋找修改視窗。")
        calibrated_width = int(point.get("window_width", 0))
        calibrated_height = int(point.get("window_height", 0))
        if calibrated_width <= 0 or calibrated_height <= 0:
            raise AutomationError("校準視窗尺寸無效，無法用尺寸尋找修改視窗。")

        excluded = exclude_handles or set()
        deadline = time.monotonic() + timeout
        last_titles: list[str] = []
        while time.monotonic() < deadline:
            self.emergency.guard()
            candidates = [
                window
                for window in self.list_windows()
                if window.handle not in excluded
                and abs(window.width - calibrated_width) <= 2
                and abs(window.height - calibrated_height) <= 2
            ]
            if candidates:
                return candidates[0]
            last_titles = [window.title for window in self.list_windows()[:5]]
            time.sleep(0.05)

        raise AutomationError(
            "找不到尺寸符合校準資料的修改視窗；"
            f"校準尺寸：{calibrated_width}x{calibrated_height}；"
            f"目前前幾個視窗：{', '.join(last_titles)}"
        )

    def ensure_checkbox_checked(
        self,
        window: WindowInfo,
        point: dict[str, float],
    ) -> bool:
        self.emergency.guard()
        try:
            import pyautogui
        except ImportError as exc:
            raise AutomationError("尚未安裝 pyautogui，請先執行 install.bat。") from exc
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        self.emergency.guard()
        image = pyautogui.screenshot(
            region=(max(0, x - 7), max(0, y - 7), 15, 15)
        ).convert("L")
        bright_pixels = sum(pixel >= 150 for pixel in image.getdata())
        if bright_pixels >= 5:
            return False
        pyautogui.click(x, y)
        time.sleep(0.08)
        return True

    def refresh_checkbox_checked(
        self,
        window: WindowInfo,
        point: dict[str, float],
        checkbox_key: str,
    ) -> int:
        """Restore the checked state using cTrader's REAL UIA ToggleState.

        * Unchecked -> click once, verify checked (1)
        * Checked -> click off, verify unchecked, click on, verify checked (2)

        The old "five bright pixels" test was fundamentally unreliable:
        an UNCHECKED cTrader box's white border passes that test. Use the
        unique nearby, semantically matching UIA CheckBox instead. When no
        reliable ToggleState is available, FAIL CLOSED rather than blindly
        clicking a live trading screen. Clicking the UIA control center also
        avoids a calibrated point on its bottom border.
        """
        if checkbox_key not in ("sl_checkbox", "tp_checkbox"):
            raise AutomationError(f"不支援的 cTrader 勾選框：{checkbox_key}")
        self.emergency.guard()
        try:
            import pyautogui
            from pywinauto import Desktop
        except ImportError as exc:
            raise AutomationError("cTrader 勾選狀態讀取需要 pywinauto 與 pyautogui") from exc
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        target_x, target_y = self.screen_point(focused, point)
        label = "止損" if checkbox_key == "sl_checkbox" else "止盈"

        def locate():
            self.emergency.guard()
            try:
                root = Desktop(backend="uia").window(handle=focused.handle)
                controls = root.descendants(control_type="CheckBox")
                matches = []
                for ctrl in controls:
                    name = (ctrl.window_text() or "").casefold().replace("-", " ")
                    if checkbox_key == "sl_checkbox":
                        correct = ("stop loss" in name or "stoploss" in name
                                   or "止損" in name or "止损" in name)
                    else:
                        correct = ("take profit" in name or "takeprofit" in name
                                   or "止盈" in name)
                    if not correct:
                        continue
                    rect = ctrl.rectangle()
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    # The existing calibrated point may be on the lower edge;
                    # only accept a checkbox that is spatially very close.
                    if abs(cx-target_x) > 42 or abs(cy-target_y) > 42:
                        continue
                    if not ctrl.is_enabled() or not ctrl.is_visible():
                        continue
                    matches.append((ctrl, cx, cy))
                if len(matches) != 1:
                    raise AutomationError(
                        f"cTrader {label}無法辨識唯一的勾選框（找到 {len(matches)} 個）。"
                        "已停止填寫；請打開 cTrader 下單面板並重新校準。"
                    )
                ctrl, cx, cy = matches[0]
                toggle = int(ctrl.get_toggle_state())
                if toggle not in (0, 1):
                    raise AutomationError(
                        f"cTrader {label}勾選狀態不明（{toggle}），為避免誤切換已停止。"
                    )
                return ctrl, toggle, cx, cy
            except AutomationError:
                raise
            except Exception as exc:
                raise AutomationError(
                    f"無法可靠讀取 cTrader {label}勾選狀態，已停止填寫：{exc}"
                ) from exc

        # Reuse the SAME uniquely identified UIA checkbox between the
        # two clicks. The old flow re-enumerated all UIA checkboxes before
        # and after each click (5+ slow traversals per already-checked box).
        # A fast verified toggle isn't an unverified blind double-click.
        ctrl, current, x, y = locate()

        def wait_for(expected: int) -> None:
            nonlocal ctrl, x, y
            deadline = time.monotonic() + 1.2
            while True:
                self.emergency.guard()
                try:
                    observed = int(ctrl.get_toggle_state())
                except Exception:
                    # cTrader sometimes rebuilds a checkbox after toggling.
                    # Reacquire by its semantic label and calibrated location
                    # ONLY on a stale UIA element, not on every poll.
                    fresh, observed, fx, fy = locate()
                    if abs(fx - x) > 12 or abs(fy - y) > 12:
                        raise AutomationError(
                            f"cTrader {label}勾選框切換時移位，已停止。"
                        )
                    ctrl, x, y = fresh, fx, fy
                if observed not in (0, 1):
                    raise AutomationError(
                        f"cTrader {label}勾選狀態無法確定（{observed}）。"
                    )
                if observed == expected:
                    return
                if time.monotonic() >= deadline:
                    raise AutomationError(
                        f"cTrader {label}點擊後狀態未變成"
                        f"{'勾選' if expected else '未勾選'}；"
                        "已停止後續操作，請檢查校準位置。"
                    )
                time.sleep(0.025)

        def click_to(expected: int) -> None:
            nonlocal current
            if current == expected:
                raise AutomationError(
                    f"cTrader {label}狀態在操作期間變動，已取消以防誤按。"
                )
            self.emergency.guard()
            pyautogui.click(x, y)
            wait_for(expected)
            current = expected

        if current:
            click_to(0)
            click_to(1)
            return 2
        click_to(1)
        return 1

    def hotkey(
        self,
        window: WindowInfo,
        *keys: str,
        interval: float = 0.04,
    ) -> None:
        self.emergency.guard()
        try:
            import pyautogui
        except ImportError as exc:
            raise AutomationError(
                "尚未安裝 pyautogui，請先執行 install.bat。"
            ) from exc
        self.focus(window)
        self.emergency.guard()
        if tuple(key.lower() for key in keys) == ("alt", "shift", "right"):
            self._send_alt_shift_right()
            time.sleep(0.12)
            return
        if not keys:
            return
        modifiers = keys[:-1]
        trigger = keys[-1]
        pressed: list[str] = []
        try:
            for key in modifiers:
                self.emergency.guard()
                pyautogui.keyDown(key)
                pressed.append(key)
            time.sleep(interval)
            self.emergency.guard()
            pyautogui.press(trigger)
        finally:
            for key in reversed(pressed):
                pyautogui.keyUp(key)
        time.sleep(0.12)

    def paste_text(self, window: WindowInfo, text: str) -> None:
        self.emergency.guard()
        try:
            import pyautogui
            import pyperclip
        except ImportError as exc:
            raise AutomationError(
                "撠摰? pyautogui嚗??銵?install.bat??"
            ) from exc
        self.focus(window)
        self.emergency.guard()
        pyperclip.copy(str(text))
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.08)

    def press(self, window: WindowInfo, key: str) -> None:
        self.emergency.guard()
        try:
            import pyautogui
        except ImportError as exc:
            raise AutomationError(
                "撠摰? pyautogui嚗??銵?install.bat??"
            ) from exc
        self.focus(window)
        self.emergency.guard()
        pyautogui.press(key)
        time.sleep(0.08)

    def _send_alt_shift_right(self) -> None:
        events = _alt_shift_right_events()
        inputs = (INPUT * len(events))(
            *[
                INPUT(
                    type=INPUT_KEYBOARD,
                    data=INPUTUNION(
                        ki=KEYBDINPUT(
                            wVk=virtual_key,
                            wScan=0,
                            dwFlags=flags,
                            time=0,
                            dwExtraInfo=0,
                        )
                    ),
                )
                for virtual_key, flags in events
            ]
        )
        sent = user32.SendInput(
            len(inputs),
            inputs,
            ctypes.sizeof(INPUT),
        )
        if sent != len(inputs):
            raise AutomationError(
                "Windows 未完整送出 Alt + Shift + → 快捷鍵。"
            )
        return True

    def show_marker(self, x: int, y: int, duration_ms: int = 2500) -> None:
        threading.Thread(
            target=self._show_native_marker,
            args=(x, y, duration_ms),
            daemon=True,
        ).start()

    def _show_native_marker(self, x: int, y: int, duration_ms: int) -> None:
        class_name = f"TradingHelperMarker_{threading.get_ident()}"
        def wndproc(hwnd, message, wparam, lparam):
            if message == WM_PAINT:
                paint = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
                pen = gdi32.CreatePen(PS_SOLID, 4, 0x000000FF)
                old_pen = gdi32.SelectObject(hdc, pen)
                old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
                gdi32.Ellipse(hdc, 5, 5, 47, 47)
                gdi32.MoveToEx(hdc, 26, 0, None)
                gdi32.LineTo(hdc, 26, 52)
                gdi32.MoveToEx(hdc, 0, 26, None)
                gdi32.LineTo(hdc, 52, 26)
                gdi32.SelectObject(hdc, old_brush)
                gdi32.SelectObject(hdc, old_pen)
                gdi32.DeleteObject(pen)
                user32.EndPaint(hwnd, ctypes.byref(paint))
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        wndproc_ref = WNDPROC(wndproc)
        window_class = WNDCLASS()
        window_class.lpfnWndProc = wndproc_ref
        window_class.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        window_class.lpszClassName = class_name
        window_class.hCursor = user32.LoadCursorW(None, 32512)
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom:
            return
        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class_name,
            "",
            WS_POPUP,
            x - 26,
            y - 26,
            52,
            52,
            None,
            None,
            window_class.hInstance,
            None,
        )
        if not hwnd:
            user32.UnregisterClassW(class_name, window_class.hInstance)
            return
        user32.SetLayeredWindowAttributes(hwnd, 0x00000000, 255, LWA_COLORKEY)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x - 26, y - 26, 52, 52, 0x0010)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.UpdateWindow(hwnd)
        deadline = time.monotonic() + duration_ms / 1000
        message = wintypes.MSG()
        while time.monotonic() < deadline:
            while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            time.sleep(0.01)
        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(class_name, window_class.hInstance)

    def read_number(self, window: WindowInfo, point: dict[str, float]) -> Decimal:
        self.emergency.guard()
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        attempts = [
            (x, y, 150, 70),
            (x, y + 22, 190, 100),
            (x, y + 35, 230, 125),
            (x + 35, y, 230, 95),
        ]
        last_error: AutomationError | None = None
        for target_x, target_y, width, height in attempts:
            try:
                return self._read_number_ocr(
                    target_x,
                    target_y,
                    width=width,
                    height=height,
                )
            except AutomationError as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise AutomationError(
            "無法從校準區域辨識價格。"
            "請把校準點放在成交價數字或懸浮觸發位置後重試。"
        )

    def read_account_number(self, window: WindowInfo, point: dict[str, float]) -> str:
        self.emergency.guard()
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        attempts = [
            (x, y, 190, 55),
            (x, y, 240, 70),
            (x, y, 300, 90),
        ]
        last_error: AutomationError | None = None
        for target_x, target_y, width, height in attempts:
            try:
                candidates = self._read_text_candidates_ocr(
                    target_x,
                    target_y,
                    width=width,
                    height=height,
                )
            except AutomationError as exc:
                last_error = exc
                continue
            digit_runs: list[str] = []
            for candidate in candidates:
                digit_runs.extend(re.findall(r"\d{3,}", candidate.replace(" ", "")))
            if digit_runs:
                return max(digit_runs, key=len)
        if last_error:
            raise last_error
        raise AutomationError("無法從校準區域辨識帳號數字。")

    def read_number_near(
        self,
        window: WindowInfo,
        point: dict[str, float],
        expected: Decimal,
    ) -> Decimal:
        self.emergency.guard()
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        attempts = [
            (x, y, 120, 55),
            (x, y, 150, 70),
            (x, y + 12, 160, 75),
        ]
        last_error: AutomationError | None = None
        for target_x, target_y, width, height in attempts:
            try:
                candidates = self._read_number_candidates_ocr(
                    target_x,
                    target_y,
                    width=width,
                    height=height,
                )
            except AutomationError as exc:
                last_error = exc
                continue
            if candidates:
                return min(candidates, key=lambda value: abs(value - expected))
        if last_error is not None:
            raise last_error
        raise AutomationError("Could not read a number near the expected value.")

    def read_hover_number(
        self, window: WindowInfo, point: dict[str, float]
    ) -> Decimal:
        self.emergency.guard()
        try:
            import pyautogui
        except ImportError as exc:
            raise AutomationError(
                "尚未安裝 pyautogui，請先執行 install.bat。"
            ) from exc
        focused = self.focus(window)
        self._validate_calibrated_window(focused, point)
        x, y = self.screen_point(focused, point)
        pyautogui.moveTo(x, y, duration=0.08)
        time.sleep(0.55)
        self.emergency.guard()
        return self._read_number_ocr(x, y + 35, width=190, height=110)

    def warm_ocr(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            with WindowController._ocr_lock:
                if WindowController._ocr_engine is None:
                    WindowController._ocr_engine = RapidOCR()
        except Exception:
            return

    def _read_number_ocr(
        self,
        x: int,
        y: int,
        *,
        width: int = 150,
        height: int = 70,
    ) -> Decimal:
        return self._read_number_candidates_ocr(
            x,
            y,
            width=width,
            height=height,
        )[0]

    def _read_number_candidates_ocr(
        self,
        x: int,
        y: int,
        *,
        width: int = 150,
        height: int = 70,
    ) -> list[Decimal]:
        try:
            import cv2
            import numpy as np
            import pyautogui
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise AutomationError(
                "尚未安裝 OCR 套件，請重新執行 install.bat。"
            ) from exc

        self.emergency.guard()
        left = max(0, x - width // 2)
        top = max(0, y - height // 2)
        image = pyautogui.screenshot(region=(left, top, width, height))
        frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        frame = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        variants = [
            frame,
            cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            cv2.cvtColor(
                cv2.threshold(
                    gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )[1],
                cv2.COLOR_GRAY2BGR,
            ),
        ]
        with WindowController._ocr_lock:
            if WindowController._ocr_engine is None:
                WindowController._ocr_engine = RapidOCR()
            for variant in variants:
                self.emergency.guard()
                result, _ = WindowController._ocr_engine(variant)
                candidates = (
                    [str(item[1]) for item in result] if result else []
                )
                parsed = _extract_decimal_candidates(candidates)
                if parsed:
                    return parsed
        raise AutomationError(
            "無法從校準區域辨識價格。"
            "請把校準點放在成交價數字或懸浮觸發位置後重試。"
        )

    def _read_text_candidates_ocr(
        self,
        x: int,
        y: int,
        *,
        width: int = 150,
        height: int = 70,
    ) -> list[str]:
        try:
            import cv2
            import numpy as np
            import pyautogui
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise AutomationError(
                "尚未安裝 OCR 套件，請重新執行 install.bat。"
            ) from exc

        self.emergency.guard()
        left = max(0, x - width // 2)
        top = max(0, y - height // 2)
        image = pyautogui.screenshot(region=(left, top, width, height))
        frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        frame = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        variants = [
            frame,
            cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            cv2.cvtColor(
                cv2.threshold(
                    gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )[1],
                cv2.COLOR_GRAY2BGR,
            ),
        ]
        candidates: list[str] = []
        with WindowController._ocr_lock:
            if WindowController._ocr_engine is None:
                WindowController._ocr_engine = RapidOCR()
            for variant in variants:
                self.emergency.guard()
                result, _ = WindowController._ocr_engine(variant)
                if result:
                    candidates.extend(str(item[1]) for item in result)
        if candidates:
            return candidates
        raise AutomationError("無法從校準區域辨識文字。")

    def _read_number_legacy(self, x: int, y: int) -> Decimal:
        candidates: list[str] = []

        try:
            from pywinauto import Desktop

            element = Desktop(backend="uia").from_point(x, y)
            candidates.extend(
                [
                    element.window_text(),
                    str(element.element_info.name or ""),
                    str(getattr(element.element_info, "rich_text", "") or ""),
                ]
            )
            try:
                candidates.append(str(element.get_value()))
            except Exception:
                pass
        except Exception:
            pass

        try:
            import pyautogui
            import pyperclip

            self.emergency.guard()
            pyperclip.copy("")
            pyautogui.click(x, y)
            self.emergency.guard()
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.15)
            candidates.append(pyperclip.paste())
        except Exception:
            pass

        for candidate in candidates:
            match = re.search(r"(?<!\d)(\d[\d,]*\.?\d*)", str(candidate))
            if not match:
                continue
            try:
                return Decimal(match.group(1).replace(",", ""))
            except InvalidOperation:
                continue
        raise AutomationError(
            "無法讀取目前價格。請重新校準 MT5 的目前價格顯示位置。"
        )

    def _validate_calibrated_window(
        self, window: WindowInfo, point: dict[str, float]
    ) -> None:
        required = {"x_px", "y_px", "window_width", "window_height"}
        if not required.issubset(point):
            raise AutomationError(
                "這個欄位使用舊版校準資料。請在目前視窗配置下重新校準。"
            )
        calibrated_width = int(point.get("window_width", 0))
        calibrated_height = int(point.get("window_height", 0))
        if (
            abs(window.width - calibrated_width) > 2
            or abs(window.height - calibrated_height) > 2
        ):
            self._raise_size_mismatch(window, point)

    def _raise_size_mismatch(
        self, window: WindowInfo, point: dict[str, float]
    ) -> None:
        calibrated_width = int(point.get("window_width", 0))
        calibrated_height = int(point.get("window_height", 0))
        raise AutomationError(
            "平台視窗尺寸和校準時不同，為避免點錯位置已停止操作。"
            f"校準尺寸：{calibrated_width}×{calibrated_height}，"
            f"目前尺寸：{window.width}×{window.height}。請重新校準。"
        )

    def _refresh(self, handle: int) -> WindowInfo:
        for window in self.list_windows():
            if window.handle == handle:
                return window
        raise AutomationError("自動操作期間目標視窗已關閉。")
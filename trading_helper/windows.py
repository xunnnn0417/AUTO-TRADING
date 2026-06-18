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
        if user32.IsIconic(window.handle):
            user32.ShowWindow(window.handle, SW_RESTORE)
        user32.SetForegroundWindow(window.handle)
        time.sleep(0.2)
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
    ) -> int:
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
            pyautogui.click(x, y)
            time.sleep(0.08)
            self.emergency.guard()
            pyautogui.click(x, y)
            time.sleep(0.08)
            return 2
        pyautogui.click(x, y)
        time.sleep(0.08)
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

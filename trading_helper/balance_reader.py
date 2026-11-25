"""Read the 場內 account's actual Balance. Read-only: never clicks or trades.

MT5: the official read-only MetaTrader5 connection (the same one that
confirms fills after entry) - account_info().balance, after checking the
login/server match the bound window.

cTrader: the balance shown in the top-right account selector is exposed to
UI Automation (exact, no calibration). Fallback: the window is captured with
PrintWindow (works while covered), the 「Balance」 caption of the bottom
account strip is found by OCR and the number under it is read; two image
variants must agree.
"""
from __future__ import annotations

import re
import threading
from decimal import Decimal, InvalidOperation

from .windows import AutomationError

_OCR = None
_OCR_LOCK = threading.Lock()


def parse_balance_text(text: str) -> Decimal | None:
    """'$ 5 002 318.58', '5,002,318.58', OCR's 'C5.002318.58' -> 5002318.58."""
    raw = str(text or "").strip()
    raw = re.sub(r"^[^\d-]+", "", raw)          # currency sign / misread prefix
    raw = re.sub(r"[^\d.,\s-]", "", raw).strip()
    if not raw or not any(ch.isdigit() for ch in raw):
        return None
    negative = raw.startswith("-")
    digits = raw.lstrip("-")
    match = re.search(r"[.,](\d{2})$", digits)
    if match:
        whole = re.sub(r"[^\d]", "", digits[:match.start()])
        number = f"{whole or '0'}.{match.group(1)}"
    else:
        number = re.sub(r"[^\d]", "", digits)
    try:
        value = Decimal(number)
    except InvalidOperation:
        return None
    return -value if negative else value


def capture_window(handle: int):
    """BGR image of a window's full area, even when other windows cover it."""
    import ctypes
    from ctypes import wintypes
    import numpy as np
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    if user32.IsIconic(handle):
        raise AutomationError("cTrader 目前是最小化，畫面讀不到；請先把 cTrader 視窗打開。")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise AutomationError("讀不到 cTrader 視窗位置。")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise AutomationError("cTrader 視窗目前沒有顯示（可能最小化），請先打開它。")
    window_dc = user32.GetWindowDC(handle)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(handle, memory_dc, 2):  # PW_RENDERFULLCONTENT
            raise AutomationError("無法擷取 cTrader 畫面。")

        class Header(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
                        ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                        ("image_size", wintypes.DWORD), ("x_ppm", wintypes.LONG), ("y_ppm", wintypes.LONG),
                        ("used", wintypes.DWORD), ("important", wintypes.DWORD)]
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        image = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(handle, window_dc)
    return image


def _ocr(image):
    global _OCR
    from rapidocr_onnxruntime import RapidOCR
    with _OCR_LOCK:
        if _OCR is None:
            _OCR = RapidOCR()
        result, _ = _OCR(image)
    return result or []


CTRADER_ACCOUNT_DETAILS_ID = "CTraderAccountDetailsTextBlock_AId"


def ctrader_header_balance(handle: int) -> Decimal | None:
    """Balance in cTrader's top-right account selector, e.g.
    '$ 5 002 318.58 • 1:1000'. Exposed to UI Automation: exact and fast."""
    from .windows import _native_names_by_automation_id
    try:
        names = _native_names_by_automation_id(handle, CTRADER_ACCOUNT_DETAILS_ID)
    except Exception:
        return None
    if len(names) != 1:
        return None
    return parse_balance_text(names[0].replace(" ", " ").split("•", 1)[0])


def ocr_bottom_balance(image, *, ocr=_ocr) -> Decimal | None:
    """Find the 「Balance」 caption in the account strip and read the number
    right under it (no calibration). Two image variants must agree."""
    import cv2
    height = image.shape[0]
    top = int(height * 0.8)
    strip = image[top:, :]
    scale = 2
    big = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    otsu = cv2.cvtColor(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], cv2.COLOR_GRAY2BGR)
    readings = []
    for variant in (big, otsu):
        items = []
        for box, text, score in ocr(variant):
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            items.append((str(text), float(score), min(xs), max(xs), min(ys), max(ys)))
        labels = [i for i in items if re.fullmatch(r"\s*balance\s*", i[0], re.I)]
        if len(labels) != 1:
            continue
        _t, _s, lx0, lx1, _ly0, ly1 = labels[0]
        below = []
        for text, score, x0, x1, y0, _y1 in items:
            value = parse_balance_text(text)
            if value is None or score < 0.6 or y0 < ly1 - 2 or y0 > ly1 + 40 * scale:
                continue
            if x1 < lx0 - 60 * scale or x0 > lx1 + 60 * scale:
                continue
            below.append((y0 - ly1, abs((x0 + x1) / 2 - (lx0 + lx1) / 2), value))
        if below:
            readings.append(min(below)[2])
    if len(readings) == 2 and readings[0] == readings[1]:
        return readings[0]
    return None


def read_ctrader_balance(window, point=None, *, capture=capture_window, ocr=_ocr,
                         header=ctrader_header_balance) -> Decimal:
    """cTrader Balance without calibration: the account header first; if it
    cannot be read, the 「Balance」 cell of the bottom strip found by OCR."""
    value = header(window.handle)
    if value is not None:
        return value
    try:
        image = capture(window.handle)
    except AutomationError as exc:
        raise AutomationError("cTrader 右上帳戶列讀不到餘額，" + str(exc)) from exc
    value = ocr_bottom_balance(image, ocr=ocr)
    if value is None:
        raise AutomationError("cTrader 右上帳戶列和底部 Balance 都讀不到餘額；"
                              "請確認 cTrader 視窗有打開、底部 Balance 列有顯示。")
    return value


def read_mt5_balance(expected, *, terminal_path, sdk=None) -> Decimal:
    """Balance from the official read-only MT5 connection (exact value)."""
    from .mt5_native_readonly import MT5_LOCK
    with MT5_LOCK:
        return _read_mt5_balance(expected, terminal_path=terminal_path, sdk=sdk)


def _read_mt5_balance(expected, *, terminal_path, sdk=None) -> Decimal:
    from .mt5_native_readonly import _sdk
    if not (expected.verified and expected.account_id.isdigit() and expected.server):
        raise AutomationError("MT5 唯讀前無法確認目標帳戶。")
    mt = sdk if sdk is not None else _sdk()
    if not terminal_path.is_file():
        raise AutomationError("MT5 終端執行檔不存在，沒有讀取餘額。")
    if not mt.initialize(path=str(terminal_path), timeout=5500):
        raise AutomationError("MT5 唯讀連線失敗，沒有讀取餘額。")
    try:
        account = mt.account_info()
        if (account is None or str(account.login) != expected.account_id
                or str(account.server).casefold() != expected.server.casefold()):
            raise AutomationError("MT5 唯讀帳戶或伺服器與已綁定的場內視窗不符，沒有讀取餘額。")
        return Decimal(str(account.balance))
    finally:
        try:
            mt.shutdown()
        except Exception:
            pass

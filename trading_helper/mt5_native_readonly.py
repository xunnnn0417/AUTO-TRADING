"""Read-only native MT5 position source for one verified terminal.

NEVER invokes order_send/order_check or any broker write operation.
Unverified identity, pending orders or read failures are not empty positions.
"""
from __future__ import annotations
import ctypes
from decimal import Decimal,InvalidOperation
from pathlib import Path
from ctypes import wintypes
import importlib,sys
import time
from .auto_entry import DemoAccount,Position
from .windows import AutomationError

_VENDOR=Path(__file__).resolve().parents[1]/"vendor"/"mt5_readonly"
_TERMINAL=Path(r"C:\Program Files\RL Crates MT5 Terminal\terminal64.exe")


class MarketOrderInProgress(AutomationError):
    """The terminal still has a market request; never infer an empty account."""

def _sdk():
    from .self_update import installed_python
    selected=installed_python(Path(__file__).resolve().parents[1])
    vendor=selected.parent.parent/"mt5_readonly" if selected else _VENDOR
    if not (vendor/"MetaTrader5").is_dir():
        raise AutomationError("MT5 唯讀套件未安裝在 LAB，禁止假設空倉。")
    if str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    try:return importlib.import_module("MetaTrader5")
    except Exception as exc:
        raise AutomationError("MT5 唯讀套件載入失敗。") from exc

def _positive(value,field):
    try: num=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise AutomationError(f"MT5 {field} 無法辨識。") from exc
    if not num.is_finite() or num<=0:
        raise AutomationError(f"MT5 {field} 不是有效正數。")
    return num

def _display_text(value, fallback="未知", limit=48):
    if value is None:
        return fallback
    text=str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:limit] or fallback

def _display_number(value):
    if value is None:
        return "未知"
    try:
        number=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):
        return _display_text(value)
    if not number.is_finite():
        return _display_text(value)
    return format(number.normalize(),"f")

def _active_order_type_name(mt, value):
    labels=(
        ("ORDER_TYPE_BUY",0,"市價買入委託"),
        ("ORDER_TYPE_SELL",1,"市價賣出委託"),
        ("ORDER_TYPE_BUY_LIMIT",2,"買入限價委託"),
        ("ORDER_TYPE_SELL_LIMIT",3,"賣出限價委託"),
        ("ORDER_TYPE_BUY_STOP",4,"買入停損委託"),
        ("ORDER_TYPE_SELL_STOP",5,"賣出停損委託"),
        ("ORDER_TYPE_BUY_STOP_LIMIT",6,"買入停損限價委託"),
        ("ORDER_TYPE_SELL_STOP_LIMIT",7,"賣出停損限價委託"),
        ("ORDER_TYPE_CLOSE_BY",8,"反向平倉委託"),
    )
    for constant, fallback, label in labels:
        if value == getattr(mt, constant, fallback):
            return label
    return f"未知類型（{_display_text(value)}）"


def terminal_path_for_window(window) -> Path:
    """Resolve the exact executable behind a bound MT5 HWND, read-only."""
    from .ui_inspector import process_id_for_window

    pid = process_id_for_window(int(getattr(window, "handle", 0) or 0))
    if pid <= 0:
        raise AutomationError("無法確認已綁定 MT5 視窗的程序。")
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    process = kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        raise AutomationError("無法唯讀查詢已綁定 MT5 終端路徑。")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(length)
        ):
            raise AutomationError("無法唯讀查詢已綁定 MT5 終端路徑。")
        path = Path(buffer.value)
    finally:
        kernel32.CloseHandle(process)
    if path.name.casefold() != "terminal64.exe":
        raise AutomationError(
            "已綁定視窗不是可確認的 MT5 terminal64.exe，未讀取其他終端。"
        )
    return path

def _describe_active_order(order, mt):
    ticket=_display_text(getattr(order,"ticket",None))
    symbol=_display_text(getattr(order,"symbol",None))
    order_type=_active_order_type_name(mt,getattr(order,"type",None))
    volume=getattr(order,"volume_current",None)
    if volume is None:
        volume=getattr(order,"volume_initial",None)
    price=getattr(order,"price_open",None)
    return (
        f"{symbol}｜{order_type}｜單號 {ticket}｜"
        f"{_display_number(volume)} 手｜價格 {_display_number(price)}"
        f"｜狀態 {_display_text(getattr(order,'state',None))}"
        f"｜持倉 {_display_text(getattr(order,'position_id',None))}"
    )

def _last_error_text(mt):
    try:
        error=mt.last_error()
    except Exception:
        return ""
    if error is None:
        return ""
    return f"（MT5 回報：{_display_text(error, limit=120)}）"

def snapshot_mt5_demo(
    expected: DemoAccount, *, terminal_path: Path = _TERMINAL, sdk=None,
    allow_pending_orders: bool = False,
) -> tuple[Position, ...]:
    """Legacy alias; account type is not used to authorize read-only access."""
    return snapshot_mt5_account(
        expected,
        terminal_path=terminal_path,
        sdk=sdk,
        allow_pending_orders=allow_pending_orders,
    )


def snapshot_mt5_account(
    expected: DemoAccount, *, terminal_path: Path, sdk=None,
    allow_pending_orders: bool = False,
) -> tuple[Position, ...]:
    """Read native positions, keeping pending orders fail-closed by default.

    ``allow_pending_orders`` is only for post-submit fill confirmation: it lets
    the caller keep reading positions during the existing 15-second window.
    A pending order is never treated as a fill or rejection, and normal
    preflight snapshots continue to reject it.
    """
    if not(
        expected.verified
        and expected.platform.upper().endswith("MT5")
        and expected.account_id.isdigit()
        and expected.server
    ):
        raise AutomationError("MT5 唯讀前無法確認目標帳戶。")
    mt=sdk if sdk is not None else _sdk()
    if not terminal_path.is_file():
        raise AutomationError("MT5 終端執行檔不存在，未讀取任何持倉。")
    if not mt.initialize(path=str(terminal_path),timeout=5500):
        raise AutomationError("MT5 唯讀終端無法連線；不可判定空倉。")
    try:
        def verify_account():
            acc=mt.account_info()
            if (acc is None
                or str(acc.login)!=expected.account_id
                or str(acc.server).casefold()!=expected.server.casefold()):
                raise AutomationError(
                    "MT5 唯讀帳戶或伺服器與已綁定平台不符。"
                )
        verify_account()
        positions=mt.positions_get()
        positions_error=_last_error_text(mt) if positions is None else ""
        pendings=mt.orders_get()
        orders_error=_last_error_text(mt) if pendings is None else ""
        verify_account()
        # orders_get includes market requests during execution/closing, not
        # just parked limit/stop orders. Wait READ-ONLY for a fresh settled
        # snapshot; never drop an order or invent an empty position list.
        for _attempt in range(8):
            if (allow_pending_orders or not pendings or
                any(getattr(order,"type",None) not in (
                    getattr(mt,"ORDER_TYPE_BUY",0),
                    getattr(mt,"ORDER_TYPE_SELL",1),
                ) for order in pendings)):
                break
            time.sleep(0.15)
            verify_account()
            positions=mt.positions_get()
            positions_error=_last_error_text(mt) if positions is None else ""
            pendings=mt.orders_get()
            orders_error=_last_error_text(mt) if pendings is None else ""
            verify_account()
        if positions is None:
            raise AutomationError(
                "MT5 持倉讀取失敗，無法確認是否已有成交持倉。"
                + positions_error
            )
        if pendings is None:
            raise AutomationError(
                "MT5 有效委託清單讀取失敗，無法確認是否有未成交委託。"
                + orders_error
            )
        if len(pendings) > 0 and not allow_pending_orders:
            details=[_describe_active_order(order,mt) for order in pendings[:5]]
            if len(pendings)>len(details):
                details.append(f"另有 {len(pendings)-len(details)} 筆未展開")
            error_class=(MarketOrderInProgress if all(
                getattr(order,"type",None) in (
                    getattr(mt,"ORDER_TYPE_BUY",0),getattr(mt,"ORDER_TYPE_SELL",1)
                ) for order in pendings) else AutomationError)
            raise error_class(
                f"MT5 唯讀 API 回報 {len(pendings)} 筆仍有效委託"
                "（查詢全部商品，這不是已成交持倉）；為避免重複送單，"
                "已停止：\n- " + "\n- ".join(details)
                + "\n請在 MT5「交易」分頁用單號核對。若畫面找不到相同單號，"
                "請回傳這段明細；代表程式讀值與畫面不一致。"
            )
        items=[]
        seen=set()
        for p in positions:
            ticket=str(p.ticket)
            if not ticket.isdigit() or int(ticket)<=0 or ticket in seen:
                raise AutomationError("MT5 唯讀持倉訂單編號重複或不可靠。")
            seen.add(ticket)
            if p.type==mt.POSITION_TYPE_BUY: direction="BUY"
            elif p.type==mt.POSITION_TYPE_SELL: direction="SELL"
            else:raise AutomationError("MT5 唯讀持倉方向無法辨識。")
            sl=Decimal(str(p.sl)) if float(p.sl)>0 else None
            tp=Decimal(str(p.tp)) if float(p.tp)>0 else None
            for level in (sl,tp):
                if level is not None and(not level.is_finite() or level<=0):
                    raise AutomationError("MT5 唯讀持倉止盈止損無效。")
            items.append(Position(
                ticket,expected.account_id,"MT5",str(p.symbol),direction,
                _positive(p.volume,"手數"),_positive(p.price_open,"成交價"),
                sl,tp,
            ))
        return tuple(items)
    finally:
        mt.shutdown()

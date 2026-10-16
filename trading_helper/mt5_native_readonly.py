"""Read-only native MT5 position source for the running Demo terminal.

NEVER invokes order_send/order_check or any broker write operation.
Unverified identity, pending orders or read failures are not empty positions.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
from pathlib import Path
import importlib,sys
from .auto_entry import DemoAccount,Position
from .windows import AutomationError

_VENDOR=Path(__file__).resolve().parents[1]/"vendor"/"mt5_readonly"
_TERMINAL=Path(r"C:\Program Files\RL Crates MT5 Terminal\terminal64.exe")

def _sdk():
    if not (_VENDOR/"MetaTrader5").is_dir():
        raise AutomationError("MT5 唯讀套件未安裝在 LAB，禁止假設空倉。")
    if str(_VENDOR) not in sys.path:sys.path.insert(0,str(_VENDOR))
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

def snapshot_mt5_demo(expected:DemoAccount,*,terminal_path:Path=_TERMINAL,sdk=None)->tuple[Position,...]:
    """Check account before and after querying native open positions."""
    if not(expected.verified and expected.is_demo and
           expected.platform=="MT5" and expected.account_id.isdigit()
           and expected.server):
        raise AutomationError("MT5 唯讀前無法確認目標 Demo 帳戶。")
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
                or str(acc.server).casefold()!=expected.server.casefold()
                or int(acc.trade_mode)!=int(mt.ACCOUNT_TRADE_MODE_DEMO)
                or "demo" not in str(acc.server).casefold()):
                raise AutomationError(
                    "MT5 唯讀帳戶、伺服器或 Demo 身分與已綁定平台不符。"
                )
        verify_account()
        positions=mt.positions_get()
        pendings=mt.orders_get()
        verify_account()
        if positions is None or pendings is None:
            raise AutomationError("MT5 唯讀持倉／掛單資訊不可辨識。")
        if len(pendings)>0:
            raise AutomationError("MT5 Demo 存在待成交掛單，拒絕自動進場／補單。")
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

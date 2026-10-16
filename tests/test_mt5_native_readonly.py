"""MT5 SDK position extraction: pure fake API, no network or broker clicks."""
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from decimal import Decimal
from unittest.mock import MagicMock,patch

from trading_helper.auto_entry import DemoAccount
from trading_helper.mt5_native_readonly import snapshot_mt5_demo
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError

ACCOUNT=DemoAccount("MT5","55512345","ICMarketsSC-Demo",True,True)
class FakeNative:
    ACCOUNT_TRADE_MODE_DEMO=0
    POSITION_TYPE_BUY=0
    POSITION_TYPE_SELL=1
    def __init__(self):
        self.events=[]
        self.account=N(login=55512345,server="ICMarketsSC-Demo",trade_mode=0)
        self.positions=(N(
            ticket=8765432101,symbol="XAUUSD",type=0,volume=0.16,
            price_open=4169.30,sl=4135.57,tp=4174.62
        ),)
        self.orders=()
        self.ok=True
    def initialize(self,**kw):
        self.events.append("initialize")
        return self.ok
    def account_info(self):
        self.events.append("account")
        return self.account
    def positions_get(self):
        self.events.append("positions")
        return self.positions
    def orders_get(self):
        self.events.append("orders")
        return self.orders
    def shutdown(self):self.events.append("shutdown")

class NativeReadOnlyPositionTests(unittest.TestCase):
    def setUp(self):
        self.sdk=FakeNative()
        self.path=Path("C:/Program Files/RL Crates MT5 Terminal/terminal64.exe")
    def snapshot(self):
        with patch("pathlib.Path.is_file",return_value=True):
            return snapshot_mt5_demo(ACCOUNT,terminal_path=self.path,sdk=self.sdk)
    def test_existing_realistic_demo_buy_position(self):
        ps=self.snapshot()
        self.assertEqual(len(ps),1)
        self.assertEqual((ps[0].direction,ps[0].symbol),("BUY","XAUUSD"))
        self.assertEqual(ps[0].volume,Decimal("0.16"))
        self.assertEqual(ps[0].sl,Decimal("4135.57"))
        self.assertEqual(ps[0].tp,Decimal("4174.62"))
        self.assertEqual(self.sdk.events,
                         ["initialize","account","positions","orders","account","shutdown"])
    def test_genuinely_empty_native_terminal(self):
        self.sdk.positions=()
        self.assertEqual(self.snapshot(),())
    def test_wrong_account_and_server_fail_closed(self):
        for kwargs in ({"login":1234567},{"server":"Some-Other-Demo"},
                       {"trade_mode":1}):
            with self.subTest(kwargs=kwargs):
                original=self.sdk.account
                self.sdk.account=N(**{**vars(original),**kwargs})
                with self.assertRaisesRegex(AutomationError,"身分|不符"):
                    self.snapshot()
                self.assertEqual(self.sdk.events[-1],"shutdown")
                self.sdk.account=original
    def test_unknown_positions_never_empty(self):
        self.sdk.positions=None
        with self.assertRaises(AutomationError):
            self.snapshot()
    def test_any_unfilled_pending_order_blocks_auto_trade(self):
        self.sdk.orders=(N(ticket=123),)
        with self.assertRaisesRegex(AutomationError,"掛單"):
            self.snapshot()
    def test_duplicate_native_ticket_rejected(self):
        self.sdk.positions=self.sdk.positions*2
        with self.assertRaisesRegex(AutomationError,"重複"):
            self.snapshot()
    def test_zero_negative_nan_lot_rejected(self):
        for vol in (0,-1,"nan"):
            with self.subTest(vol=vol):
                original=self.sdk.positions[0]
                self.sdk.positions=(N(**{**vars(original),"volume":vol}),)
                with self.assertRaises(AutomationError):
                    self.snapshot()
    def test_native_initialize_failure_not_empty(self):
        self.sdk.ok=False
        with self.assertRaisesRegex(AutomationError,"無法連線"):
            self.snapshot()
    def test_port_snapshot_mt5_uses_native_not_blank_uia(self):
        port=DemoUiBrokerPort(MagicMock(),lambda m:None)
        port.inspect_account=lambda platform,role:ACCOUNT
        with patch("trading_helper.mt5_native_readonly.snapshot_mt5_demo",return_value=self.snapshot()) as read:
            port._mt5_positions=MagicMock(side_effect=AssertionError("old ownerdraw must not run"))
            self.assertEqual(len(port.snapshot_positions("MT5","external")),1)
            read.assert_called_once_with(ACCOUNT)
            port._mt5_positions.assert_not_called()

if __name__=="__main__":unittest.main()

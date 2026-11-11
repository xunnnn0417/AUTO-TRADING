"""MT5 SDK position extraction: pure fake API, no network or broker clicks."""
import unittest
from pathlib import Path
from types import SimpleNamespace,SimpleNamespace as N
from decimal import Decimal
from unittest.mock import MagicMock,patch

from trading_helper.auto_entry import DemoAccount
from trading_helper.mt5_native_readonly import (
    snapshot_mt5_account,snapshot_mt5_demo,
)
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError

ACCOUNT=DemoAccount("MT5","11111111","Example-Demo",True,True)
class FakeNative:
    ACCOUNT_TRADE_MODE_DEMO=0
    ACCOUNT_TRADE_MODE_REAL=2
    POSITION_TYPE_BUY=0
    POSITION_TYPE_SELL=1
    ORDER_TYPE_BUY=0
    ORDER_TYPE_SELL=1
    ORDER_TYPE_BUY_LIMIT=2
    ORDER_TYPE_SELL_LIMIT=3
    ORDER_TYPE_BUY_STOP=4
    ORDER_TYPE_SELL_STOP=5
    ORDER_TYPE_BUY_STOP_LIMIT=6
    ORDER_TYPE_SELL_STOP_LIMIT=7
    ORDER_TYPE_CLOSE_BY=8
    def __init__(self):
        self.events=[]
        self.account=N(login=11111111,server="Example-Demo",trade_mode=0)
        self.positions=(N(
            ticket=11111111,symbol="XAUUSD",type=0,volume=0.01,
            price_open=100.0,sl=99.0,tp=101.0
        ),)
        self.orders=()
        self.api_error=(-1,"No error")
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
    def last_error(self):return self.api_error
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
        self.assertEqual(ps[0].volume,Decimal("0.01"))
        self.assertEqual(ps[0].sl,Decimal("99.0"))
        self.assertEqual(ps[0].tp,Decimal("101.0"))
        self.assertEqual(self.sdk.events,
                         ["initialize","account","positions","orders","account","shutdown"])
    def test_verified_live_account_uses_exact_login_server_and_real_mode(self):
        live=DemoAccount("BYBIT MT5","22222222","Bybit-Live",False,True)
        self.sdk.account=N(login=22222222,server="Bybit-Live",trade_mode=2)
        with patch("pathlib.Path.is_file",return_value=True):
            positions=snapshot_mt5_account(
                live,terminal_path=self.path,sdk=self.sdk
            )
        self.assertEqual(len(positions),1)
        self.assertEqual(positions[0].account_id,"22222222")
        with self.assertRaisesRegex(AutomationError,"拒絕連接 Live"):
            snapshot_mt5_demo(live,terminal_path=self.path,sdk=self.sdk)
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
        self.sdk.orders=(N(
            ticket=123,symbol="ETHUSD",type=self.sdk.ORDER_TYPE_BUY_LIMIT,
            volume_current=0.1,price_open=3500.5,
        ),)
        with self.assertRaises(AutomationError) as raised:
            self.snapshot()
        message=str(raised.exception)
        for detail in (
            "ETHUSD","買入限價委託","單號 123","0.1 手","3500.5",
            "查詢全部商品","不是已成交持倉","MT5「交易」分頁",
        ):
            self.assertIn(detail,message)
    def test_unreadable_orders_are_reported_as_read_failure(self):
        self.sdk.orders=None
        self.sdk.api_error=(-10004,"IPC timeout")
        with self.assertRaises(AutomationError) as raised:
            self.snapshot()
        message=str(raised.exception)
        self.assertIn("有效委託清單讀取失敗",message)
        self.assertIn("IPC timeout",message)
        self.assertNotIn("回報 1 筆",message)
    def test_pending_order_does_not_block_post_submit_position_readback(self):
        self.sdk.orders=(N(ticket=123),)
        ps=snapshot_mt5_demo(
            ACCOUNT,terminal_path=self.path,sdk=self.sdk,
            allow_pending_orders=True,
        )
        self.assertEqual(len(ps),1)
        self.assertEqual(ps[0].ticket,"11111111")
    def test_fill_confirmation_keeps_polling_through_pending_state(self):
        port=DemoUiBrokerPort(MagicMock(),lambda _:None)
        port.inspect_account=lambda platform,role:ACCOUNT
        port._account_binding[("MT5","external")]=ACCOUNT
        position=self.snapshot()[0]
        port.automation.emergency.guard=MagicMock()
        with patch(
            "trading_helper.demo_broker_port.time.sleep"
        ):
            port.snapshot_positions=MagicMock(side_effect=((),(position,)))
            confirmed=port.confirm_new_position(
                "MT5","external",(),"BUY",Decimal("0.16"),
                ACCOUNT.account_id,
            )
        self.assertEqual(confirmed,position)
        self.assertEqual(port.snapshot_positions.call_count,2)
        self.assertTrue(all(
            call.kwargs["allow_pending_orders"]
            for call in port.snapshot_positions.call_args_list
        ))
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
        port.inspect_account=lambda platform,role,**kwargs:ACCOUNT
        window=SimpleNamespace(handle=123)
        port._bound=MagicMock(return_value=({},window))
        with patch(
            "trading_helper.mt5_native_readonly.terminal_path_for_window",
            return_value=self.path,
        ), patch("pathlib.Path.is_file",return_value=True), patch(
            "trading_helper.mt5_native_readonly.snapshot_mt5_account",
            return_value=self.snapshot(),
        ) as read:
            port._mt5_positions=MagicMock(side_effect=AssertionError("old ownerdraw must not run"))
            self.assertEqual(len(port.snapshot_positions("MT5","external")),1)
            read.assert_called_once_with(
                ACCOUNT,terminal_path=self.path,allow_pending_orders=False
            )
            port._mt5_positions.assert_not_called()

if __name__=="__main__":unittest.main()

"""DEMO identity and safe no-position UIA probe, mocked entirely."""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from trading_helper.auto_entry import AutoEntryWorkflow,DemoAccount,Position
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError


class FakeText:
    def __init__(self, aid, content):
        self.element_info=SimpleNamespace(automation_id=aid)
        self.content=content
    def is_visible(self):return True
    def window_text(self):return self.content

class FakeGrid(FakeText):
    def __init__(self, rows):
        super().__init__("PositionListDataGrid_AId","")
        self.rows=rows
        self.iface_grid=SimpleNamespace(CurrentRowCount=len(rows))
    def descendants(self, control_type):
        if control_type=="DataItem":
            return self.rows
        if control_type=="HeaderItem":
            return []
        raise AssertionError(control_type)

class FakeWindow:
    def __init__(self,title):
        self.handle=900
        self.title=title

class DemoPortTests(unittest.TestCase):
    def setUp(self):
        self.automation=MagicMock()
        self.automation.config={
            "platforms":{
                "cTrader":{"window_title":{"internal":"cTrader","external":"cTrader"}},
                "MT5":{"window_title":{"internal":"MetaTrader","external":"MetaTrader"}}
            }
        }
        self.port=DemoUiBrokerPort(self.automation,lambda msg:None)
        self.ui_text=[
            FakeText("CTraderAccountTypeTextBlock_AId","Demo"),
            FakeText("CTraderAccountNumberTextBlock_AId","11111111"),
            FakeText("AccountSelector_BrokerNameShort_AId","Example Broker Ltd")
        ]
    def with_uia(self,items):
        root=SimpleNamespace(descendants=lambda control_type=None:items)
        return patch("pywinauto.Desktop",return_value=SimpleNamespace(
            window=lambda handle:root
        ))
    def test_mt5_demo_verified_from_title(self):
        self.automation.windows.find.return_value=FakeWindow(
            "11111111 - Example-Demo: Test Account - Hedge - Example Broker Ltd"
        )
        result=self.port.inspect_account("MT5","external")
        self.assertTrue(result.is_demo)
        self.assertEqual(result.account_id,"11111111")
        self.assertEqual(result.server,"Example-Demo")
    def test_account_change_between_preflight_and_submit_is_rejected(self):
        self.automation.windows.find.return_value=FakeWindow(
            "11111111 - Example-Demo: Test Account - Hedge"
        )
        self.port.inspect_account("MT5","external")
        self.automation.windows.find.return_value=FakeWindow(
            "53999999 - Example-Demo: Different Demo - Hedge"
        )
        with self.assertRaisesRegex(AutomationError,"被切換"):
            self.port.inspect_account("MT5","external")
        self.automation.windows.click.assert_not_called()

    def test_prefill_account_is_rechecked_before_form_verification(self):
        expected=DemoAccount("MT5","11111111","Example-Demo",True,True)
        changed=DemoAccount("MT5","53999999","Example-Demo",True,True)
        self.port.set_expected_accounts({("MT5","external"):expected})
        with self.assertRaises(AutomationError):
            self.port._bind_verified_account("MT5","external",changed)

    def test_mt5_live_identity_is_verified(self):
        self.automation.windows.find.return_value=FakeWindow(
            "11111111 - Example-Live: Test Account - Hedge"
        )
        result=self.port.inspect_account("MT5","external")
        self.assertFalse(result.is_demo)
        self.assertTrue(result.verified)
        self.assertEqual(result.server,"Example-Live")
    def test_ctrader_identity_does_not_read_demo_live_label(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader 5.10.20")
        with self.with_uia(self.ui_text):
            result=self.port.inspect_account("cTrader","internal")
        self.assertIsNone(result.is_demo)
        self.assertEqual(result.account_id,"11111111")
        self.assertEqual(result.server,"")
    def test_ctrader_identity_ignores_live_label(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader")
        self.ui_text[0].content="Live"
        with self.with_uia(self.ui_text):
            result=self.port.inspect_account("cTrader","internal")
        self.assertIsNone(result.is_demo)
        self.assertTrue(result.verified)

    def test_unknown_account_type_is_not_required_for_identity(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader")
        self.ui_text[0].content="Contest"
        with self.with_uia(self.ui_text):
            result=self.port.inspect_account("cTrader","internal")
        self.assertIsNone(result.is_demo)
        self.assertTrue(result.verified)

    def test_mt5_position_row_is_matched_by_readonly_ticket(self):
        account=DemoAccount("MT5","11111111","Example-Demo",True,True)
        expected=Position(
            "123456","11111111","MT5","ETHUSD.x","SELL",
            Decimal("0.1"),Decimal("3000"),
        )
        unrelated=Position(
            "654321","11111111","MT5","ETHUSD.x","BUY",
            Decimal("26.904"),Decimal("3100"),
        )
        self.port.inspect_account=MagicMock(return_value=account)
        self.port.snapshot_positions=MagicMock(return_value=(unrelated,expected))
        self.port._mt5_position_rows=MagicMock(return_value=(
            (0,unrelated),(4,expected),
        ))
        row,matched=self.port.find_mt5_position_row(
            "MT5","external",expected_symbol="ETHUSD",
            expected_direction="SELL",expected_volume=Decimal("0.1"),
            window=FakeWindow("11111111 - Example-Demo"),
        )
        self.assertEqual(row,4)
        self.assertEqual(matched.ticket,"123456")
        self.port.snapshot_positions.assert_called_once_with(
            "MT5","external",_window=self.port._mt5_position_rows.call_args.kwargs["window"],
            allow_pending_orders=False,
        )

    def test_mt5_position_row_match_fails_closed_for_no_or_duplicate_matches(self):
        account=DemoAccount("MT5","11111111","Example-Demo",True,True)
        expected=Position(
            "123456","11111111","MT5","ETHUSD.x","SELL",
            Decimal("0.1"),Decimal("3000"),
        )
        self.port.inspect_account=MagicMock(return_value=account)
        self.port._mt5_position_rows=MagicMock(return_value=((0,expected),))
        self.port.snapshot_positions=MagicMock(return_value=())
        with self.assertRaisesRegex(AutomationError,"符合筆數 0"):
            self.port.find_mt5_position_row(
                "MT5","external",expected_symbol="ETHUSD",
                expected_direction="SELL",expected_volume=Decimal("0.1"),
                window=FakeWindow("11111111 - Example-Demo"),
            )
        self.port.snapshot_positions.return_value=(expected,expected)
        with self.assertRaisesRegex(AutomationError,"符合筆數 2"):
            self.port.find_mt5_position_row(
                "MT5","external",expected_symbol="ETHUSD",
                expected_direction="SELL",expected_volume=Decimal("0.1"),
                window=FakeWindow("11111111 - Example-Demo"),
            )

    def test_blank_mt5_table_uses_calibrated_first_row_only_for_single_position(self):
        account=DemoAccount("MT5","11111111","Example-Demo",True,True)
        expected=Position(
            "123456","11111111","MT5","ETHUSD.x","SELL",
            Decimal("0.1"),Decimal("3000"),
        )
        self.port.inspect_account=MagicMock(return_value=account)
        self.port.snapshot_positions=MagicMock(return_value=(expected,))
        self.port._mt5_position_rows=MagicMock(return_value=())

        row,matched=self.port.find_mt5_position_row(
            "MT5","external",expected_symbol="ETHUSD",
            expected_direction="SELL",expected_volume=Decimal("0.1"),
            window=FakeWindow("11111111 - Example-Demo"),
        )

        self.assertEqual(row,0)
        self.assertEqual(matched.ticket,"123456")
        self.assertTrue(
            self.port._mt5_position_rows.call_args.kwargs["allow_blank_rows"]
        )

    def test_blank_mt5_table_still_fails_closed_when_multiple_positions_exist(self):
        account=DemoAccount("MT5","11111111","Example-Demo",True,True)
        one=Position(
            "123456","11111111","MT5","ETHUSD.x","SELL",
            Decimal("0.1"),Decimal("3000"),
        )
        other=Position(
            "234567","11111111","MT5","GOLD","BUY",
            Decimal("0.2"),Decimal("2000"),
        )
        self.port.inspect_account=MagicMock(return_value=account)
        self.port.snapshot_positions=MagicMock(return_value=(one,other))
        self.port._mt5_position_rows=MagicMock(return_value=())

        with self.assertRaisesRegex(AutomationError,"多筆持倉.*無法安全對應"):
            self.port.find_mt5_position_row(
                "MT5","external",expected_symbol="ETHUSD",
                expected_direction="SELL",expected_volume=Decimal("0.1"),
                window=FakeWindow("11111111 - Example-Demo"),
            )

    def test_mt5_partial_memory_read_uses_native_fallback_for_one_position(self):
        class PartialMemoryReadError(OSError):
            winerror=299

        account=DemoAccount("MT5","11111111","Example-Demo",True,True)
        expected=Position(
            "123456","11111111","MT5","ETHUSD.x","SELL",
            Decimal("0.1"),Decimal("3000"),
        )
        self.port.inspect_account=MagicMock(return_value=account)
        self.port.snapshot_positions=MagicMock(return_value=(expected,))
        self.port._mt5_position_rows=MagicMock(
            side_effect=PartialMemoryReadError("partial process-memory read")
        )

        row,matched=self.port.find_mt5_position_row(
            "MT5","external",expected_symbol="ETHUSD",
            expected_direction="SELL",expected_volume=Decimal("0.1"),
            window=FakeWindow("11111111 - Example-Demo"),
        )

        self.assertEqual(row,0)
        self.assertEqual(matched.ticket,"123456")

    def test_mt5_partial_memory_read_with_multiple_positions_stops_safely(self):
        class PartialMemoryReadError(OSError):
            winerror=299

        account=DemoAccount("MT5","11111111","Example-Demo",True,True)
        expected=Position(
            "123456","11111111","MT5","ETHUSD.x","SELL",
            Decimal("0.1"),Decimal("3000"),
        )
        other=Position(
            "234567","11111111","MT5","GOLD","BUY",
            Decimal("0.2"),Decimal("2000"),
        )
        self.port.inspect_account=MagicMock(return_value=account)
        self.port.snapshot_positions=MagicMock(return_value=(expected,other))
        self.port._mt5_position_rows=MagicMock(
            side_effect=PartialMemoryReadError("partial process-memory read")
        )

        with self.assertRaisesRegex(AutomationError,"讀取不完整.*多筆持倉"):
            self.port.find_mt5_position_row(
                "MT5","external",expected_symbol="ETHUSD",
                expected_direction="SELL",expected_volume=Decimal("0.1"),
                window=FakeWindow("11111111 - Example-Demo"),
            )

    def test_mt5_position_row_read_does_not_swallow_other_os_errors(self):
        class OtherWinError(OSError):
            winerror=5

        account=DemoAccount("MT5","11111111","Example-Demo",True,True)
        expected=Position(
            "123456","11111111","MT5","ETHUSD.x","SELL",
            Decimal("0.1"),Decimal("3000"),
        )
        self.port.inspect_account=MagicMock(return_value=account)
        self.port.snapshot_positions=MagicMock(return_value=(expected,))
        self.port._mt5_position_rows=MagicMock(
            side_effect=OtherWinError("access denied")
        )

        with self.assertRaisesRegex(OtherWinError,"access denied"):
            self.port.find_mt5_position_row(
                "MT5","external",expected_symbol="ETHUSD",
                expected_direction="SELL",expected_volume=Decimal("0.1"),
                window=FakeWindow("11111111 - Example-Demo"),
            )

    def test_duplicate_account_label_rejected(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader")
        with self.with_uia(self.ui_text+[self.ui_text[1]]):
            with self.assertRaisesRegex(AutomationError,"唯一"):
                self.port.inspect_account("cTrader","internal")
    def test_ctrader_empty_grid_is_accepted_readonly(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader")
        with self.with_uia(self.ui_text+[FakeGrid([])]):
            self.assertEqual(self.port.snapshot_positions("cTrader","internal"),())
    def test_ctrader_existing_position_refuses_unknown_id(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader")
        with self.with_uia(self.ui_text+[FakeGrid([FakeText("position","XAUUSD")])]):
            with self.assertRaisesRegex(AutomationError,"欄名"):
                self.port.snapshot_positions("cTrader","internal")
    def test_mt5_trade_list_fails_closed_before_any_click(self):
        self.automation.windows.find.return_value=FakeWindow(
            "11111111 - Example-Demo: Test Account - Hedge"
        )
        fake=SimpleNamespace(descendants=lambda:[])
        with patch("pywinauto.Desktop",return_value=SimpleNamespace(
            window=lambda handle:fake
        )):
            with self.assertRaisesRegex(AutomationError,"不唯一"):
                self.port._mt5_positions("MT5","external",self.port.inspect_account("MT5","external"))
        self.automation.windows.click.assert_not_called()
    def test_ctrader_signed_stop_loss_is_not_rejected_as_invalid(self):
        from decimal import Decimal
        self.port.set_expected_symbol("GOLD")
        self.port.inspect_account=MagicMock()
        self.port._verify_instrument=MagicMock()
        self.port._form_window=MagicMock(return_value=(
            {"points":{"lot_input":{},"sl_input":{},"tp_input":{},
                       "buy_button":{},"sell_button":{},
                       "sl_checkbox":{},"tp_checkbox":{}}},
            FakeWindow("cTrader")
        ))
        self.automation.windows.read_fill_snapshot.return_value={
            "values":{"lot_input":"0.4","sl_input":"-527",
                      "tp_input":"3378"},
            "direction":"BUY",
            "checks":{"sl_checkbox":True,"tp_checkbox":True},
        }
        self.automation._normalize_numeric_input.side_effect=(
            lambda v, expected=None: Decimal(str(v))
        )
        self.port.verify_order_form("cTrader","internal","BUY",Decimal("0.4"))
        self.automation.windows.read_fill_snapshot.return_value["values"]["sl_input"]="0"
        with self.assertRaisesRegex(AutomationError,"沒有有效數值"):
            self.port.verify_order_form("cTrader","internal","BUY",Decimal("0.4"))

    def test_ctrader_final_sl_tp_must_match_last_verified_fill(self):
        from decimal import Decimal
        self.port.set_expected_symbol("GOLD")
        self.automation._last_verified_fills={
            ("cTrader","internal"):{
                "direction":"BUY", "symbol":"GOLD",
                "values":{"lot_input":Decimal("0.4"),
                          "sl_input":Decimal("-527"),
                          "tp_input":Decimal("3378")},
            }
        }
        self.port.inspect_account=MagicMock()
        self.port._verify_instrument=MagicMock()
        self.port._form_window=MagicMock(return_value=(
            {"points":{"lot_input":{},"sl_input":{},"tp_input":{},
                       "buy_button":{},"sell_button":{},
                       "sl_checkbox":{},"tp_checkbox":{}}},
            FakeWindow("cTrader")
        ))
        self.automation.windows.read_fill_snapshot.return_value={
            "values":{"lot_input":"0.4","sl_input":"-526",
                      "tp_input":"3378"},
            "direction":"BUY",
            "checks":{"sl_checkbox":True,"tp_checkbox":True},
        }
        self.automation._normalize_numeric_input.side_effect=(
            lambda value, expected=None: Decimal(str(value))
        )
        with self.assertRaisesRegex(AutomationError,"sl_input"):
            self.port.verify_order_form(
                "cTrader","internal","BUY",Decimal("0.4")
            )
        self.automation.windows.click.assert_not_called()

    def test_ctrader_submit_requires_successful_current_fill_readback(self):
        with self.assertRaisesRegex(AutomationError,"缺少本次填值"):
            self.port.submit_once("cTrader","internal","BUY",1,"key")
        self.automation.windows.click.assert_not_called()

    def test_mt5_final_absolute_prices_must_match_last_verified_fill(self):
        from decimal import Decimal
        self.port.set_expected_symbol("GOLD")
        self.automation._last_verified_fills={
            ("MT5","internal"):{
                "direction":"BUY", "symbol":"GOLD",
                "values":{"lot_input":Decimal("0.4"),
                          "sl_input":Decimal("4100.12"),
                          "tp_input":Decimal("4110.12")},
            }
        }
        self.port.inspect_account=MagicMock()
        self.port._verify_instrument=MagicMock()
        self.port._form_window=MagicMock(return_value=(
            {"points":{"lot_input":{},"sl_input":{},"tp_input":{}}},
            FakeWindow("11111111 - Example-Demo")
        ))
        self.automation.windows.read_fill_snapshot.return_value={
            "values":{"lot_input":"0.4","sl_input":"4100.11",
                      "tp_input":"4110.12"},
            "direction":None,"checks":{},
        }
        self.automation._normalize_numeric_input.side_effect=(
            lambda value, expected=None: Decimal(str(value))
        )
        with self.assertRaisesRegex(AutomationError,"sl_input"):
            self.port.verify_order_form(
                "MT5","internal","BUY",Decimal("0.4")
            )
        self.automation.windows.click.assert_not_called()

    def test_mt5_open_position_subitem_mapping_skips_hidden_column(self):
        # The native MT5 ListView has hidden subitem 2. Headers use
        # subitems 0,1,3,4,5,6,7,8,9,12, so type is 4 not 3.
        self.automation.windows.find.return_value=FakeWindow(
            "11111111 - Example-Demo: Test Account - Hedge"
        )
        rows=[
            [""]*9,
            ["GOLD","11111111","","2025.01.01 00:00",
             "buy","0.01","100.00","99.00","101.00"],
        ]
        class View:
            def class_name(self):return "SysListView32"
            def control_id(self):return 10328
            def is_visible(self):return True
            def columns(self):return [{}]*10
            def item_count(self):return len(rows)
            def get_item(self,i,j):
                return SimpleNamespace(text=lambda:rows[i][j])
        root=SimpleNamespace(descendants=lambda:[View()])
        with patch("pywinauto.Desktop",return_value=SimpleNamespace(
            window=lambda handle:root
        )):
            positions=self.port._mt5_positions("MT5","external",self.port.inspect_account("MT5","external"))
        self.assertEqual(len(positions),1)
        self.assertEqual(positions[0].ticket,"11111111")
        self.assertEqual(positions[0].direction,"BUY")
        self.assertEqual(str(positions[0].volume),"0.01")
        self.assertEqual(str(positions[0].entry_price),"100.00")
        self.assertEqual(str(positions[0].sl),"99.00")
        self.assertEqual(str(positions[0].tp),"101.00")

    def test_mt5_order_instrument_rejects_wrong_symbol(self):
        self.port.set_expected_symbol("GOLD")
        with self.assertRaisesRegex(AutomationError,"商品"):
            self.port._verify_instrument(
                "MT5","external",FakeWindow("Order: BTCUSD")
            )
        self.port._verify_instrument(
            "MT5","external",FakeWindow("Order: XAUUSD+ - Gold US Dollar")
        )

    def test_weekend_btc_test_mode_skips_mt5_and_ctrader_symbol_identity_checks(self):
        messages=[]
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }):
            port=DemoUiBrokerPort(self.automation,messages.append)
            port.set_expected_symbol("XAUUSD")
            port._verify_instrument(
                "MT5","external",FakeWindow("Order: EURUSD"),_controls=[]
            )
            port._verify_instrument(
                "cTrader","external",FakeWindow("cTrader"),_controls=[]
            )
        notices=[message for message in messages if "略過 MT5 與 cTrader" in message]
        self.assertEqual(len(notices),1)

    def test_weekend_eth_test_mode_skips_mt5_and_ctrader_symbol_identity_checks(self):
        messages=[]
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"ETHUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            port=DemoUiBrokerPort(self.automation,messages.append)
            port.set_expected_symbol("XAUUSD")
            port._verify_instrument(
                "MT5","external",FakeWindow("Order: EURUSD"),_controls=[]
            )
            port._verify_instrument(
                "cTrader","external",FakeWindow("cTrader"),_controls=[]
            )
        self.assertTrue(any("LAB ETHUSD 假日測試" in message for message in messages))

    def test_weekend_symbol_skip_does_not_apply_to_unlisted_platforms(self):
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            port=DemoUiBrokerPort(self.automation,lambda msg:None)
            port.set_expected_symbol("GOLD")
            with self.assertRaisesRegex(AutomationError,"Bitcoin vs US Dollar"):
                port._verify_instrument(
                    "OtherPlatform","external",FakeWindow("OtherPlatform"),
                    _controls=[],
                )

    def test_mt5_and_ctrader_symbol_checks_remain_enabled_without_test_flag(self):
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
        }, clear=True):
            port=DemoUiBrokerPort(self.automation,lambda msg:None)
            port.set_expected_symbol("XAUUSD")
            with self.assertRaisesRegex(AutomationError,"商品"):
                port._verify_instrument(
                    "MT5","external",FakeWindow("Order: EURUSD"),_controls=[]
                )
            with self.assertRaisesRegex(AutomationError,"Bitcoin vs US Dollar"):
                port._verify_instrument(
                    "cTrader","external",FakeWindow("cTrader"),_controls=[]
                )

    def test_weekend_btc_and_eth_test_symbols_are_used_for_postfill_validation(self):
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.assertEqual(
                AutoEntryWorkflow._effective_test_symbol("GOLD"),"BTCUSD"
            )
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"ETHUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.assertEqual(
                AutoEntryWorkflow._effective_test_symbol("GOLD"),"ETHUSD"
            )

    def test_postfill_symbol_stays_from_instruction_without_test_bypass(self):
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
        }, clear=True):
            self.assertEqual(
                AutoEntryWorkflow._effective_test_symbol("GOLD"),"GOLD"
            )

    def test_no_live_submit_or_modify_from_unverified_adapter(self):
        with self.assertRaises(AutomationError):
            self.port.submit_once("cTrader","internal","BUY",1,"key")
        from trading_helper.auto_entry import Position
        from decimal import Decimal
        pos=Position("ticket","11111111","cTrader","XAUUSD",
                     "BUY",Decimal("0.1"),Decimal("4100"))
        with self.assertRaises(AutomationError):
            self.port.set_position_sl_tp(pos,1,2)
        self.automation.windows.click.assert_not_called()
    def test_verification_failure_does_not_fake_success(self):
        with self.assertRaises(AutomationError):
            self.port.verify_order_form("MT5","external","SELL",1)
        self.automation.windows.click.assert_not_called()

if __name__=="__main__":
    unittest.main()


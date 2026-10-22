"""DEMO identity and safe no-position UIA probe, mocked entirely."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from trading_helper.auto_entry import AutoEntryWorkflow
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
            FakeText("CTraderAccountNumberTextBlock_AId","10125710"),
            FakeText("AccountSelector_BrokerNameShort_AId","Raw Trading Ltd")
        ]
    def with_uia(self,items):
        root=SimpleNamespace(descendants=lambda control_type=None:items)
        return patch("pywinauto.Desktop",return_value=SimpleNamespace(
            window=lambda handle:root
        ))
    def test_mt5_demo_verified_from_title(self):
        self.automation.windows.find.return_value=FakeWindow(
            "53099775 - ICMarketsSC-Demo: Test Account - Hedge - Raw Trading Ltd"
        )
        result=self.port.inspect_account("MT5","external")
        self.assertTrue(result.is_demo)
        self.assertEqual(result.account_id,"53099775")
        self.assertEqual(result.server,"ICMarketsSC-Demo")
    def test_account_change_between_preflight_and_submit_is_rejected(self):
        self.automation.windows.find.return_value=FakeWindow(
            "53099775 - ICMarketsSC-Demo: Test Account - Hedge"
        )
        self.port.inspect_account("MT5","external")
        self.automation.windows.find.return_value=FakeWindow(
            "53999999 - ICMarketsSC-Demo: Different Demo - Hedge"
        )
        with self.assertRaisesRegex(AutomationError,"被切換"):
            self.port.inspect_account("MT5","external")
        self.automation.windows.click.assert_not_called()

    def test_mt5_live_is_rejected(self):
        self.automation.windows.find.return_value=FakeWindow(
            "53099775 - ICMarketsSC-Live - Hedge"
        )
        with self.assertRaisesRegex(AutomationError,"Demo"):
            self.port.inspect_account("MT5","external")
    def test_ctrader_demo_verified_only_with_unique_native_labels(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader 5.10.20")
        with self.with_uia(self.ui_text):
            result=self.port.inspect_account("cTrader","internal")
        self.assertTrue(result.is_demo)
        self.assertEqual(result.account_id,"10125710")
        self.assertEqual(result.server,"Raw Trading Ltd")
    def test_ctrader_real_account_rejected(self):
        self.automation.windows.find.return_value=FakeWindow("cTrader")
        self.ui_text[0].content="Live"
        with self.with_uia(self.ui_text):
            with self.assertRaisesRegex(AutomationError,"Demo"):
                self.port.inspect_account("cTrader","internal")
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
            "53099775 - ICMarketsSC-Demo: Test Account - Hedge"
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
            FakeWindow("53099775 - ICMarketsSC-Demo")
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
            "53099775 - ICMarketsSC-Demo: Test Account - Hedge"
        )
        rows=[
            [""]*9,
            ["XAUUSD","12345678","","2026.10.15 16:00",
             "buy","0.4","4100.12","4090.12","4120.12"],
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
        self.assertEqual(positions[0].ticket,"12345678")
        self.assertEqual(positions[0].direction,"BUY")
        self.assertEqual(str(positions[0].volume),"0.4")
        self.assertEqual(str(positions[0].entry_price),"4100.12")
        self.assertEqual(str(positions[0].sl),"4090.12")
        self.assertEqual(str(positions[0].tp),"4120.12")

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
        pos=Position("ticket","10125710","cTrader","XAUUSD",
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

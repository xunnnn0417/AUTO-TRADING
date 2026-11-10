"""Verify both pre-submit sides with bounded retries, entirely offline.

Fake windows do not actually focus broker software or press any real button.
"""
import unittest
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.automation import PlatformAutomation
from trading_helper.test_mode import effective_test_symbol
from trading_helper.windows import AutomationError, WindowController, WindowInfo


class DummyEmergency:
    def guard(self):pass


class FakeWindowActions:
    def __init__(self):
        self.writes=[]
        self.values={}
        self.directions={}
        self.checks={"sl_checkbox":True,"tp_checkbox":True}
        self.poison={}
        self.bad_read=set()
        self.bad_check=False
        self.bad_direction=None

    def read_edit_value(self,window,point):
        key=point["id"]
        if key in self.bad_read:
            raise AutomationError("UIA get_value unavailable")
        return self.values.get(key,"0")
    def click_and_type(self,window,point,value):
        key=point["id"]
        self.writes.append((window.title,key,value))
        nth=sum(1 for _,k,_ in self.writes if k==key)
        # A field with multiple rejected writes recovers only after
        # requested nth attempt; 99 means permanently wrong.
        fail_through=self.poison.get(key,0)
        self.values[key]="999" if nth<=fail_through else value
    def read_ctrader_direction(self,window,points):
        return self.bad_direction or "BUY"
    def read_ctrader_checkbox_checked(self,window,point,key):
        return self.checks[key] and not self.bad_check
    def click(self,window,point):pass
    def find(self,pattern):return WindowInfo(1,"MT5",0,0,800,600)
    def wait_for_active_window_change(self,window,timeout):
        return WindowInfo(2,"New Order",0,0,800,600)
    def read_number(self,window,point):return D("4100")
    def refresh_checkbox_checked(self,window,point,key):return 1

class FillVerificationTests(unittest.TestCase):
    def setUp(self):
        self.log=[]
        self.fake=FakeWindowActions()
        self.config={"platforms":{
            "MT5":{"window_title":{"internal":"MT5","external":"MT5"},"points":{
                key:{"id":key,"x_px":100+i*80,"y_px":70,
                      "window_width":800,"window_height":600}
                for i,key in enumerate((
                    "new_order_button","lot_input","ask_price","sl_input","tp_input"))
            }},
            "cTrader":{"window_title":{"internal":"cTrader","external":"cTrader"},"points":{
                key:{"id":key,"x_px":100+i*70,"y_px":70,
                      "window_width":800,"window_height":600}
                for i,key in enumerate((
                    "lot_input","sl_input","tp_input","sl_checkbox",
                    "tp_checkbox","buy_button","sell_button"))
            }},
        }}
        self.automation=PlatformAutomation(
            self.config,self.fake,DummyEmergency(),self.log.append
        )
        self.automation._window_for_point=lambda *args:WindowInfo(
            7,"cTrader",0,0,800,600
        )
        self.window=WindowInfo(1,"MT5",0,0,800,600)
        self.mt5=WindowInfo(2,"New Order",0,0,800,600)
        self.values=[
            ("lot_input","手數","0.74"),
            ("sl_input","止損價","4100.25"),
            ("tp_input","止盈價","4111.50"),
        ]
    def test_test_symbol_requires_supported_symbol_and_both_process_flags(self):
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.assertEqual(effective_test_symbol("GOLD"),"BTCUSD")
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"ETHUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.assertEqual(effective_test_symbol("GOLD"),"ETHUSD")
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"GOLD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.assertEqual(effective_test_symbol("ETHUSD"),"ETHUSD")
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
        }, clear=True):
            self.assertEqual(effective_test_symbol("GOLD"),"GOLD")
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.assertEqual(effective_test_symbol("GOLD"),"GOLD")

    def test_btc_override_disallows_fallback_to_original_sheet_price(self):
        instruction=SimpleNamespace(symbol="GOLD",estimated_price=D("408.00"))
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.assertFalse(
                self.automation._allow_sheet_price_fallback("GOLD")
            )
            self.fake.read_number=MagicMock(
                side_effect=AutomationError("讀不到報價")
            )
            with self.assertRaisesRegex(AutomationError,"不會拿表格原商品"):
                self.automation._read_mt5_reference_price(
                    self.window,{"x_px":1},instruction,"場內"
                )
            self.assertTrue(
                self.automation._allow_sheet_price_fallback("BTCUSD")
            )
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(
                self.automation._allow_sheet_price_fallback("GOLD")
            )
            self.assertEqual(
                self.automation._read_mt5_reference_price(
                    self.window,{"x_px":1},instruction,"場內"
                ),D("408.00")
            )

    def test_mt5_quote_pair_uses_ask_for_buy_and_bid_for_sell(self):
        instruction=SimpleNamespace(symbol="GOLD")
        self.fake.read_number=MagicMock(side_effect=[D("4100.00"),D("4100.25")])
        buy=self.automation._read_mt5_quote_pair(
            self.window,{}, {},instruction,"BUY","場內"
        )
        self.assertEqual(buy,D("4100.25"))
        self.fake.read_number=MagicMock(side_effect=[D("4100.00"),D("4100.25")])
        sell=self.automation._read_mt5_quote_pair(
            self.window,{}, {},instruction,"SELL","場內"
        )
        self.assertEqual(sell,D("4100.00"))

    def test_mt5_quote_pair_rejects_bad_order_or_excessive_spread(self):
        instruction=SimpleNamespace(symbol="GOLD")
        self.fake.read_number=MagicMock(side_effect=[D("4100.25"),D("4100.00")])
        self.fake.read_number=MagicMock(side_effect=[
            D("4100.25"),D("4100.00")]*3
        )
        with self.assertRaisesRegex(AutomationError,"連續 3 次未能可靠核對"):
            self.automation._read_mt5_quote_pair(
                self.window,{}, {},instruction,"BUY","場內"
            )
        self.fake.read_number=MagicMock(side_effect=[D("4100"),D("4160")]*3)
        with self.assertRaisesRegex(AutomationError,"連續 3 次未能可靠核對"):
            self.automation._read_mt5_quote_pair(
                self.window,{}, {},instruction,"BUY","場內"
            )

    def test_btc_quote_pair_rejects_truncated_tail_but_accepts_full_quote(self):
        instruction=SimpleNamespace(symbol="GOLD")
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.fake.read_number=MagicMock(
                side_effect=[D("428.52"),D("436.02")]*3
            )
            with self.assertRaisesRegex(AutomationError,"連續 3 次未能可靠核對"):
                self.automation._read_mt5_quote_pair(
                    self.window,{}, {},instruction,"BUY","場內"
                )
            self.fake.read_number=MagicMock(
                side_effect=[D("81428.52"),D("81436.02")]
            )
            self.assertEqual(
                self.automation._read_mt5_quote_pair(
                    self.window,{}, {},instruction,"BUY","場內"
                ),D("81436.02")
            )
            self.fake.read_number=MagicMock(
                side_effect=[D("999.99"),D("1000.00")]*3
            )
            with self.assertRaisesRegex(AutomationError,"BTCUSD 報價低於 LAB 測試下限"):
                self.automation._read_mt5_quote_pair(
                    self.window,{}, {},instruction,"BUY","場內"
                )

    def test_eth_quote_retries_transient_truncated_read_and_rejects_repeated_tail(self):
        instruction=SimpleNamespace(symbol="GOLD")
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"ETHUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.fake.read_number=MagicMock(side_effect=[
                D("420.86"),D("423.80"),D("2420.86"),D("2423.80")
            ])
            self.assertEqual(
                self.automation._read_mt5_quote_pair(
                    self.window,{}, {},instruction,"BUY","場內"
                ),D("2423.80")
            )
            self.fake.read_number=MagicMock(
                side_effect=[D("420.86"),D("423.80")]*3
            )
            with self.assertRaisesRegex(AutomationError,"ETHUSD 報價低於 LAB 測試下限"):
                self.automation._read_mt5_quote_pair(
                    self.window,{}, {},instruction,"BUY","場內"
                )

    def test_mt5_quote_recovers_from_truncated_fast_read_with_repeated_full_candidates(self):
        instruction=SimpleNamespace(symbol="GOLD")
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"ETHUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            self.fake.read_number=MagicMock(
                side_effect=[D("422.25"),D("2425.79")]
            )
            self.fake.read_number_candidates=MagicMock(side_effect=[
                [D("422.25"),D("2422.25"),D("2422.25")],
                [D("2425.79"),D("2425.79")],
            ])
            result=self.automation._read_mt5_quote_pair(
                self.window,{}, {},instruction,"BUY","場內"
            )
            self.assertEqual(result,D("2425.79"))
            self.fake.read_number_candidates.assert_any_call(self.window,{})
            self.assertTrue(any("完整 OCR 候選交叉核對" in line for line in self.log))

    def test_full_mt5_quote_candidate_scan_combines_all_crops(self):
        controller=object.__new__(WindowController)
        controller.emergency=DummyEmergency()
        controller.focus=MagicMock(return_value=self.window)
        controller._validate_calibrated_window=MagicMock()
        controller.screen_point=MagicMock(return_value=(100,200))
        controller._read_number_candidates_ocr=MagicMock(side_effect=[
            [D("422.25"),D("2422.25")],
            [D("2422.25")],
            [D("2422.25")],
            [D("422.25")],
        ])
        candidates=controller.read_number_candidates(self.window,{"x_px":1})
        self.assertEqual(candidates,[
            D("422.25"),D("2422.25"),D("2422.25"),D("2422.25"),D("422.25")
        ])
        self.assertEqual(controller._read_number_candidates_ocr.call_count,4)
        self.assertTrue(all(
            call.kwargs["all_variants"]
            for call in controller._read_number_candidates_ocr.call_args_list
        ))

    def test_eth_price_range_guard_is_limited_to_explicit_test_mode(self):
        instruction=SimpleNamespace(symbol="ETHUSD")
        with patch.dict("os.environ", {}, clear=True):
            self.fake.read_number=MagicMock(
                side_effect=[D("980.10"),D("980.30")]
            )
            self.assertEqual(
                self.automation._read_mt5_quote_pair(
                    self.window,{}, {},instruction,"BUY","場內"
                ),D("980.30")
            )

    def test_btc_fill_requires_two_price_calibrations_even_with_old_point(self):
        instruction=SimpleNamespace(symbol="GOLD",estimated_price=D("408"))
        with patch.dict("os.environ", {
            "TRADING_HELPER_TEST_SYMBOL_OVERRIDE":"BTCUSD",
            "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK":"1",
        }, clear=True):
            with self.assertRaisesRegex(AutomationError,"需要左右兩側報價校準"):
                self.automation.fill("MT5","internal",instruction)

    def seed(self):
        for key,_,value in self.values:
            self.fake.click_and_type(self.mt5,{"id":key},value)
    def verify_mt5(self):
        self.automation._verify_filled_side(
            self.config["platforms"]["MT5"],"internal","MT5","場內",
            self.config["platforms"]["MT5"]["points"],
            self.window,self.mt5,"BUY",self.values
        )
    def verify_ctrader(self):
        self.automation._verify_filled_side(
            self.config["platforms"]["cTrader"],"internal","cTrader","場內",
            self.config["platforms"]["cTrader"]["points"],
            self.window,None,"BUY",self.values
        )
    def test_correct_mt5_values_no_extra_writes(self):
        self.seed()
        self.verify_mt5()
        self.assertEqual(len(self.fake.writes),3)
        self.assertTrue(any("核對通過" in x for x in self.log))
    def test_one_wrong_mt5_field_is_repaired_second_attempt(self):
        self.fake.poison={"sl_input":1}
        self.seed()
        self.verify_mt5()
        self.assertEqual([key for _,key,_ in self.fake.writes],
                         ["lot_input","sl_input","tp_input","sl_input"])
        self.assertEqual(self.fake.values["sl_input"],"4100.25")
    def test_wrong_field_three_attempts_then_stop(self):
        self.fake.poison={"tp_input":99}
        self.seed()
        with self.assertRaisesRegex(AutomationError,"三次填入.*止盈價|止盈價.*三次填入"):
            self.verify_mt5()
        self.assertEqual([key for _,key,_ in self.fake.writes].count("tp_input"),3)
        self.assertEqual([key for _,key,_ in self.fake.writes].count("sl_input"),1)
    def test_unreadable_field_is_not_retyped(self):
        self.seed()
        self.fake.bad_read={"tp_input"}
        with self.assertRaisesRegex(AutomationError,"止盈價 無法讀回確認"):
            self.verify_mt5()
        self.assertEqual(len(self.fake.writes),3)
    def test_ctrader_direction_mismatch_halts_before_any_repair(self):
        self.seed()
        self.fake.bad_direction="SELL"
        with self.assertRaisesRegex(AutomationError,"方向錯誤"):
            self.verify_ctrader()
        self.assertEqual(len(self.fake.writes),3)
    def test_ctrader_checkbox_off_halts_without_retry(self):
        self.seed()
        self.fake.checks["sl_checkbox"]=False
        with self.assertRaisesRegex(AutomationError,"止損勾選已關閉"):
            self.verify_ctrader()
        self.assertEqual(len(self.fake.writes),3)
    def test_ctrader_two_repair_cycles_and_full_rescan(self):
        self.fake.poison={"sl_input":1,"tp_input":1}
        self.seed()
        self.verify_ctrader()
        keys=[v[1] for v in self.fake.writes]
        self.assertEqual(keys.count("sl_input"),2)
        self.assertEqual(keys.count("tp_input"),2)
        self.assertTrue(any("勾選狀態正常" in x for x in self.log))
    def test_grouped_numbers_and_numeric_equivalence(self):
        normalize=self.automation._normalize_numeric_input
        self.assertEqual(normalize("3 378"),D("3378"))
        self.assertEqual(normalize("4,117.46"),D("4117.46"))
        self.assertEqual(normalize("4100,25"),D("4100.25"))
        self.assertEqual(normalize("0.7400"),D(".74"))
        self.assertEqual(normalize("0,740",D(".74")),D(".74"))
        self.assertEqual(normalize("3,378",D("3378")),D("3378"))
        self.assertRaises(AutomationError,normalize,"--")
        self.assertRaises(AutomationError,normalize,"1.5 USD")
        self.assertRaises(AutomationError,normalize,"NaN")
    def test_both_sides_stops_before_external_if_internal_verification_fails(self):
        # This is precisely the user's requested workflow boundary:
        # failed internal readback blocks the external side.
        events=[]
        def fill(platform,role,item):
            events.append(role)
            if role=="internal":
                raise AutomationError("場內 手數核對失敗")
        from trading_helper.gui import TradingHelperApp
        fake_app=SimpleNamespace(
            automation=SimpleNamespace(fill=fill),
            _require_instruction=lambda:object(),
            _auto_entry_after_fill_both_pending=MagicMock(),
        )
        with self.assertRaisesRegex(AutomationError,"手數核對失敗"):
            TradingHelperApp._fill_both_task(fake_app,"cTrader","MT5",True)
        self.assertEqual(events,["internal"])
        fake_app._auto_entry_after_fill_both_pending.assert_not_called()


if __name__=="__main__":
    unittest.main()

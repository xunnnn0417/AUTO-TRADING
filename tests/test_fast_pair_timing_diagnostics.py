"""Offline timing and pre-click readback tests; NEVER contacts brokers."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from decimal import Decimal
from trading_helper.auto_entry import AutoEntryWorkflow,AutoEntryJournal
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.gui import TradingHelperApp
from test_auto_entry_state_machine import FakeBrokerPort,instruction


class FreshCheckFake(FakeBrokerPort):
    def __init__(self):
        super().__init__()
        self.counts={"internal":0,"external":0}
        self.submit_times={}
    def verify_order_form(self,platform,role,direction,lot):
        self.counts[role]+=1
        time.sleep(.018)
        return super().verify_order_form(platform,role,direction,lot)
    def submit_once(self,platform,role,direction,lot,key):
        # The actual DemoUiBrokerPort does a fresh readback as part of
        # submit_once. Model the same invariant, with no real clicks.
        self.verify_order_form(platform,role,direction,lot)
        self.submit_times[role]=time.perf_counter()
        return super().submit_once(platform,role,direction,lot,key)


class FastPairTimingTests(unittest.TestCase):
    def test_each_side_has_early_and_fresh_preclick_checks_not_three(self):
        with tempfile.TemporaryDirectory() as folder:
            broker=FreshCheckFake()
            logs=[]
            flow=AutoEntryWorkflow(
                broker,AutoEntryJournal(Path(folder)/"journal.json"),
                lambda:None,logs.append
            )
            flow.run(instruction(),"cTrader","MT5","fast-check",
                     "fake-sheet",fast_pair=True,
                     sync_sl_tp=False,draw_tv=False)
            self.assertEqual(broker.counts,{"internal":2,"external":2})
            self.assertEqual(len([e for e in broker.events if e[0]=="submit"]),2)
            self.assertTrue(any("送單呼叫開始間隔" in x for x in logs))

    def test_real_ui_submit_requires_fresh_form_but_not_duplicate_account_scan(self):
        # Monkeypatched cTrader UIA tree - no live platform, no real click.
        class Ancestor:
            def __init__(self,name,parent=None):
                self.element_info=SimpleNamespace(automation_id=name)
                self._parent=parent
            def parent(self):
                return self._parent
        parent2=Ancestor("PropertySectionView_AId")
        parent1=Ancestor("AspPlaceOrderButton_AId",parent2)
        class Button:
            element_info=SimpleNamespace(
                control_type="Button",
                automation_id=(
                    "Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId"
                )
            )
            def is_visible(self):return True
            def is_enabled(self):return True
            def rectangle(self):
                return SimpleNamespace(left=10,right=90,top=10,bottom=90)
            def parent(self):return parent1
        native_root=SimpleNamespace(descendants=lambda **kwargs:[Button()])
        desktop=SimpleNamespace(window=lambda **kwargs:native_root)
        window=SimpleNamespace(handle=123)
        windows=SimpleNamespace(
            screen_point=MagicMock(return_value=(50,50)),
            click=MagicMock(),
        )
        adapter=DemoUiBrokerPort(
            SimpleNamespace(
                windows=windows,
                emergency=SimpleNamespace(guard=lambda:None),
            ),lambda _:None
        )
        adapter.automation._last_verified_fills={
            ("cTrader","external"):{
                "direction":"BUY", "symbol":"GOLD",
                "values":{"lot_input":Decimal("0.1"),
                          "sl_input":Decimal("-527"),
                          "tp_input":Decimal("3378")},
            }
        }
        adapter.set_expected_symbol("GOLD")
        windows.focus=MagicMock()
        adapter.verify_order_form=MagicMock()
        adapter.inspect_account=MagicMock(
            side_effect=AssertionError("should not re-scan account")
        )
        adapter._form_window=MagicMock(return_value=(
            {"points":{"order_submit_button":{"x_px":50}}},window
        ))
        with patch("pywinauto.Desktop",return_value=SimpleNamespace(
            window=lambda **kwargs:native_root
        )):
            adapter.submit_once("cTrader","external","BUY",
                                Decimal("0.1"),"fake-key")
        adapter.verify_order_form.assert_called_once()
        adapter.inspect_account.assert_not_called()
        windows.click.assert_called_once()
        timing=adapter.submit_phase_timings["external"]
        self.assertLessEqual(timing["start"],timing["form_verified"])
        self.assertLessEqual(
            timing["uia_inventory_returned"],timing["form_verified"]
        )
        self.assertLessEqual(timing["form_verified"],timing["click_started"])
        self.assertLessEqual(timing["click_started"],timing["click_returned"])

    def test_fill_both_reports_each_side_elapsed_time(self):
        fake=SimpleNamespace(
            automation=SimpleNamespace(fill=MagicMock()),
            _require_instruction=MagicMock(return_value=instruction()),
            log=MagicMock()
        )
        TradingHelperApp._fill_both_task(
            fake,"MT5","cTrader",auto_entry_requested=False
        )
        self.assertEqual(fake.automation.fill.call_count,2)
        text=fake.log.call_args.args[0]
        self.assertIn("填入兩邊診斷",text)
        self.assertIn("場內",text)
        self.assertIn("場外",text)


if __name__=="__main__":
    unittest.main()

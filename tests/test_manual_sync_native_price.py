"""Manual sync's native price path stays read-only and validates the full row."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from trading_helper.automation import PlatformAutomation
from trading_helper.auto_entry import Position
from trading_helper.windows import AutomationError, WindowController, WindowInfo
from tests.test_auto_entry_state_machine import instruction


class NativeManualPriceTests(unittest.TestCase):
    def test_both_platforms_read_unique_matched_position_without_hover_or_click(self):
        for platform in ("cTrader","MT5"):
            with self.subTest(platform=platform):
                item=instruction()
                windows=WindowController(SimpleNamespace(guard=lambda:None))
                windows.click=MagicMock()
                windows.read_hover_number=MagicMock(side_effect=AssertionError("no tooltip OCR"))
                windows.read_number=MagicMock(side_effect=AssertionError("no price OCR"))
                profile={"window_title":{"internal":"bound terminal"},
                         "account_number":{"internal":"111111"},
                         "points":{"positions_entry_price":{"x":0.5,"y":0.5}}}
                flow=PlatformAutomation({"platforms":{platform:profile}},windows,
                                        SimpleNamespace(guard=lambda:None),lambda _:None)
                window=WindowInfo(1,"bound terminal",0,0,800,600)
                flow._window_for_point=MagicMock(return_value=window)
                position=Position("123","111111",platform,item.symbol,
                    item.internal_direction,item.internal.lot,D("4100.25"))
                with patch("trading_helper.demo_broker_port.DemoUiBrokerPort") as port:
                    port.return_value.snapshot_positions.return_value=(position,)
                    self.assertEqual(flow._read_internal_entry_price(item,platform),D("4100.25"))
                    port.return_value.snapshot_positions.assert_called_once_with(platform,"internal",_window=window)
                    for bad in ((),(position,position),(replace(position,volume=D("99")),),
                                (replace(position,account_id="222222"),),
                                (replace(position,symbol="OTHER"),)):
                        port.return_value.snapshot_positions.return_value=bad
                        with self.assertRaises(AutomationError):
                            flow._read_internal_entry_price(item,platform)
                windows.click.assert_not_called()
                windows.read_hover_number.assert_not_called()
                windows.read_number.assert_not_called()

    def test_unavailable_native_reader_keeps_existing_calibrated_fallback(self):
        item=instruction()
        windows=WindowController(SimpleNamespace(guard=lambda:None))
        windows.read_number=MagicMock(return_value=D("4101.50"))
        profile={"points":{"positions_entry_price":{"x":0.5,"y":0.5}}}
        flow=PlatformAutomation({"platforms":{"MT5":profile}},windows,
                                SimpleNamespace(guard=lambda:None),lambda _:None)
        window=WindowInfo(1,"bound",0,0,800,600)
        flow._window_for_point=lambda *args:window
        with patch("trading_helper.demo_broker_port.DemoUiBrokerPort") as port:
            port.return_value.snapshot_positions.side_effect=AutomationError("讀取方式不可用")
            self.assertEqual(flow._read_internal_entry_price(item,"MT5"),D("4101.50"))
        windows.read_number.assert_called_once_with(window,profile["points"]["positions_entry_price"])

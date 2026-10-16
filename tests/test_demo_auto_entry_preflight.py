"""Missing post-entry calibrations must block BEFORE the first Demo order."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from trading_helper.auto_entry import AutoEntryWorkflow, AutoEntryJournal
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError
from test_auto_entry_state_machine import FakeBrokerPort, instruction


def point():
    return {"x_px":200,"y_px":100,"window_width":1920,
            "window_height":1080}

def config():
    ct={k:point() for k in (
        "lot_input","sl_input","tp_input","order_submit_button",
        "position_order_row","position_sl_input","position_tp_input",
        "position_modify_confirm",
    )}
    mt={k:point() for k in (
        "lot_input","sl_input","tp_input","order_submit_buy",
        "order_submit_sell","position_order_row","position_sl_input",
        "position_tp_input","position_modify_confirm",
    )}
    return {"platforms":{
        "cTrader":{"points":ct},
        "MT5":{"points":mt},
        "TradingView":{"points":{"position_tool":point()},
                       "window_title":{"internal":"TradingView"}},
    }}


class PreflightPortTests(unittest.TestCase):
    def setUp(self):
        self.config=config()
        self.auto=SimpleNamespace(
            config=self.config,
            windows=SimpleNamespace(find=MagicMock(return_value="TV")),
        )
        self.port=DemoUiBrokerPort(self.auto,lambda x:None)
    def check(self,first="cTrader",second="MT5",
              sync=False,draw=False):
        self.port.validate_auto_entry_capabilities(
            first,second,"BUY","SELL",
            sync_sl_tp=sync,draw_tv=draw
        )
    def test_no_optional_sync_requires_submit_calibrations_only(self):
        self.config["platforms"]["MT5"]["points"].pop(
            "position_modify_confirm"
        )
        self.check()
    def test_cTrader_missing_submit_button_rejected(self):
        self.config["platforms"]["cTrader"]["points"].pop(
            "order_submit_button"
        )
        with self.assertRaisesRegex(AutomationError,
                                    "order_submit_button"):
            self.check()
    def test_mt5_missing_sell_button_rejected_before_submit(self):
        self.config["platforms"]["MT5"]["points"].pop(
            "order_submit_sell"
        )
        with self.assertRaisesRegex(AutomationError,
                                    "order_submit_sell"):
            self.check()
    def test_mt5_internal_must_have_modify_calibration(self):
        self.config["platforms"]["MT5"]["points"].pop(
            "position_modify_confirm"
        )
        with self.assertRaisesRegex(AutomationError,
                                    "position_modify_confirm"):
            self.check("MT5","cTrader")
    def test_mt5_external_sync_must_have_modify_calibration(self):
        self.config["platforms"]["MT5"]["points"].pop(
            "position_tp_input"
        )
        with self.assertRaisesRegex(AutomationError,
                                    "position_tp_input"):
            self.check(sync=True)
    def test_empty_position_rows_block_late_modification(self):
        self.config["platforms"]["cTrader"]["points"].pop(
            "position_order_row"
        )
        with self.assertRaisesRegex(AutomationError,
                                    "position_order_row"):
            self.check("MT5","cTrader",sync=True)
    def test_incomplete_geometry_rejected(self):
        self.config["platforms"]["cTrader"]["points"][
            "order_submit_button"
        ]={"x_px":100}
        with self.assertRaisesRegex(AutomationError,
                                    "座標不完整"):
            self.check()
    def test_tv_enabled_requires_calibration(self):
        self.config["platforms"]["TradingView"]["points"].clear()
        with self.assertRaisesRegex(AutomationError,
                                    "TradingView"):
            self.check(sync=True,draw=True)
    def test_tv_enabled_checks_window_early(self):
        self.check(sync=True,draw=True)
        self.auto.windows.find.assert_called_once_with("TradingView")
    def test_valid_sync_has_every_required_control(self):
        self.check(sync=True)
    def test_no_trade_if_post_entry_preflight_fails(self):
        with tempfile.TemporaryDirectory() as td:
            broker=FakeBrokerPort()
            broker.validate_auto_entry_capabilities=MagicMock(
                side_effect=AutomationError(
                    "場外 MT5 缺少持倉修改確認按鈕"
                )
            )
            flow=AutoEntryWorkflow(
                broker,AutoEntryJournal(Path(td)/"journal.json"),
                lambda:None,lambda x:None
            )
            with self.assertRaisesRegex(AutomationError,
                                        "持倉修改確認按鈕"):
                flow.run(
                    instruction(),"cTrader","MT5","Test","sheet",
                    sync_sl_tp=True,draw_tv=False
                )
            self.assertFalse(any(x[0]=="submit" for x in broker.events))
            broker.validate_auto_entry_capabilities.assert_called_once()


if __name__=="__main__":
    unittest.main()

"""The trading-page price replaces the duplicate edit-page UI (no auto-TV)."""
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from trading_helper import gui
from trading_helper.models import TradeInstruction, SideValues


def instruction(price=None):
    return TradeInstruction(
        source_row=2, status="", symbol="XAUUSD", sheet_direction="BUY",
        internal=SideValues(Decimal(".4"),Decimal("-6"),Decimal("10")),
        external=SideValues(Decimal(".3"),Decimal("-8"),Decimal("9")),
        estimated_price=Decimal("4100"),point_size=Decimal("0.01"),
        price_digits=2, internal_entry_price=price,
    )


class MainPriceUnification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp=QApplication.instance() or QApplication([])
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        conf=gui.ConfigStore
        profiles=gui.ProfileStore
        with patch.object(gui,"ConfigStore",side_effect=lambda:conf(path=root/"config.json")),\
             patch.object(gui,"ProfileStore",side_effect=lambda data:profiles(data,path=root/"profiles.json")),\
             patch.object(gui.WindowController,"warm_ocr",return_value=None),\
             patch.object(gui.TradingHelperApp,"read_sheet",lambda self:None):
            self.w=gui.TradingHelperApp()
        self.w.instruction=instruction()
        self.w._show_instruction(self.w.instruction)
        self.w.show()
        self.qtapp.processEvents()
    def tearDown(self):
        self.w.close()
        self.w.deleteLater()

    def test_edit_duplicate_hidden_primary_field_visible(self):
        self.w.switch_workspace("編輯")
        group=self.w.edit_page.findChild(gui.QGroupBox,"editManualEntryGroup")
        self.assertIsNotNone(group)
        self.assertFalse(group.isVisible())
        self.w.switch_workspace("交易")
        self.assertTrue(self.w.parameter_inputs["internal_entry_price"].isVisible())

    def test_write_and_readback_only_then_enable_manual_override(self):
        w=self.w
        with patch.object(w,"draw_tradingview") as draw,\
             patch.object(w,"_write_trade_parameter_values") as write:
            w.parameter_inputs["internal_entry_price"].setText("4104.60")
            w.update_all_trade_parameters()
            draw.assert_not_called()
            self.assertIsNone(w.manual_entry_price)
            self.assertEqual(w._primary_entry_price_pending,Decimal("4104.60"))
            self.assertEqual(write.call_args.args[0]["internal_entry_price"],"4104.60")
            w._show_instruction(instruction(Decimal("4104.60")))
            self.assertEqual(w.manual_entry_price,Decimal("4104.60"))
            self.assertIsNone(w._primary_entry_price_pending)
            draw.assert_not_called()

    def test_stale_price_does_not_enable_override_and_failed_write_clears(self):
        w=self.w
        with patch.object(w,"_write_trade_parameter_values"):
            w.parameter_inputs["internal_entry_price"].setText("4104.60")
            w.update_all_trade_parameters()
        w._show_instruction(instruction(Decimal("4100")))
        self.assertIsNone(w.manual_entry_price)
        self.assertEqual(w._primary_entry_price_pending,Decimal("4104.60"))
        with patch.object(gui.QMessageBox,"critical"):
            w._show_error("mock write failed")
        self.assertIsNone(w._primary_entry_price_pending)
        self.assertIsNone(w.manual_entry_price)


if __name__ == "__main__":
    unittest.main()

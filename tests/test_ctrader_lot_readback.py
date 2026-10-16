"""Offline regression for cTrader quantity UIA display (e.g. '0.74 Lots').
Synthetic native grid only; no broker mouse/keyboard access.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.auto_entry import DemoAccount, AutoEntryWorkflow
from trading_helper.windows import AutomationError


class Node:
    def __init__(self, kind, content, rect, aid=""):
        self.element_info=SimpleNamespace(control_type=kind,automation_id=aid)
        self.text=content
        self.r=SimpleNamespace(left=rect[0],top=rect[1],right=rect[2],bottom=rect[3])
    def window_text(self):return self.text
    def rectangle(self):return self.r


class Grid(Node):
    headers=("symbol","quantity","direction","entry price","sl","tp","created (utc+0)")
    values=("XAUUSD","0.74 Lots","SELL","4170.91","4200.20","4137.12","2026-10-15 22:02")
    def __init__(self, vals=None):
        super().__init__("DataGrid","",(0,0,1400,300))
        vals=vals or self.values
        self.heads=[
            Node("HeaderItem",key,(i*190,0,i*190+179,30))
            for i,key in enumerate(self.headers)
        ]
        self.row=Node("DataItem","",(0,60,1400,110))
        self.row.descendants=lambda: [
            Node("Text",val,(i*190+10,70,i*190+160,92))
            for i,val in enumerate(vals)
        ]
    def descendants(self,control_type):
        if control_type=="DataItem":return [self.row]
        if control_type=="HeaderItem":return self.heads
        raise ValueError(control_type)


class CTraderLotReadbackTests(unittest.TestCase):
    def setUp(self):
        self.port=DemoUiBrokerPort(MagicMock(),lambda s:None)
        self.demo=DemoAccount("cTrader","10000000","Demo Broker",True,True)

    def test_single_and_plural_native_lots(self):
        for text,amount in [
            ("0.74 Lots","0.74"),
            ("1 Lot","1"),
            ("0.74 lots","0.74"),
            ("1.25","1.25"),
            ("1,25 Lots","1.25"),
            ("1.000,25 Lots","1000.25"),
        ]:
            with self.subTest(value=text):
                self.assertEqual(
                    self.port._ctrader_quantity_lots(text),Decimal(amount)
                )

    def test_native_grid_yields_confirmable_position_and_volume(self):
        grid=Grid()
        self.port._ctrader_grid=lambda *args:grid
        positions=self.port._ctrader_positions(
            "cTrader","internal",self.demo
        )
        self.assertEqual(len(positions),1)
        pos=positions[0]
        self.assertEqual(pos.volume,Decimal("0.74"))
        self.assertEqual(pos.direction,"SELL")
        self.assertEqual(pos.entry_price,Decimal("4170.91"))
        self.assertEqual(pos.sl,Decimal("4200.20"))
        self.assertEqual(pos.tp,Decimal("4137.12"))
        AutoEntryWorkflow._validate_position(
            pos,"cTrader","SELL",Decimal("0.74"),self.demo,"GOLD"
        )

    def test_no_quantity_parse_of_arbitrary_units(self):
        for raw in (
            "0.74 Lots USD", "0.74 EUR", "Lots 0.74",
            "abc Lots", "0.74% Lots", "0.74xLots", "",
            "1e999 Lots", "-1 Lots","0 Lots",
        ):
            with self.subTest(raw=raw),self.assertRaises(AutomationError):
                self.port._ctrader_quantity_lots(raw)

    def test_price_parser_remains_strict(self):
        with self.assertRaisesRegex(AutomationError,"不可辨識"):
            self.port._decimal("4170.90 Lots")
        self.assertEqual(self.port._decimal("4170.90"),Decimal("4170.90"))

    def test_native_grid_rejects_bad_quantity_before_confirming(self):
        vals=list(Grid.values)
        vals[1]="0.74 Something"
        self.port._ctrader_grid=lambda *args:Grid(tuple(vals))
        with self.assertRaises(AutomationError):
            self.port._ctrader_positions("cTrader","internal",self.demo)


if __name__=="__main__":
    unittest.main()

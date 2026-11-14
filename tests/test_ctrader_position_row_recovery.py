"""Synthetic UIA rows only: no terminal or transaction is operated."""
from decimal import Decimal as D
from types import SimpleNamespace as NS
from unittest.mock import MagicMock,patch
import unittest

from trading_helper.auto_entry import DemoAccount
from trading_helper.automation import PlatformAutomation
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.entry_status_report import build_entry_status_report,summarize_interruption_reason
from trading_helper.windows import AutomationError,WindowController,WindowInfo


class Node:
    def __init__(self,text,kind,rect,children=()):
        self.text,self.rect,self.nodes=text,rect,children
        self.element_info=NS(control_type=kind)
    def window_text(self): return self.text
    def rectangle(self): return self.rect
    def is_visible(self): return True
    def descendants(self,**_): return self.nodes


class PositionRowRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.automation=NS(emergency=NS(guard=MagicMock()),windows=MagicMock())
        self.port=DemoUiBrokerPort(self.automation,MagicMock())
        self.account=DemoAccount("cTrader","111111","",None,True)
        headers=("Symbol","Quantity","Direction","Entry price","SL","TP","Created (UTC+0)")
        values=("XAUUSD","0.4 Lots","Buy","4100.25","4090.25","4120.25","2026-01-01 12:00:00")
        self.headers=[Node(h,"HeaderItem",NS(left=i*100,right=(i+1)*100,top=0,bottom=20)) for i,h in enumerate(headers)]
        children=[Node(v,"Text",NS(left=i*100+10,right=i*100+60,top=30,bottom=50)) for i,v in enumerate(values)]
        self.row=Node("","DataItem",NS(left=0,right=700,top=25,bottom=55),children)
        self.grid=NS(iface_grid=NS(CurrentRowCount=1),descendants=MagicMock())
        self.port._ctrader_grid=lambda *args:self.grid
        self.row_reads=[]
        def descendants(control_type):
            if control_type=="HeaderItem": return self.headers
            return self.row_reads.pop(0) if self.row_reads else []
        self.grid.descendants.side_effect=descendants

    def test_transient_tree_update_gets_one_fresh_read_without_native_fallback(self):
        self.row_reads=[[],[self.row]]
        with patch.object(self.port,"_ctrader_native_row") as native:
            positions=self.port._ctrader_positions("cTrader","internal",self.account)
        native.assert_not_called()
        self.assertEqual(len(positions),1)
        self.assertEqual(positions[0].entry_price,D("4100.25"))
        self.automation.windows.click.assert_not_called()

    def test_missing_visual_row_uses_native_grid_then_validates_all_columns(self):
        with patch.object(self.port,"_ctrader_native_row",return_value=self.row) as native:
            positions=self.port._ctrader_positions("cTrader","internal",self.account)
        native.assert_called_once_with(self.grid,0)
        p=positions[0]
        self.assertEqual((p.account_id,p.symbol,p.direction,p.volume,p.sl,p.tp),
            ("111111","XAUUSD","BUY",D("0.4"),D("4090.25"),D("4120.25")))
        self.automation.windows.click.assert_not_called()

    def test_unreadable_native_row_is_unknown_and_never_empty(self):
        with patch.object(self.port,"_ctrader_native_row",side_effect=RuntimeError("virtualized")):
            with self.assertRaisesRegex(AutomationError,"不能據此判定未進場"):
                self.port._ctrader_positions("cTrader","internal",self.account)

    def test_native_row_missing_column_cannot_confirm_a_fill(self):
        self.row.nodes=self.row.nodes[:-1]
        with patch.object(self.port,"_ctrader_native_row",return_value=self.row):
            with self.assertRaisesRegex(AutomationError,"沒有唯一原生讀值"):
                self.port._ctrader_positions("cTrader","internal",self.account)

    def test_stable_zero_count_can_confirm_empty_without_native_lookup(self):
        self.grid.iface_grid.CurrentRowCount=0
        with patch.object(self.port,"_ctrader_native_row") as native:
            self.assertEqual(self.port._ctrader_positions("cTrader","internal",self.account),())
        native.assert_not_called()

    def test_duplicate_native_rows_cannot_be_counted_as_two_positions(self):
        self.grid.iface_grid.CurrentRowCount=2
        with patch.object(self.port,"_ctrader_native_row",return_value=self.row):
            with self.assertRaisesRegex(AutomationError,"識別碼重複"):
                self.port._ctrader_positions("cTrader","internal",self.account)

    def test_grid_pattern_cell_is_resolved_to_its_row_without_realizing_or_clicking(self):
        cell=NS(element_info=NS(control_type="Custom"),parent=MagicMock(return_value=self.row))
        self.grid.iface_grid.GetItem=MagicMock(return_value=object())
        with patch("pywinauto.uia_element_info.UIAElementInfo"),patch(
            "pywinauto.controls.uiawrapper.UIAWrapper",return_value=cell
        ):
            self.assertIs(self.port._ctrader_native_row(self.grid,0),self.row)
        self.grid.iface_grid.GetItem.assert_called_once_with(0,0)
        cell.parent.assert_called_once()

    def test_receipt_distinguishes_read_failure_from_missing_entry(self):
        reason="場內（cTrader）：cTrader 持倉表資料列與原生列數不一致；目前持倉狀態未知。"
        report=build_entry_status_report({"confirmed_legs":{"external":"TEST-E"}},
            success=False,sync_requested=True,tv_requested=False,reason=reason,
            internal_platform="cTrader",external_platform="MT5")
        self.assertIn("場內（cTrader）：持倉讀取失敗，成交待核對",report["message"])
        self.assertIn("場外（MT5）：已確認進場",report["message"])
        self.assertIn("勿直接重複進場",summarize_interruption_reason(reason))


class NativeAccountSpeedTests(unittest.TestCase):
    def test_account_inspection_uses_the_installed_uia_query_contract_for_both_roles(self):
        from pywinauto.uia_defines import IUIA
        number=NS(is_visible=lambda:True,window_text=lambda:"111111",
                  element_info=NS(automation_id="CTraderAccountNumberTextBlock_AId"))
        unrelated=NS(is_visible=lambda:True,window_text=lambda:"999999",
                     element_info=NS(automation_id="OtherLabel"))
        queries=[]
        def descendants(**kwargs):
            IUIA().build_condition(**kwargs)
            queries.append(kwargs)
            return [unrelated,number]
        root=NS(descendants=descendants)
        port=DemoUiBrokerPort(NS(),lambda _:None)
        with patch("pywinauto.Desktop",return_value=NS(window=lambda **_:root)):
            for role in ("internal","external"):
                account=port.inspect_account("cTrader",role,_window=WindowInfo(1,"Test",0,0,800,600))
                self.assertEqual(account.account_id,"111111")
        self.assertEqual(queries,[{"control_type":"Text"}]*2)

    def test_native_account_avoids_ocr_but_mismatch_and_ambiguity_still_stop(self):
        windows=WindowController(NS(guard=lambda:None))
        windows.read_account_number=MagicMock(return_value="111111")
        flow=PlatformAutomation({},windows,NS(guard=lambda:None),MagicMock())
        profile={"account_number":{"internal":"111111"},"points":{"account_number":{}}}
        profile["points"]["account_number"]={"x":.5}
        node=NS(is_visible=lambda:True,window_text=lambda:"111111",
                element_info=NS(automation_id="CTraderAccountNumberTextBlock_AId"))
        def descendants(control_type=None):
            # Exercise the installed UIA condition builder, not permissive kwargs.
            from pywinauto.uia_defines import IUIA
            IUIA().build_condition(control_type=control_type)
            return root.nodes
        root=NS(descendants=descendants,nodes=[node])
        window=WindowInfo(1,"Test",0,0,800,600)
        with patch("pywinauto.Desktop",return_value=NS(window=lambda **_:root)):
            flow._verify_ctrader_account("cTrader",profile,"internal",window)
            windows.read_account_number.assert_not_called()
            node.window_text=lambda:"222222"
            with self.assertRaisesRegex(AutomationError,"帳號不符"):
                flow._verify_ctrader_account("cTrader",profile,"internal",window)
            root.nodes=[node,node]
            with self.assertRaisesRegex(AutomationError,"不唯一"):
                flow._verify_ctrader_account("cTrader",profile,"internal",window)
            root.nodes=[]
            flow._verify_ctrader_account("cTrader",profile,"internal",window)
            windows.read_account_number.assert_called_once()


if __name__ == "__main__": unittest.main()

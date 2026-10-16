"""Synthetic read-only UIA test fixtures reflecting observed 2026-10-16 dialogs."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from trading_helper.position_calibration import (
    POSITION_GRID_KEYS, POSITION_EDIT_KEYS,
    select_broker_main_window, select_modify_dialog, scan_position_grid,
    scan_open_modify_dialog,
)

class R:
    def __init__(self,l,t,r,b):
        self.left=l; self.top=t;self.right=r;self.bottom=b
    def width(self): return self.right-self.left
    def height(self):return self.bottom-self.top

class Node:
    def __init__(self,kind="",aid="",name="",rect=None,visible=True,enabled=True):
        self.kind=kind
        self.element_info=NS(control_type=kind,automation_id=aid)
        self.name=name
        self.rect=R(*(rect or (0,0,20,20)))
        self.visible=visible
        self.enabled=enabled
        self.children=[]
    def window_text(self):return self.name
    def text(self):return self.name
    def rectangle(self):return self.rect
    def is_visible(self):return self.visible
    def is_enabled(self):return self.enabled
    def descendants(self,control_type=None):
        return ([n for n in self.children if n.kind==control_type]
                if control_type else list(self.children))
    def class_name(self):return self.kind
    def control_id(self):return int(self.element_info.automation_id)

class BrokerPositionCalibrationTests(unittest.TestCase):
    def test_main_selection_never_uses_ctrader_modify_popup(self):
        modal=NS(handle=1,title="Modify order or position - cTrader")
        main=NS(handle=2,title="cTrader 5.10.20")
        lookup=lambda h:999
        self.assertEqual(select_broker_main_window(modal,[modal,main],"cTrader",lookup),main)
        self.assertEqual(select_modify_dialog(main,[modal,main],"cTrader",lookup),modal)

    def test_title_binding_rechecks_visible_terminals_not_first_modal(self):
        main=NS(handle=2,title="cTrader 5.10.20")
        modal=NS(handle=1,title="Modify order or position - cTrader")
        selected=NS(handle=3,title="Another cTrader helper")
        windows=[selected,modal,main]
        lookup=lambda h:99 if h in (main.handle,modal.handle) else 17
        self.assertEqual(
            select_broker_main_window(
                selected,windows,"cTrader",lookup,binding_pattern="cTrader",
            ),main
        )
        self.assertIsNone(
            select_broker_main_window(
                modal,[modal],"cTrader",lookup,binding_pattern="cTrader",
            )
        )

    def test_mt5_native_position_title_not_confused_with_order(self):
        main=NS(handle=3,title="55512345 - ICMarketsSC-Demo - [XAUUSD,H1]")
        modal=NS(handle=4,title="持倉: #8765432101 buy 0.16 XAUUSD 4169.30 sl: 4135.57 tp: 4174.62")
        order=NS(handle=5,title="Order: XAUUSD")
        lookup=lambda h:987
        self.assertEqual(select_broker_main_window(modal,[main,modal,order],"MT5",lookup),main)
        self.assertEqual(select_modify_dialog(main,[order,modal],"MT5",lookup),modal)

    def test_ctrader_grid_ignores_two_empty_action_headers(self):
        grid=Node("DataGrid","PositionListDataGrid_AId")
        row=Node("DataItem",rect=(0,60,1300,90))
        headers=[
            Node("HeaderItem",name=name,rect=(120*i,20,120*i+100,40))
            for i,name in enumerate(["Symbol","Quantity","Direction","Entry price","TP","SL","",""])
        ]
        grid.children=[row,*headers]
        root=Node("Window")
        root.children=[grid]
        with patch("pywinauto.Desktop") as mock:
            mock.return_value.window.return_value=root
            result=scan_position_grid(100,"cTrader",tuple((k,k) for k in POSITION_GRID_KEYS))
        self.assertFalse(result.warnings)
        self.assertEqual(set(result.candidates),set(POSITION_GRID_KEYS))
        self.assertEqual(result.candidates["position_order_row"].rect,(480,60,580,90))

    def test_ctrader_pips_first_price_second_and_disabled_protect(self):
        root=Node("Window")
        controls=[
            Node("CheckBox","CheckBoxStopLoss_AId","Stop loss",(294,510,404,528)),
            Node("CheckBox","CheckBoxTakeProfit_AId","Take profit 1",(578,510,709,528)),
            Node("CheckBox","CheckBoxTakeProfit_AId","Take profit 2",(578,668,709,686)),
        ]
        for x,t in ((294,537),(294,567),(294,596),
                    (578,537),(578,567),(578,596)):
            controls.append(Node("Edit","SpinnerContent_AId",str(t),(x,t,x+115,t+24)))
        controls.append(Node("Button","ProtectButton_AId","Protect",
                             (294,851,716,875),enabled=False))
        root.children=controls
        with patch("pywinauto.Desktop") as mock:
            mock.return_value.window.return_value=root
            result=scan_open_modify_dialog(99,"cTrader",tuple((k,k) for k in POSITION_EDIT_KEYS))
        self.assertEqual(set(result.candidates),set(POSITION_EDIT_KEYS))
        self.assertEqual(result.candidates["position_sl_input"].rect,(294,567,409,591))
        self.assertEqual(result.candidates["position_tp_input"].rect,(578,567,693,591))
        self.assertEqual(result.candidates["position_modify_confirm"].rect,(294,851,716,875))

    def test_mt5_modification_uses_price_ids_not_pip_ids(self):
        root=Node("Window")
        root.children=[
            Node("Edit","10334",rect=(734,337,827,361)),
            Node("Edit","10423",rect=(874,337,967,361)),
            Node("Edit","10336",rect=(734,371,827,395)),
            Node("Edit","10345",rect=(874,371,967,395)),
            Node("Button","10351",rect=(647,675,1120,703),enabled=False),
        ]
        with patch("pywinauto.Desktop") as mock:
            mock.return_value.window.return_value=root
            result=scan_open_modify_dialog(99,"MT5",tuple((k,k) for k in POSITION_EDIT_KEYS))
        self.assertEqual(set(result.candidates),set(POSITION_EDIT_KEYS))
        self.assertEqual(result.candidates["position_sl_input"].rect,(734,337,827,361))
        self.assertEqual(result.candidates["position_tp_input"].rect,(734,371,827,395))
        self.assertEqual(result.candidates["position_modify_confirm"].rect,(647,675,1120,703))

    def test_mt5_ownerdrawn_blank_rows_only_allow_low_confidence_preview(self):
        listview=Node("SysListView32","10328",rect=(27,816,1920,963))
        listview.item_count=lambda:2
        listview.columns=lambda:[object()]*10
        def item(i,j):
            return Node("ListItem",name="",rect=(j*180,25+i*25,(j+1)*180,50+i*25))
        listview.get_item=item
        root=Node("Window");root.children=[listview]
        with patch("pywinauto.Desktop") as mock:
            mock.return_value.window.return_value=root
            result=scan_position_grid(99,"MT5",tuple((k,k) for k in POSITION_GRID_KEYS))
        self.assertEqual(len(result.candidates),3)
        self.assertEqual(result.candidates["position_order_row"].rect,(1107,841,1287,866))
        self.assertIn("低信度",result.candidates["position_order_row"].evidence)
        self.assertIn("不可用於自動成交",result.candidates["position_order_row"].evidence)

if __name__=="__main__":
    unittest.main()

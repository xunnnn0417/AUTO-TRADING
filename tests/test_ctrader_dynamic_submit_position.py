"""Read-only synthetic checks for dynamic cTrader Place order position.
Never clicks any actual trading window.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError, WindowInfo


class FakeNativeButton:
    def __init__(self, rect=(1471, 720, 1867, 743), parents=None):
        self.element_info=SimpleNamespace(
            control_type="Button",
            automation_id=(
                "Orders_Create_MarketOrderPlaceButtonControl__Button_"
                "NewOrdersWindowPlaceOrder_AId"
            )
        )
        self.rect=rect
        self.parents=parents or (
            "AspPlaceOrderButton_AId", "PropertySectionView_AId"
        )
        self.level=0

    def is_visible(self):return True
    def is_enabled(self):return True
    def rectangle(self):
        a,b,c,d=self.rect
        return SimpleNamespace(left=a, top=b, right=c, bottom=d)
    def parent(self):
        if self.level>=len(self.parents):
            raise AssertionError("unexpected parent traversal")
        p=SimpleNamespace(element_info=SimpleNamespace(
            automation_id=self.parents[self.level]
        ))
        self.level+=1
        p.parent=lambda: self.parent()
        return p


class DynamicCTraderPlaceOrderTests(unittest.TestCase):
    def setUp(self):
        self.win=WindowInfo(330,"cTrader 5.10.20",-9,-9,1929,1029)
        self.point=dict(x_px=1678,y_px=597,window_width=1938,
                        window_height=1038)
        self.profile={"points":{"order_submit_button":self.point}}
        self.automation=MagicMock()
        self.automation.windows.screen_point.side_effect=(
            lambda w,p:(w.left+p["x_px"],w.top+p["y_px"])
        )
        self.automation.windows.relative_point.side_effect=(
            lambda w,x,y:dict(
                x_px=x-w.left,y_px=y-w.top,
                window_width=w.width,window_height=w.height
            )
        )
        self.port=DemoUiBrokerPort(self.automation,lambda message:None)
        self.port.inspect_account=MagicMock()
        self.port.verify_order_form=MagicMock()
        self.port._form_window=MagicMock(return_value=(self.profile,self.win))
        self.buttons=[FakeNativeButton()]

    def submit(self):
        desktop=SimpleNamespace(window=lambda handle:SimpleNamespace(
            descendants=lambda **kwargs:list(self.buttons)
        ))
        with patch("pywinauto.Desktop",return_value=desktop):
            self.port.submit_once("cTrader","internal","BUY",0.16,"key")

    def test_132_pixel_vertical_shift_targets_unique_real_button(self):
        self.submit()
        self.port.verify_order_form.assert_called_once()
        self.automation.windows.click.assert_called_once()
        w,p=self.automation.windows.click.call_args.args
        self.assertEqual(w,self.win)
        self.assertEqual(
            self.automation.windows.screen_point(w,p),(1669,731)
        )

    def test_no_shift_keeps_saved_calibration(self):
        self.point["y_px"]=740
        self.submit()
        self.automation.windows.click.assert_called_once_with(
            self.win,self.point
        )

    def test_large_shift_never_clicks(self):
        self.point["y_px"]=300
        with self.assertRaisesRegex(AutomationError,"重新校準"):
            self.submit()
        self.automation.windows.click.assert_not_called()

    def test_horizontal_misalignment_never_clicks(self):
        self.point["x_px"]=500
        with self.assertRaises(AutomationError):
            self.submit()
        self.automation.windows.click.assert_not_called()

    def test_wrong_parent_never_clicks(self):
        self.buttons=[FakeNativeButton(
            parents=("AspNewMarketOrderControl_AId","SomethingElse")
        )]
        with self.assertRaisesRegex(AutomationError,"下單面板"):
            self.submit()
        self.automation.windows.click.assert_not_called()

    def test_multiple_buttons_never_clicks(self):
        self.buttons=[FakeNativeButton(),FakeNativeButton()]
        with self.assertRaisesRegex(AutomationError,"唯一"):
            self.submit()
        self.automation.windows.click.assert_not_called()

    def test_no_button_never_clicks(self):
        self.buttons=[]
        # Empty fresh UIA inventory is rejected before button matching.
        with self.assertRaisesRegex(AutomationError,"UIA 控制項清單"):
            self.submit()
        self.automation.windows.click.assert_not_called()


if __name__=="__main__":
    unittest.main()

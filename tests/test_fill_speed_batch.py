"""Speed-path correctness and safety: native UIA snapshot once per round.

Everything in this test suite is mocked. No broker window is opened or clicked.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from trading_helper.windows import WindowController,WindowInfo,AutomationError
from trading_helper.automation import PlatformAutomation


class UIControl:
    def __init__(self,kind,rect,value="",name="",selected=False,checked=0):
        self.element_info=SimpleNamespace(control_type=kind)
        self.rect=SimpleNamespace(
            left=rect[0],top=rect[1],right=rect[2],bottom=rect[3]
        )
        self.value=value
        self.name=name
        self.selected=selected
        self.checked=checked
    def rectangle(self):return self.rect
    def is_visible(self):return True
    def is_enabled(self):return True
    def get_value(self):return self.value
    def window_text(self):return self.name
    def is_selected(self):return self.selected
    def get_toggle_state(self):return self.checked

def pt(x,y):
    return dict(x_px=x,y_px=y,window_width=800,window_height=600)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.window=WindowInfo(1234,"mock cTrader",0,0,800,600)
        self.controller=WindowController(SimpleNamespace(guard=lambda:None))
        self.controller.focus=MagicMock(return_value=self.window)
        self.count={"inventories":0}
        self.edits={
            "lot_input":UIControl("Edit",(100,100,160,125),"0.74"),
            "sl_input":UIControl("Edit",(100,140,160,166),"-527"),
            "tp_input":UIControl("Edit",(300,140,360,166),"3378"),
        }
        self.radios=[
            UIControl("RadioButton",(240,50,350,85),selected=True),
            UIControl("RadioButton",(100,50,210,85),selected=False),
        ]
        self.checks=[
            UIControl("CheckBox",(100,182,180,203),name="Stop loss",checked=1),
            UIControl("CheckBox",(300,182,380,203),name="Take profit 1",checked=1),
        ]
        self.points={
            "lot_input":pt(130,110),"sl_input":pt(130,151),
            "tp_input":pt(330,151),
            "buy_button":pt(275,65),"sell_button":pt(155,65),
            "sl_checkbox":pt(138,202),"tp_checkbox":pt(338,202)
        }

    def read(self,ctrader=True):
        def enumerate_controls():
            self.count["inventories"]+=1
            return list(self.edits.values())+self.radios+self.checks
        root=SimpleNamespace(descendants=enumerate_controls)
        fake=SimpleNamespace(window=lambda handle:root)
        with patch("pywinauto.Desktop",return_value=fake), \
             patch.object(self.controller,"read_edit_value",
                          side_effect=AssertionError("old per-field scan")), \
             patch("pyautogui.click",
                   side_effect=AssertionError("read snapshot must never click")):
            return self.controller.read_fill_snapshot(
                self.window,self.points,ctrader=ctrader
            )

    def test_all_values_direction_checkboxes_from_one_inventory(self):
        result=self.read()
        self.assertEqual(self.count["inventories"],1)
        self.assertEqual(result["values"],{
            "lot_input":"0.74","sl_input":"-527","tp_input":"3378"
        })
        self.assertEqual(result["direction"],"BUY")
        self.assertEqual(result["checks"],
                         {"sl_checkbox":True,"tp_checkbox":True})
        self.controller.focus.assert_called_once()

    def test_snapshot_refreshes_values_each_verification_round(self):
        self.read()
        self.edits["sl_input"].value="-528"
        result=self.read()
        self.assertEqual(result["values"]["sl_input"],"-528")
        self.assertEqual(self.count["inventories"],2)

    def test_duplicate_overlap_blocks_instead_of_guessing(self):
        self.edits["extra"]=UIControl("Edit",(102,102,165,124),"99")
        with self.assertRaisesRegex(AutomationError,"沒有唯一"):
            self.read()

    def test_direction_ambiguous_stops(self):
        self.radios[1].selected=True
        with self.assertRaisesRegex(AutomationError,"沒有唯一選擇"):
            self.read()

    def test_checkbox_off_is_reported_not_assumed(self):
        self.checks[0].checked=0
        self.assertFalse(self.read()["checks"]["sl_checkbox"])

    def test_mt5_only_reads_three_edits_once(self):
        result=self.read(ctrader=False)
        self.assertEqual(self.count["inventories"],1)
        self.assertIsNone(result["direction"])
        self.assertFalse(result["checks"])

    def test_focus_does_not_wait_if_exact_window_is_already_foreground(self):
        original=self.controller.focus
        self.controller.focus=WindowController.focus.__get__(self.controller)
        self.controller._refresh=MagicMock(return_value=self.window)
        with patch("trading_helper.windows.user32") as u, \
             patch("trading_helper.windows.time.sleep") as wait:
            u.IsIconic.return_value=0
            u.GetForegroundWindow.return_value=self.window.handle
            actual=self.controller.focus(self.window)
            self.assertEqual(actual,self.window)
            u.SetForegroundWindow.assert_not_called()
            wait.assert_not_called()
            u.GetForegroundWindow.return_value=5
            self.controller.focus(self.window)
            u.SetForegroundWindow.assert_called_once_with(self.window.handle)
            wait.assert_called_once_with(0.2)


class BatchWorkflowTests(unittest.TestCase):
    def test_batch_one_scan_per_pass_and_three_attempts_still_apply(self):
        from test_fill_verification import FillVerificationTests
        test=FillVerificationTests("test_correct_mt5_values_no_extra_writes")
        test.setUp()
        test.fake.poison={"tp_input":1}
        test.seed()
        calls=[]
        def read_fill_snapshot(w,pts,ctrader=False):
            calls.append([test.fake.values.get(k) for k in
                          ("lot_input","sl_input","tp_input")])
            return {
                "values":{k:test.fake.values.get(k,"0") for k in
                          ("lot_input","sl_input","tp_input")},
                "direction":None,"checks":{}
            }
        test.fake.read_fill_snapshot=read_fill_snapshot
        test.fake.read_edit_value=lambda *a:(_ for _ in ()).throw(
            AssertionError("per-field read should not be used")
        )
        test.verify_mt5()
        self.assertEqual(len(calls),2)
        self.assertEqual(
            [key for _,key,_ in test.fake.writes].count("tp_input"),2
        )


if __name__ == "__main__":
    unittest.main()

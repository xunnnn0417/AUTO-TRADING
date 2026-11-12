"""Native UIA readback is strict and read-only; fake elements only."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from trading_helper.windows import AutomationError, WindowController, WindowInfo


class FakeEdit:
    def __init__(self,rect,value,kind="Edit"):
        self.box=SimpleNamespace(left=rect[0],top=rect[1],right=rect[2],bottom=rect[3])
        self.element_info=SimpleNamespace(control_type=kind)
        self.value=value
    def rectangle(self):return self.box
    def is_visible(self):return True
    def is_enabled(self):return True
    def get_value(self):
        if isinstance(self.value,Exception):raise self.value
        return self.value


class NativeReadbackTests(unittest.TestCase):
    def setUp(self):
        self.window=WindowInfo(101,"Fake broker",0,0,800,600)
        self.point={
            "window_width":800,"window_height":600,
            "x_px":110,"y_px":110,
        }
        self.controller=WindowController(SimpleNamespace(guard=lambda:None))
        self.controller.focus=MagicMock(return_value=self.window)
        self.ctrls=[FakeEdit((95,100,140,125),"0.740")]
    def read(self):
        root=SimpleNamespace(descendants=lambda:self.ctrls)
        desktop=SimpleNamespace(window=lambda handle:root)
        with patch("pywinauto.Desktop",return_value=desktop), \
             patch("pyautogui.click",side_effect=AssertionError("read clicked!")), \
             patch("pyautogui.hotkey",side_effect=AssertionError("read typed!")):
            return self.controller.read_edit_value(self.window,self.point)
    def test_reads_one_calibrated_numeric_cell(self):
        self.assertEqual(self.read(),"0.740")
    def test_rejects_overlapping_fields(self):
        self.ctrls.append(FakeEdit((100,100,147,130),"999"))
        with self.assertRaisesRegex(AutomationError,"唯一定位"):
            self.read()
    def test_rejects_unreadable_native_edit(self):
        self.ctrls=[FakeEdit((95,100,140,125),RuntimeError("Value not supported"))]
        with self.assertRaisesRegex(AutomationError,"不支援可靠讀回"):
            self.read()
    def test_rejects_empty(self):
        self.ctrls[0].value=""
        with self.assertRaisesRegex(AutomationError,"空白"):
            self.read()
    def test_rejects_off_target(self):
        self.ctrls=[FakeEdit((300,330,450,400),"0.74")]
        with self.assertRaisesRegex(AutomationError,"找到 0 個"):
            self.read()

    def test_fill_snapshot_refreshes_once_when_calibrated_field_is_temporarily_missing(self):
        points={
            "lot_input":dict(window_width=800,window_height=600,x_px=110,y_px=110),
            "sl_input":dict(window_width=800,window_height=600,x_px=210,y_px=210),
            "tp_input":dict(window_width=800,window_height=600,x_px=310,y_px=310),
        }
        partial=[
            FakeEdit((95,100,140,125),"0.740"),
            FakeEdit((295,300,340,325),"3378"),
        ]
        complete=partial+[FakeEdit((195,200,240,225),"-527")]
        roots=[
            SimpleNamespace(descendants=lambda:partial),
            SimpleNamespace(descendants=lambda:complete),
        ]
        desktop=SimpleNamespace(window=lambda handle:roots.pop(0))
        with patch("pywinauto.Desktop",side_effect=[desktop,desktop]), \
             patch("trading_helper.windows.time.sleep") as sleep:
            snapshot=self.controller.read_fill_snapshot(self.window,points)
        self.assertEqual(snapshot["values"],{
            "lot_input":"0.740","sl_input":"-527","tp_input":"3378",
        })
        sleep.assert_called_once_with(0.12)


if __name__=="__main__":
    unittest.main()

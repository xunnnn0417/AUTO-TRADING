"""cTrader SL/TP native ToggleState workflow, offline only: NEVER click real trading UI."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.windows import AutomationError, WindowController, WindowInfo


class FakeCheckbox:
    def __init__(self, name, rect, initial):
        self.name = name
        self.box = SimpleNamespace(left=rect[0],top=rect[1],
                                   right=rect[2],bottom=rect[3])
        self.state = initial
        self.enabled = True
    def window_text(self):
        return self.name
    def rectangle(self):
        return self.box
    def is_enabled(self):
        return self.enabled
    def is_visible(self):
        return True
    def get_toggle_state(self):
        return self.state


class CTraderCheckboxTests(unittest.TestCase):
    def setUp(self):
        self.window=WindowInfo(909,"cTrader",0,0,1938,1038)
        self.point_sl={
            "x_px":1545,"y_px":483,"window_width":1938,
            "window_height":1038
        }
        self.point_tp={
            "x_px":1810,"y_px":483,"window_width":1938,
            "window_height":1038
        }
        self.sl=FakeCheckbox("Stop loss",(1471,466,1602,483),0)
        self.tp=FakeCheckbox("Take profit 1",(1736,466,1867,483),0)
        self.extra=FakeCheckbox("Break-even",(1471,498,1602,515),0)
        self.ui=SimpleNamespace(
            descendants=lambda control_type:[self.sl,self.tp,self.extra]
        )
        self.controller=WindowController(SimpleNamespace(guard=lambda:None))
        self.controller.focus=MagicMock(return_value=self.window)
        self.controller._validate_calibrated_window=MagicMock()
        self.controller.screen_point=MagicMock(side_effect=lambda w,p:(
            p["x_px"],p["y_px"]
        ))

    def run_case(self,field,stop_click=False):
        clicked=[]
        def fake_click(x,y):
            clicked.append((x,y))
            if stop_click:
                return
            for ctrl in (self.sl,self.tp):
                r=ctrl.box
                if r.left<=x<r.right and r.top<=y<r.bottom:
                    ctrl.state=1-ctrl.state
                    return
            raise AssertionError("clicked outside checkbox")
        fake_desktop=SimpleNamespace(window=lambda handle:self.ui)
        with patch("pywinauto.Desktop",return_value=fake_desktop), \
             patch("pyautogui.click",side_effect=fake_click), \
             patch("pyautogui.screenshot",side_effect=AssertionError("No screenshots")):
            if field=="sl_checkbox":
                point=self.point_sl
            else:
                point=self.point_tp
            result=self.controller.refresh_checkbox_checked(
                self.window,point,field
            )
        return result,clicked

    def test_unchecked_sl_clicks_once_and_verifies_checked(self):
        clicks,coords=self.run_case("sl_checkbox")
        self.assertEqual(clicks,1)
        self.assertEqual(self.sl.state,1)
        self.assertEqual(coords,[(1536,474)])
        self.assertEqual(self.tp.state,0)
    def test_checked_sl_clicks_off_then_on_and_verifies_each(self):
        self.sl.state=1
        clicks,coords=self.run_case("sl_checkbox")
        self.assertEqual(clicks,2)
        self.assertEqual(coords,[(1536,474),(1536,474)])
        self.assertEqual(self.sl.state,1)
        self.assertEqual(self.tp.state,0)
    def test_unchecked_tp_clicks_once_and_verifies_checked(self):
        clicks,coords=self.run_case("tp_checkbox")
        self.assertEqual(clicks,1)
        self.assertEqual(coords,[(1801,474)])
        self.assertEqual(self.tp.state,1)
        self.assertEqual(self.sl.state,0)
    def test_checked_tp_clicks_twice_and_verifies_checked(self):
        self.tp.state=1
        clicks,coords=self.run_case("tp_checkbox")
        self.assertEqual(clicks,2)
        self.assertEqual(coords,[(1801,474),(1801,474)])
        self.assertEqual(self.tp.state,1)
    def test_checked_fast_toggle_reuses_one_uia_inventory(self):
        # Before optimization, the slow nested UIA inventory was scanned
        # multiple times for off/on on the same already checked box.
        self.sl.state=1
        count={"inventories":0}
        original=self.ui.descendants
        def counted(control_type):
            count["inventories"]+=1
            return original(control_type)
        self.ui.descendants=counted
        clicks,coords=self.run_case("sl_checkbox")
        self.assertEqual((clicks,len(coords),self.sl.state),(2,2,1))
        self.assertEqual(count["inventories"],1)

    def test_stale_element_reacquired_only_when_needed(self):
        self.sl.state=1
        attempts={"reads":0,"inventories":0}
        original_read=self.sl.get_toggle_state
        original_list=self.ui.descendants
        def temporary_stale():
            attempts["reads"]+=1
            if attempts["reads"]==2:
                raise RuntimeError("UIA element was re-created")
            return original_read()
        def counted(control_type):
            attempts["inventories"]+=1
            return original_list(control_type)
        self.sl.get_toggle_state=temporary_stale
        self.ui.descendants=counted
        clicks,_=self.run_case("sl_checkbox")
        self.assertEqual(clicks,2)
        self.assertEqual(self.sl.state,1)
        self.assertEqual(attempts["inventories"],2)

    def test_unknown_toggle_state_stops_without_clicks(self):
        self.sl.state=2
        with patch("pywinauto.Desktop",return_value=SimpleNamespace(
                  window=lambda handle:self.ui)), \
             patch("pyautogui.click") as click:
            with self.assertRaises(AutomationError):
                self.controller.refresh_checkbox_checked(
                    self.window,self.point_sl,"sl_checkbox"
                )
            click.assert_not_called()
    def test_missing_checkbox_stops_without_clicks(self):
        self.sl.name="Unrelated toggle"
        with patch("pywinauto.Desktop",return_value=SimpleNamespace(
                  window=lambda handle:self.ui)), \
             patch("pyautogui.click") as click:
            with self.assertRaises(AutomationError):
                self.controller.refresh_checkbox_checked(
                    self.window,self.point_sl,"sl_checkbox"
                )
            click.assert_not_called()
    def test_no_state_change_stops_no_blind_second_click(self):
        fake_desktop=SimpleNamespace(window=lambda handle:self.ui)
        with patch("pywinauto.Desktop",return_value=fake_desktop), \
             patch("pyautogui.click") as click:
            with self.assertRaises(AutomationError):
                self.controller.refresh_checkbox_checked(
                    self.window,self.point_sl,"sl_checkbox"
                )
            self.assertEqual(click.call_count,1)
    def test_changed_calibration_point_stops_before_click(self):
        self.point_sl["x_px"]=500
        with patch("pywinauto.Desktop",return_value=SimpleNamespace(
                  window=lambda handle:self.ui)), \
             patch("pyautogui.click") as click:
            with self.assertRaises(AutomationError):
                self.controller.refresh_checkbox_checked(
                    self.window,self.point_sl,"sl_checkbox"
                )
            click.assert_not_called()


if __name__=="__main__":
    unittest.main()

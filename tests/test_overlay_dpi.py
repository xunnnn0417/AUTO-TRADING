"""Regression tests for physical UIA to logical Qt coordinate conversion."""
import unittest
from PySide6.QtCore import QRect
from trading_helper.ui_inspector import logical_bounds_for_physical

class OverlayDpiTests(unittest.TestCase):
    def test_125_percent_on_primary_monitor(self):
        physical=(614,431,702,451)
        monitor=(0,0,1920,1080)
        logical=QRect(0,0,1536,864)
        self.assertEqual(logical_bounds_for_physical(physical,monitor,logical,1.25),QRect(491,345,71,16))

    def test_100_percent(self):
        self.assertEqual(logical_bounds_for_physical((614,431,702,451),(0,0,1920,1080),QRect(0,0,1920,1080),1),QRect(614,431,88,20))

    def test_150_percent(self):
        self.assertEqual(logical_bounds_for_physical((150,300,450,360),(0,0,1920,1080),QRect(0,0,1280,720),1.5),QRect(100,200,200,40))

    def test_monitor_offset_preserved_before_scaling(self):
        # Qt keeps monitor locations while scaling sizes on Windows.
        result=logical_bounds_for_physical((-1800,130,-1600,230),(-1920,0,0,1080),QRect(-1920,0,1536,864),1.25)
        self.assertEqual(result,QRect(-1824,104,160,80))

    def test_reject_mismatched_scale_or_screen(self):
        with self.assertRaises(ValueError):
            logical_bounds_for_physical((614,431,702,451),(0,0,1920,1080),QRect(0,0,1536,864),1)
        with self.assertRaises(ValueError):
            logical_bounds_for_physical((614,431,702,451),(0,0,1920,1080),QRect(0,0,1536,864),0)

    def test_reject_outside_monitor(self):
        with self.assertRaises(ValueError):
            logical_bounds_for_physical((1900,100,2000,125),(0,0,1920,1080),QRect(0,0,1536,864),1.25)

if __name__=="__main__":
    unittest.main()

import os,unittest
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication,QMainWindow,QTabBar
from trading_helper.calibration_status import completion,has_saved_coordinate
from trading_helper.gui import CalibrationDialog,CALIBRATION_TARGETS

def pt():
    return {"x":0.34,"y":0.46,"window_width":1600,"window_height":900}

class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def test_only_persisted_finite_normalized_coordinates_count(self):
        vals={"a":pt(),"b":{"x":1,"y":0},"c":{"x":float("nan"),"y":.3},
              "d":{"x":.2,"y":1.5},"e":None}
        self.assertEqual(completion(vals,["a","b","c","d","e"]),(2,5))
        self.assertFalse(has_saved_coordinate({"x":0.3}))
        self.assertTrue(has_saved_coordinate(pt()))

    def test_stage_saved_counts_and_red_dot_toggle(self):
        parent=QMainWindow()
        store={"platforms":{"cTrader":{"points":{}},"MT5":{"points":{}},
                            "TradingView":{"points":{}}},
               "ui":{"show_calibration_badges":True}}
        parent.store=SimpleNamespace(data=store)
        dlg=CalibrationDialog(parent,"cTrader")
        try:
            first=dlg._stage_keys[0]
            self.assertGreater(len(first),1)
            for key in first[:-1]:
                store["platforms"]["cTrader"]["points"][key]=pt()
            dlg._refresh_stage_progress()
            self.assertIn(f"({len(first)-1}/{len(first)})",
                          dlg._calibration_tabs.tabText(0))
            marker=dlg._calibration_tabs.tabBar().tabButton(
                0,QTabBar.RightSide)
            self.assertIsNotNone(marker)
            self.assertFalse(marker.isHidden())
            store["ui"]["show_calibration_badges"]=False
            dlg._refresh_stage_progress()
            self.assertTrue(marker.isHidden())
            self.assertIn(f"({len(first)-1}/{len(first)})",
                          dlg._calibration_tabs.tabText(0))
            store["ui"]["show_calibration_badges"]=True
            store["platforms"]["cTrader"]["points"][first[-1]]=pt()
            dlg._refresh_stage_progress()
            self.assertIn(f"({len(first)}/{len(first)})",
                          dlg._calibration_tabs.tabText(0))
            self.assertTrue(marker.isHidden())
        finally:
            dlg._hover_outline.close()
            dlg.close()
            parent.close()

    def test_tradingview_stage_progress_and_independent_badge_setting(self):
        parent=QMainWindow()
        parent.store=SimpleNamespace(data={
            "platforms":{"cTrader":{"points":{}},"MT5":{"points":{}},
                         "TradingView":{"points":{}}},
            "ui":{"show_calibration_badges":True}
        })
        dlg=CalibrationDialog(parent,"TradingView")
        try:
            self.assertEqual(len(dlg._stage_keys),1)
            self.assertEqual(len(dlg._stage_keys[0]),
                             len(CALIBRATION_TARGETS["TradingView"]))
            first=dlg._stage_keys[0][0]
            parent.store.data["platforms"]["TradingView"]["points"][first]=pt()
            dlg._refresh_stage_progress()
            total=len(dlg._stage_keys[0])
            self.assertIn(f"(1/{total})",dlg._calibration_tabs.tabText(0))
            marker=dlg._calibration_tabs.tabBar().tabButton(0,QTabBar.RightSide)
            self.assertFalse(marker.isHidden())
            parent.store.data["ui"]["show_calibration_badges"]=False
            dlg._refresh_stage_progress()
            self.assertTrue(marker.isHidden())
            self.assertIn(f"(1/{total})",dlg._calibration_tabs.tabText(0))
        finally:
            dlg._hover_outline.close()
            dlg.close()
            parent.close()

    def test_missing_ctrader_first_stage_from_full_16(self):
        all_keys=[k for k,_ in CALIBRATION_TARGETS["cTrader"]]
        first=all_keys[:9]
        saved={k:pt() for k in all_keys}
        for k in first:saved.pop(k)
        self.assertEqual(completion(saved,all_keys),(7,16))
        self.assertEqual(completion(saved,first),(0,9))
        self.assertEqual(completion(saved,all_keys[9:]),(7,7))

    def test_tiny_stage_notification_dot_size(self):
        parent=QMainWindow()
        parent.store=SimpleNamespace(data={
            "platforms":{"cTrader":{"points":{}},"MT5":{"points":{}},
                         "TradingView":{"points":{}}},
            "ui":{"show_calibration_badges":True}
        })
        dlg=CalibrationDialog(parent,"cTrader")
        try:
            for index in range(dlg._calibration_tabs.count()):
                marker=dlg._calibration_tabs.tabBar().tabButton(
                    index,QTabBar.RightSide)
                self.assertIsNotNone(marker)
                self.assertEqual((marker.width(),marker.height()),(6,6))
                self.assertIn("border-radius:3px", marker.styleSheet())
        finally:
            dlg._hover_outline.close()
            dlg.close()
            parent.close()

    def test_mt5_four_stages_total_consistent(self):
        parent=QMainWindow()
        parent.store=SimpleNamespace(data={
            "platforms":{"cTrader":{"points":{}},"MT5":{"points":{}},
                         "TradingView":{"points":{}}},
            "ui":{"show_calibration_badges":True}
        })
        dlg=CalibrationDialog(parent,"MT5")
        try:
            self.assertEqual(len(dlg._stage_keys),4)
            self.assertEqual(sum(map(len,dlg._stage_keys)),
                             len(CALIBRATION_TARGETS["MT5"]))
            self.assertEqual(dlg._calibration_tabs.count(),4)
            self.assertIn("(0/",dlg._calibration_tabs.tabText(0))
        finally:
            dlg._hover_outline.close()
            dlg.close()
            parent.close()

if __name__=="__main__":unittest.main()

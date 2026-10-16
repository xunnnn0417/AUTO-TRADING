"""Opt-in save tests use temporary configs and synthetic UIA only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import trading_helper.calibration_confirm as safe
from trading_helper.calibration_scan import Candidate, ScanReport
from trading_helper.windows import WindowInfo

PLATFORM="cTrader"

def scan(keys=("lot_input","sl_input")):
    r=ScanReport(PLATFORM,tuple((key,key) for key in keys))
    if "lot_input" in keys:
        r.candidates["lot_input"]=Candidate("lot_input",(505,320,595,340),"UIA")
    if "sl_input" in keys:
        r.candidates["sl_input"]=Candidate("sl_input",(610,350,730,370),"低信度")
    return r

class CandidatePointTests(unittest.TestCase):
    def setUp(self):
        self.main=WindowInfo(50,"cTrader",100,200,1100,800)
        self.windows=[self.main]
        self.pid=lambda handle: 7788 if handle==50 else -1

    def points(self,report,keys,windows=None,pid=None):
        return safe.candidate_calibration_points(
            report,keys,windows or self.windows,self.main,7788,pid or self.pid)

    def test_window_relative_coordinates_and_titles(self):
        points=self.points(scan(),["lot_input"])
        point=points["lot_input"]
        self.assertEqual(point["x_px"],450)
        self.assertEqual(point["y_px"],130)
        self.assertEqual(point["window_width"],1000)
        self.assertEqual(point["window_height"],600)
        self.assertEqual(point["x"],.45)
        self.assertAlmostEqual(point["y"],.216667)
        self.assertEqual(point["window_title"],"cTrader")

    def test_second_popup_uses_its_own_window_coordinates(self):
        popup=WindowInfo(99,"Modify Order #123",490,300,780,500)
        points=self.points(scan(["sl_input"]),["sl_input"],[self.main,popup],
                          lambda h:7788 if h in (50,99) else -1)
        point=points["sl_input"]
        self.assertEqual(point["x_px"],180)
        self.assertEqual(point["y_px"],60)
        self.assertEqual(point["window_width"],290)
        self.assertIn("Modify",point["window_title"])

    def test_position_grid_location_remains_bound_to_main_when_modal_overlaps(self):
        report=scan(("positions_entry_price",))
        report.candidates["positions_entry_price"]=Candidate(
            "positions_entry_price",(505,320,595,340),"main native grid"
        )
        popup=WindowInfo(99,"Modify order or position - cTrader",490,300,780,500)
        points=self.points(
            report,["positions_entry_price"],[self.main,popup],
            lambda h:7788 if h in (50,99) else -1,
        )
        self.assertEqual(points["positions_entry_price"]["x_px"],450)
        self.assertEqual(points["positions_entry_price"]["window_title"],"cTrader")

    def test_position_modify_location_remains_bound_to_scanned_modal(self):
        popup=WindowInfo(99,"Modify order or position - cTrader",490,300,780,500)
        report=scan(("position_sl_input",))
        report.candidates["position_sl_input"]=Candidate(
            "position_sl_input",(505,320,595,340),"modal native price"
        )
        result=safe.candidate_calibration_points(
            report,["position_sl_input"],[self.main,popup],popup,7788,
            lambda h:7788 if h in (50,99) else -1
        )
        self.assertEqual(result["position_sl_input"]["x_px"],60)
        self.assertIn("Modify",result["position_sl_input"]["window_title"])

    def test_unselected_or_unknown_never_saved(self):
        r=scan(("lot_input",))
        with self.assertRaises(safe.CalibrationConfirmationError):
            self.points(r,["sl_input"])
        with self.assertRaises(safe.CalibrationConfirmationError):
            self.points(r,[])
        with self.assertRaises(safe.CalibrationConfirmationError):
            self.points(r,["lot_input","lot_input"])

    def test_partial_scan_move_and_wrong_process_fail_closed(self):
        report=scan()
        report.warnings=("incomplete",)
        with self.assertRaises(safe.CalibrationConfirmationError):
            self.points(report,["lot_input"])
        with self.assertRaises(safe.CalibrationConfirmationError):
            self.points(scan(),["lot_input"],
                        [WindowInfo(50,"cTrader",102,200,1102,800)])
        with self.assertRaises(safe.CalibrationConfirmationError):
            self.points(scan(),["lot_input"],pid=lambda h:1234)

    def test_unrelated_or_ambiguous_dialogs_not_used(self):
        popup=WindowInfo(99,"MT5",490,300,780,500)
        report=scan(["sl_input"])
        # An unrelated process must not steal a point from the real main window.
        result=self.points(report,["sl_input"],[popup,self.main])
        self.assertEqual(result["sl_input"]["window_title"],"cTrader")
        same=WindowInfo(99,"Fake",100,200,1100,800)
        with self.assertRaises(safe.CalibrationConfirmationError):
            self.points(scan(),["lot_input"],[self.main,same],
                        lambda _:7788)

class ConfigBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder=Path(self.temp.name)
        self.config_path=folder/"config.json"
        self.profile_path=folder/"profiles.json"
        self.old={
          "platforms":{
            "cTrader":{"points":{
                "lot_input":{"x_px":111},
                "tp_input":{"x_px":999},
            },"window_title":{"internal":"cTrader","external":"cTrader"}},
            "GooeyTrade":{"points":{"lot_input":{"x_px":112}}},
            "MT5":{"points":{"lot_input":{"x_px":333}}},
          },
          "ui":{"internal_platform":"cTrader"},
        }
        self.profiles={"active":"One","profiles":{
            "One":copy.deepcopy(self.old),
            "Two":copy.deepcopy(self.old),
        }}
        self.config_path.write_text(json.dumps(self.old),encoding="utf-8")
        self.profile_path.write_text(json.dumps(self.profiles),encoding="utf-8")
        self.app=SimpleNamespace(
            store=SimpleNamespace(path=self.config_path,data=copy.deepcopy(self.old)),
            profiles=SimpleNamespace(
                path=self.profile_path,data=copy.deepcopy(self.profiles),
                active_name="One",
            ),
            automation=SimpleNamespace(config=None),
        )
        self.app.automation.config=self.app.store.data

    def test_only_selected_key_updates_every_profile_and_alias(self):
        loc={"x":.5,"y":.25,"x_px":450,"y_px":150,
             "window_width":900,"window_height":600,
             "window_title":"cTrader","calibration_window_title":"cTrader"}
        safe.save_confirmed_points(self.app,"cTrader",{"lot_input":loc})
        persisted=json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["platforms"]["cTrader"]["points"]["lot_input"]["x_px"],450)
        self.assertEqual(persisted["platforms"]["cTrader"]["points"]["tp_input"]["x_px"],999)
        self.assertEqual(persisted["platforms"]["MT5"]["points"]["lot_input"]["x_px"],333)
        self.assertNotIn("window_title",persisted["platforms"]["cTrader"]["points"]["lot_input"])
        for config in json.loads(self.profile_path.read_text(encoding="utf-8"))["profiles"].values():
            self.assertEqual(config["platforms"]["cTrader"]["points"]["lot_input"]["x_px"],450)
            self.assertEqual(config["platforms"]["GooeyTrade"]["points"]["lot_input"]["x_px"],450)
            self.assertEqual(config["platforms"]["cTrader"]["points"]["tp_input"]["x_px"],999)
        self.assertIs(self.app.automation.config,self.app.store.data)

    def test_zero_keys_rejected_without_file_or_memory_changes(self):
        before=(self.config_path.read_bytes(),self.profile_path.read_bytes())
        with self.assertRaises(safe.CalibrationConfirmationError):
            safe.save_confirmed_points(self.app,"cTrader",{})
        self.assertEqual(before,(self.config_path.read_bytes(),self.profile_path.read_bytes()))
        self.assertEqual(self.app.store.data,self.old)

    def test_atomic_restore_when_second_write_fails(self):
        before=(self.config_path.read_bytes(),self.profile_path.read_bytes())
        real=safe._replace_json_atomic
        writes=[]
        def fail_config(path, data):
            writes.append(path)
            if path == self.config_path:
                raise OSError("Synthetic disk error")
            return real(path,data)
        with patch.object(safe,"_replace_json_atomic",side_effect=fail_config):
            with self.assertRaises(OSError):
                safe.save_confirmed_points(self.app,"cTrader",{"sl_input":{"x_px":64}})
        self.assertEqual(len(writes),2)
        self.assertEqual(before,(self.config_path.read_bytes(),self.profile_path.read_bytes()))
        self.assertEqual(self.app.store.data,self.old)
        self.assertEqual(self.app.profiles.data,self.profiles)

if __name__=="__main__":
    unittest.main()

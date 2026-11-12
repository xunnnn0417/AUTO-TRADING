"""Regression: intentional cTrader clears must outlive legacy Gooey migration."""
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from trading_helper.config import (
    DEFAULT_CONFIG, _migrate_config, ConfigStore, ProfileStore,
)


class IntentionalCalibrationClearTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"profiles.json"
        self.config=deepcopy(DEFAULT_CONFIG)
        self.old={"x":0.25,"y":0.5}
        self.config["platforms"]["GooeyTrade"]["points"]={
            "lot_input":deepcopy(self.old),
            "sl_input":deepcopy(self.old)
        }
        self.config["platforms"]["cTrader"]["points"]={
            "sl_input":deepcopy(self.old)
        }

    def test_explicit_clear_prevents_legacy_reimport(self):
        c=self.config["platforms"]["cTrader"]
        c["points"].pop("sl_input")
        c["cleared_calibration_keys"]=["sl_input"]
        result=_migrate_config(self.config)
        self.assertEqual(set(result["platforms"]["cTrader"]["points"]),{"lot_input"})
        self.assertEqual(result["platforms"]["cTrader"]["cleared_calibration_keys"],["sl_input"])

    def test_cleared_all_fields_not_recopied_even_when_empty(self):
        c=self.config["platforms"]["cTrader"]
        c["points"]={}
        c["cleared_calibration_keys"]=["lot_input","sl_input"]
        result=_migrate_config(self.config)
        self.assertEqual(result["platforms"]["cTrader"]["points"],{})

    def test_saving_new_capture_undoes_explicit_clear(self):
        c=self.config["platforms"]["cTrader"]
        c["points"]={}
        c["cleared_calibration_keys"]=["lot_input","sl_input"]
        store=ProfileStore("scheme",path=self.path)
        store.data={"active":"scheme","profiles":{"scheme":deepcopy(self.config)}}
        store.sync_calibration_point("cTrader","lot_input",self.old)
        updated=store.load_profile("scheme")
        self.assertEqual(updated["platforms"]["cTrader"]["points"]["lot_input"],self.old)
        self.assertNotIn("lot_input",updated["platforms"]["cTrader"]["cleared_calibration_keys"])
        self.assertIn("sl_input",updated["platforms"]["cTrader"]["cleared_calibration_keys"])

if __name__=="__main__":
    unittest.main()

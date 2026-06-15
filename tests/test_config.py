import tempfile
import unittest
from pathlib import Path

from trading_helper.config import (
    ConfigStore,
    DEFAULT_CONFIG,
    ProfileStore,
)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "profiles.json"
        self.config = {
            **DEFAULT_CONFIG,
            "sheet": {
                **DEFAULT_CONFIG["sheet"],
                "spreadsheet_url": "https://docs.google.com/example",
            },
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seeds_default_profile_with_complete_config(self):
        store = ProfileStore(self.config, self.path)

        self.assertEqual(store.names(), ["預設方案"])
        self.assertEqual(
            store.load_profile()["sheet"]["spreadsheet_url"],
            "https://docs.google.com/example",
        )

    def test_create_rename_and_delete_profiles(self):
        store = ProfileStore(self.config, self.path)
        second = store.load_profile()
        second["sheet"]["gid"] = "123"

        store.create("第二方案", second)
        self.assertEqual(store.active_name, "第二方案")
        self.assertEqual(store.load_profile()["sheet"]["gid"], "123")

        store.rename("第二方案", "新名稱")
        self.assertEqual(store.active_name, "新名稱")
        self.assertIn("新名稱", store.names())

        active = store.delete("新名稱")
        self.assertEqual(active, "預設方案")

    def test_profile_snapshots_are_independent(self):
        store = ProfileStore(self.config, self.path)
        copied = store.load_profile()
        store.create("副本", copied)
        copied["platforms"]["cTrader"]["points"]["lot_input"] = {"x": 0.5}
        store.save_profile("副本", copied)

        self.assertNotIn(
            "lot_input",
            store.load_profile("預設方案")["platforms"]["cTrader"]["points"],
        )

    def test_cannot_delete_only_profile(self):
        store = ProfileStore(self.config, self.path)

        with self.assertRaises(ValueError):
            store.delete("預設方案")

    def test_calibration_point_syncs_to_every_profile(self):
        store = ProfileStore(self.config, self.path)
        store.create("第二方案", store.load_profile())
        point = {"x": 0.4, "y": 0.6, "window_title": "current"}

        store.sync_calibration_point("MT5", "lot_input", point)

        active_point = store.load_profile("第二方案")["platforms"]["MT5"][
            "points"
        ]["lot_input"]
        other_point = store.load_profile("預設方案")["platforms"]["MT5"][
            "points"
        ]["lot_input"]
        self.assertNotIn("window_title", active_point)
        self.assertNotIn("window_title", other_point)
        self.assertEqual(other_point["x"], 0.4)

    def test_ctrader_calibration_syncs_to_gooeytrade(self):
        store = ProfileStore(self.config, self.path)
        point = {"x": 0.25, "y": 0.75, "window_title": "cTrader"}

        store.sync_calibration_point("cTrader", "tp_input", point)

        profile = store.load_profile()
        self.assertEqual(
            profile["platforms"]["cTrader"]["points"]["tp_input"]["x"],
            0.25,
        )
        self.assertEqual(
            profile["platforms"]["GooeyTrade"]["points"]["tp_input"]["x"],
            0.25,
        )
        self.assertNotIn(
            "window_title",
            profile["platforms"]["GooeyTrade"]["points"]["tp_input"],
        )

    def test_legacy_ctrader_configuration_migrates_to_gooeytrade(self):
        legacy = {
            "platforms": {
                "cTrader": {
                    "window_title": {
                        "internal": "GooeyTrade Trader 5.7.10",
                        "external": "GooeyTrade Trader 5.7.10",
                    },
                    "points": {"lot_input": {"x": 0.5, "y": 0.4}},
                    "open_panel_before_fill": False,
                }
            },
            "ui": {
                "internal_platform": "cTrader",
                "external_platform": "MT5",
            },
        }
        config_path = Path(self.temp_dir.name) / "config.json"
        config_path.write_text(
            __import__("json").dumps(legacy),
            encoding="utf-8",
        )

        loaded = ConfigStore(config_path).data

        self.assertEqual(loaded["ui"]["internal_platform"], "GooeyTrade")
        self.assertIn(
            "lot_input",
            loaded["platforms"]["GooeyTrade"]["points"],
        )
        self.assertEqual(
            loaded["platforms"]["GooeyTrade"]["window_title"]["internal"],
            "GooeyTrade",
        )
        self.assertEqual(
            loaded["platforms"]["cTrader"]["window_title"]["internal"],
            "cTrader",
        )

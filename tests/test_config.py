import tempfile
import unittest
from pathlib import Path

from trading_helper.config import DEFAULT_CONFIG, ProfileStore


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

"""Demo-safe tests: per-scheme cTrader decimal-mode settings and opt-in."""
import inspect
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QCheckBox, QMainWindow, QMessageBox

from trading_helper.config import (
    DEFAULT_CONFIG, ProfileStore, ctrader_mode_for_profile,
    ctrader_mode_identity, set_ctrader_mode_for_profile,
)
from trading_helper.automation import (
    CTraderDecimalInputSuggestion, PlatformAutomation,
)
from trading_helper.gui import TradingHelperApp, SettingsDialog

class PerSchemeModeTests(unittest.TestCase):
    def setUp(self):
        self.c=deepcopy(DEFAULT_CONFIG)
        self.c["sheet"]["spreadsheet_url"]="https://docs.google.com/a"
    def test_initial_mode_native_even_if_stale_copy_is_gooey(self):
        self.assertEqual(ctrader_mode_for_profile(self.c,"Alpha"),"native")
        set_ctrader_mode_for_profile(self.c,"Alpha","gooey")
        self.assertEqual(ctrader_mode_for_profile(self.c,"Alpha"),"gooey")
        self.assertEqual(ctrader_mode_for_profile(self.c,"Beta"),"native")
        self.c["sheet"]["spreadsheet_url"]="https://docs.google.com/b"
        self.assertEqual(ctrader_mode_for_profile(self.c,"Alpha"),"native")
    def test_url_normalization_and_identity(self):
        first=ctrader_mode_identity(" Alpha "," https://a ")
        second=ctrader_mode_identity("Alpha","https://a")
        self.assertEqual(first,second)
        self.assertNotEqual(first,ctrader_mode_identity("Alpha","https://b"))
    def test_profile_create_and_rename_reset_to_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ProfileStore(self.c,Path(tmp)/"profiles.json")
            old=store.active_name
            a=store.load_profile()
            set_ctrader_mode_for_profile(a,old,"gooey")
            store.save_profile(old,a)
            store.create("Copy",store.load_profile(old))
            self.assertEqual(ctrader_mode_for_profile(store.load_profile("Copy"),"Copy"),"native")
            copy=store.load_profile("Copy")
            set_ctrader_mode_for_profile(copy,"Copy","gooey")
            store.save_profile("Copy",copy)
            store.rename("Copy","New Name")
            self.assertEqual(
                ctrader_mode_for_profile(store.load_profile("New Name"),"New Name"),"native"
            )
            self.assertEqual(
                ctrader_mode_for_profile(store.load_profile(old),old),"gooey"
            )
    def test_manual_mode_routes_only_matching_scheme(self):
        windows=MagicMock()
        a=PlatformAutomation(self.c,windows,MagicMock(),lambda x:None,profile_name="Alpha")
        profile=self.c["platforms"]["cTrader"]
        self.assertFalse(a._ctrader_uses_point_size("cTrader",profile,"internal",{}))
        set_ctrader_mode_for_profile(self.c,"Alpha","gooey")
        self.assertTrue(a._ctrader_uses_point_size("cTrader",profile,"internal",{}))
        self.assertTrue(a._ctrader_uses_point_size(
            "GooeyTrade",self.c["platforms"]["GooeyTrade"],"internal",{}
        ))
        a.profile_name="Beta"
        self.assertFalse(a._ctrader_uses_point_size("cTrader",profile,"internal",{}))
    def test_mode_rejects_unrecognized_setting(self):
        with self.assertRaises(ValueError):
            set_ctrader_mode_for_profile(self.c,"Alpha","arbitrary")

class DecimalSuggestionTests(unittest.TestCase):
    def setUp(self):
        from test_fill_verification import FillVerificationTests
        self.t=FillVerificationTests("test_correct_mt5_values_no_extra_writes")
        self.t.setUp()
        self.t.config["sheet"]={"spreadsheet_url":"https://docs.google.com/a"}
        self.t.automation.profile_name="Alpha"
        set_ctrader_mode_for_profile(self.t.config,"Alpha","native")
        self.t.values=[
            ("lot_input","手數","0.75"),
            ("sl_input","止損點數","0.45"),
            ("tp_input","止盈點數","11.5"),
        ]
        self.raw_click=self.t.fake.click_and_type
    def _configure(self,mode="decimal_truncated",key="sl_input"):
        def click(window,point,value):
            k=point["id"]
            self.t.fake.writes.append((window.title,k,value))
            if k==key and mode=="decimal_truncated":
                self.t.fake.values[k]=str(int(Decimal(value)))
            elif k==key and mode=="different":
                self.t.fake.values[k]="777"
            else:
                self.t.fake.values[k]=value
        self.t.fake.click_and_type=click
        self.t.seed()
    def test_two_decimal_truncations_raise_suggestion_no_third_write(self):
        self._configure()
        with self.assertRaises(CTraderDecimalInputSuggestion) as result:
            self.t.verify_ctrader()
        self.assertEqual(result.exception.role_text,"場內")
        self.assertEqual(result.exception.expected,"0.45")
        self.assertEqual(
            [k for _,k,_ in self.t.fake.writes].count("sl_input"),2
        )
    def test_integer_value_or_other_mismatch_uses_regular_three_attempts(self):
        self._configure(mode="different")
        with self.assertRaisesRegex(Exception,"三次填入"):
            self.t.verify_ctrader()
        self.assertEqual(
            [k for _,k,_ in self.t.fake.writes].count("sl_input"),3
        )
    def test_gooey_mode_not_prompted(self):
        self._configure()
        set_ctrader_mode_for_profile(self.t.config,"Alpha","gooey")
        with self.assertRaisesRegex(Exception,"三次填入"):
            self.t.verify_ctrader()
        self.assertEqual(
            [k for _,k,_ in self.t.fake.writes].count("sl_input"),3
        )
    def test_mt5_never_prompts(self):
        self._configure()
        with self.assertRaisesRegex(Exception,"三次填入"):
            self.t.verify_mt5()

class SettingsAndDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])
    def setUp(self):
        self.parent=QMainWindow()
        self.parent.store=SimpleNamespace(data=deepcopy(DEFAULT_CONFIG))
        self.parent.store.data["sheet"]["spreadsheet_url"]="https://docs.google.com/a"
        self.parent.profiles=SimpleNamespace(active_name="Alpha")
        self.parent.save_config=MagicMock()
        self.parent.log=MagicMock()
    def tearDown(self):
        self.parent.close()
    def test_settings_has_mode_and_saves_only_current_scheme(self):
        dialog=SettingsDialog(self.parent)
        combo=dialog.ctrader_mode_combo
        self.assertEqual(combo.count(),2)
        combo.setCurrentIndex(combo.findData("gooey"))
        dialog.save()
        self.assertEqual(ctrader_mode_for_profile(self.parent.store.data,"Alpha"),"gooey")
        self.parent.save_config.assert_called_once()
        dialog.close()
    def test_settings_url_change_resets_to_native(self):
        set_ctrader_mode_for_profile(self.parent.store.data,"Alpha","gooey")
        dialog=SettingsDialog(self.parent)
        self.assertEqual(dialog.ctrader_mode_combo.currentData(),"gooey")
        dialog.sheet_fields["spreadsheet_url"].setText("https://docs.google.com/b")
        dialog.save()
        self.assertEqual(ctrader_mode_for_profile(self.parent.store.data,"Alpha"),"native")
        dialog.close()
    def test_prompt_accepts_and_stores_on_exact_scheme_only(self):
        data=dict(profile_name="Alpha",sheet_url="https://docs.google.com/a",
                  role_text="場內",label="止損點數",expected="0.45",actual="0")
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes) as q:
            TradingHelperApp._show_ctrader_decimal_suggestion(self.parent,data)
        self.assertIn("Gooey",q.call_args.args[2])
        self.assertEqual(ctrader_mode_for_profile(self.parent.store.data,"Alpha"),"gooey")
        self.parent.save_config.assert_called_once()
    def test_prompt_refusal_does_not_change_preference(self):
        data=dict(profile_name="Alpha",sheet_url="https://docs.google.com/a",
                  role_text="場外",label="止盈點數",expected="0.55",actual="0")
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.No):
            TradingHelperApp._show_ctrader_decimal_suggestion(self.parent,data)
        self.assertEqual(ctrader_mode_for_profile(self.parent.store.data,"Alpha"),"native")
        self.parent.save_config.assert_not_called()
    def test_switching_sheet_before_prompt_prevents_any_question(self):
        data=dict(profile_name="Alpha",sheet_url="https://docs.google.com/old",
                  role_text="場內",label="止損",expected="0.45",actual="0")
        with patch("trading_helper.gui.QMessageBox.question") as q:
            TradingHelperApp._show_ctrader_decimal_suggestion(self.parent,data)
            q.assert_not_called()
        self.parent.save_config.assert_not_called()
    def test_auto_entry_confirmation_uses_real_newlines(self):
        self.parent.auto_entry_on_fill_both=QCheckBox()
        self.parent.auto_sync_sl_tp_after_entry=QCheckBox()
        self.parent.auto_draw_tv_after_entry=QCheckBox()
        self.parent.save_ui_state=MagicMock()
        self.parent.auto_entry_on_fill_both.setChecked(True)
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.No) as q:
            TradingHelperApp._confirm_auto_entry_toggle(self.parent,True)
        text=q.call_args.args[2]
        self.assertIn("\n",text)
        self.assertNotIn("\\n",text)
        self.assertFalse(self.parent.auto_entry_on_fill_both.isChecked())
        self.parent.auto_entry_on_fill_both.close()
        self.parent.auto_sync_sl_tp_after_entry.close()
        self.parent.auto_draw_tv_after_entry.close()

if __name__=="__main__":
    unittest.main()

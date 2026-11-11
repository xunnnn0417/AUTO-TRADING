from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox

from trading_helper.gui import TradingHelperApp
from test_auto_entry_state_machine import instruction


class RepeatedExpectedSlPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.item = replace(
            instruction(), original_sl_points=Decimal("-8.35"),
            expected_sl_points=Decimal("-8.59"), expected_sl_percent=None,
        )
        identity = TradingHelperApp._expected_sl_repeat_signature(
            "Alpha", "sheet", self.item
        )
        self.ui = SimpleNamespace(
            auto_entry_on_fill_both=QCheckBox(),
            profiles=SimpleNamespace(active_name="Alpha"),
            store=SimpleNamespace(data={
                "sheet": {"spreadsheet_url": "sheet"},
                "ui": {
                    "last_auto_entry_sl_context": identity,
                    "last_auto_entry_sl_points": "-8.59",
                },
            }),
            _expected_sl_repeat_signature=(
                TradingHelperApp._expected_sl_repeat_signature
            ),
        )
        self.ui.auto_entry_on_fill_both.setChecked(True)
        self.addCleanup(self.ui.auto_entry_on_fill_both.close)

    def test_same_unmodified_value_asks_and_returns_approved_adjustment(self):
        with patch("trading_helper.gui.choose_repeat_adjustment",
                   return_value=Decimal("-9.12")), \
             patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes) as prompt:
            adjusted, did_adjust = TradingHelperApp._maybe_adjust_repeated_expected_sl(
                self.ui, self.item, roles=("internal", "external"),
                dirty=(), test_action="",
            )
        self.assertTrue(did_adjust)
        self.assertEqual(adjusted.expected_sl_points, Decimal("-9.12"))
        self.assertIn("-9.59", prompt.call_args.args[2])
        self.assertIn("-8.35", prompt.call_args.args[2])
        self.assertIn("手數", prompt.call_args.args[2])

    def test_does_not_prompt_if_input_changed_or_single_side_fill(self):
        with patch("trading_helper.gui.QMessageBox.question") as prompt:
            same, changed = TradingHelperApp._maybe_adjust_repeated_expected_sl(
                self.ui, self.item, roles=("internal", "external"),
                dirty=("expected_sl_combined",), test_action="",
            )
            single_item, single_changed = TradingHelperApp._maybe_adjust_repeated_expected_sl(
                self.ui, self.item, roles=("internal",),
                dirty=(), test_action="",
            )
        self.assertIs(same, self.item)
        self.assertIs(single_item, self.item)
        self.assertFalse(changed)
        self.assertFalse(single_changed)
        prompt.assert_not_called()

    def test_test_scenario_prompts_before_fill_even_when_auto_entry_toggle_is_off(self):
        self.ui.auto_entry_on_fill_both.setChecked(False)
        with patch("trading_helper.gui.choose_repeat_adjustment",
                   return_value=Decimal("-9.12")), \
             patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes) as prompt:
            adjusted, did_adjust = TradingHelperApp._maybe_adjust_repeated_expected_sl(
                self.ui, self.item, roles=("internal", "external"),
                dirty=(), test_action="reentry:internal",
            )
        self.assertTrue(did_adjust)
        self.assertEqual(adjusted.expected_sl_points, Decimal("-9.12"))
        prompt.assert_called_once()

    def test_only_successful_result_remembers_the_last_points(self):
        self.ui.instruction = self.item
        self.ui.save_config = MagicMock()
        saved = TradingHelperApp._expected_sl_repeat_signature(
            "Alpha", "sheet", self.item
        )
        report = {"success": True, "_repeat_expected_sl": {
            "context": saved, "points": "-8.59",
        }}
        TradingHelperApp._remember_successful_expected_sl(self.ui, report)
        self.assertEqual(
            self.ui.store.data["ui"]["last_auto_entry_sl_points"], "-8.59"
        )
        self.ui.save_config.assert_called_once()

        self.ui.store.data["ui"].pop("last_auto_entry_sl_points")
        self.ui.save_config.reset_mock()
        report["success"] = False
        TradingHelperApp._remember_successful_expected_sl(self.ui, report)
        self.assertNotIn("last_auto_entry_sl_points", self.ui.store.data["ui"])
        self.ui.save_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()

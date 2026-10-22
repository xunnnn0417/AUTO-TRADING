"""Auto-entry UI shell tests. No broker interaction or trade submission."""
import inspect
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QMainWindow, QMessageBox,
)

from trading_helper.gui import TradingHelperApp
from trading_helper.config import DEFAULT_CONFIG
from trading_helper.windows import AutomationError


def combo(text):
    c = QComboBox()
    c.addItem(text)
    return c


class AutoEntryOptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QMainWindow()
        self.parent.auto_entry_on_fill_both = QCheckBox("填入兩邊時自動進場")
        self.parent.save_ui_state = MagicMock()
        self.parent.log = MagicMock()
        self.parent.auto_entry_on_fill_both.toggled.connect(
            lambda checked: TradingHelperApp._confirm_auto_entry_toggle(self.parent, checked)
        )

    def tearDown(self):
        self.parent.auto_entry_on_fill_both.close()
        self.parent.close()

    def test_default_is_off_for_existing_profiles(self):
        self.assertFalse(DEFAULT_CONFIG["ui"]["auto_entry_on_fill_both"])

    def test_switch_on_rejection_resets_without_saving(self):
        with patch("trading_helper.gui.QMessageBox.question", return_value=QMessageBox.No) as question:
            self.parent.auto_entry_on_fill_both.setChecked(True)
            question.assert_called_once()
            self.assertFalse(self.parent.auto_entry_on_fill_both.isChecked())
            self.parent.save_ui_state.assert_not_called()

    def test_switch_on_confirmed_then_off_is_immediate(self):
        with patch("trading_helper.gui.QMessageBox.question", return_value=QMessageBox.Yes) as question:
            self.parent.auto_entry_on_fill_both.setChecked(True)
            self.assertTrue(self.parent.auto_entry_on_fill_both.isChecked())
            self.assertEqual(self.parent.save_ui_state.call_count, 1)
            args = question.call_args.args
            self.assertIn("兩個 Demo 帳戶", args[2])
        self.parent.auto_entry_on_fill_both.setChecked(False)
        self.assertEqual(self.parent.save_ui_state.call_count, 2)
        self.assertFalse(self.parent.auto_entry_on_fill_both.isChecked())

    def test_unchecked_fill_both_preserves_original_order_and_no_hook(self):
        events = []
        def fill(platform, role, instruction):
            events.append((role, platform, instruction))
        hook = MagicMock()
        fake = SimpleNamespace(
            _require_instruction=lambda: "fake-instruction",
            automation=SimpleNamespace(fill=fill),
            _auto_entry_after_fill_both_pending=hook,
        )
        TradingHelperApp._fill_both_task(fake, "cTrader", "MT5", False)
        self.assertEqual(events,[
            ("internal","cTrader","fake-instruction"),
            ("external","MT5","fake-instruction")
        ])
        hook.assert_not_called()

    def test_enabled_fill_both_calls_only_postfill_placeholder(self):
        events=[]
        def fill(platform, role, instruction):
            events.append(role)
        def hook(internal_platform, external_platform, instruction):
            events.append("reserved-hook")
        fake=SimpleNamespace(
            _require_instruction=lambda:"fake",
            automation=SimpleNamespace(fill=fill),
            _auto_entry_after_fill_both_pending=hook,
        )
        TradingHelperApp._fill_both_task(fake,"cTrader","MT5",True)
        self.assertEqual(events,["internal","external","reserved-hook"])

    def test_failure_during_fill_never_calls_entry_hook(self):
        hook=MagicMock()
        def fill(platform, role, instruction):
            if role=="external":
                raise RuntimeError("fake second-side failure")
        fake=SimpleNamespace(
            _require_instruction=lambda:"fake",
            automation=SimpleNamespace(fill=fill),
            _auto_entry_after_fill_both_pending=hook,
        )
        with self.assertRaisesRegex(RuntimeError,"second-side"):
            TradingHelperApp._fill_both_task(fake,"cTrader","MT5",True)
        hook.assert_not_called()

    def test_fill_both_dispatches_to_preflight_before_start(self):
        verify=MagicMock()
        fake=SimpleNamespace(_launch_fill=verify)
        TradingHelperApp.fill_both(fake)
        verify.assert_called_once_with(("internal", "external"))

    def test_fill_worker_captures_switch_once_at_click(self):
        button=QCheckBox()
        inside=combo("cTrader")
        outside=combo("MT5")
        run=MagicMock()
        fill=MagicMock()
        fake=SimpleNamespace(
            auto_entry_on_fill_both=button,_start=run,_fill_both_task=fill,
        )
        platforms={"internal":inside.currentText(),"external":outside.currentText()}
        TradingHelperApp._start_fill_worker(fake,("internal","external"),platforms)
        self.assertEqual(run.call_args.args[0],"填入兩邊")
        job=run.call_args.args[1]
        button.setChecked(True)
        job()
        fill.assert_called_once_with("cTrader","MT5",False)
        run.reset_mock();fill.reset_mock()
        TradingHelperApp._start_fill_worker(fake,("internal","external"),platforms)
        button.setChecked(False)
        run.call_args.args[1]()
        fill.assert_called_once_with("cTrader","MT5",True)
        button.close();inside.close();outside.close()

    def test_save_ui_state_includes_per_profile_toggle(self):
        checkbox=QCheckBox()
        checkbox.setChecked(True)
        source=SimpleNamespace(
            store=SimpleNamespace(data={"ui":{}}),
            internal_platform=combo("cTrader"),external_platform=combo("MT5"),
            tv_draw_internal=QCheckBox(),auto_entry_on_fill_both=checkbox,
            auto_sync_sl_tp_after_entry=QCheckBox(),
            auto_draw_tv_after_entry=QCheckBox(),
            save_config=MagicMock(),
        )
        TradingHelperApp.save_ui_state(source)
        self.assertTrue(source.store.data["ui"]["auto_entry_on_fill_both"])
        source.save_config.assert_called_once()
        source.internal_platform.close();source.external_platform.close()
        source.tv_draw_internal.close();checkbox.close()

    def test_profile_restore_does_not_prompt_confirmation(self):
        from PySide6.QtWidgets import QLineEdit, QLabel
        from trading_helper.gui import TradingHelperApp
        fake=QMainWindow()
        fake.store=SimpleNamespace(data={"ui":{
            "internal_platform":"cTrader","external_platform":"MT5",
            "tv_draw_internal":False,"auto_entry_on_fill_both":True,
        }})
        fake.internal_platform=combo("cTrader")
        fake.external_platform=combo("MT5")
        fake.tv_draw_internal=QCheckBox()
        fake.auto_entry_on_fill_both=QCheckBox()
        fake.auto_sync_sl_tp_after_entry=QCheckBox()
        fake.auto_draw_tv_after_entry=QCheckBox()
        fake.entry_price_input=QLineEdit()
        fake.entry_price_value=QLineEdit()
        fake._fill_waiting_for_sheet=None
        fake._fill_confirmed_text={}
        fake.internal_direction_input=combo("BUY")
        fake.parameter_inputs={"one":QLineEdit()}
        fake.data_labels={"two":QLabel()}
        dialog=MagicMock()
        fake.auto_entry_on_fill_both.toggled.connect(dialog)
        TradingHelperApp._apply_profile_ui(fake)
        self.assertTrue(fake.auto_entry_on_fill_both.isChecked())
        self.assertFalse(fake.auto_sync_sl_tp_after_entry.isChecked())
        self.assertFalse(fake.auto_draw_tv_after_entry.isChecked())
        dialog.assert_not_called()
        self.assertIsNone(fake.instruction)
        fake.store.data["ui"]["auto_entry_on_fill_both"]=False
        TradingHelperApp._apply_profile_ui(fake)
        self.assertFalse(fake.auto_entry_on_fill_both.isChecked())
        dialog.assert_not_called()
        fake.close()

    def test_fast_pair_confirm_newlines_and_only_when_user_enables(self):
        self.parent.auto_fast_pair=QCheckBox("快速雙邊")
        self.parent.auto_entry_on_fill_both.setChecked(False)
        self.parent.auto_fast_pair.toggled.connect(
            lambda checked: TradingHelperApp._confirm_fast_pair_toggle(self.parent,checked)
        )
        # With auto entry disabled, an accidental click cannot arm fast mode.
        with patch("trading_helper.gui.QMessageBox.question") as question:
            self.parent.auto_fast_pair.setChecked(True)
            question.assert_not_called()
            self.assertFalse(self.parent.auto_fast_pair.isChecked())
        self.parent.auto_entry_on_fill_both.blockSignals(True)
        self.parent.auto_entry_on_fill_both.setChecked(True)
        self.parent.auto_entry_on_fill_both.blockSignals(False)
        with patch("trading_helper.gui.QMessageBox.question",
                   return_value=QMessageBox.Yes) as question:
            self.parent.auto_fast_pair.setChecked(True)
            self.assertTrue(self.parent.auto_fast_pair.isChecked())
            message=question.call_args.args[2]
            self.assertIn("\n\n",message)
            self.assertNotIn(chr(92)+"n",message)
            question.assert_called_once()
        self.parent.auto_fast_pair.close()

    def test_records_log_room_and_no_per_fill_confirmation(self):
        source=inspect.getsource(TradingHelperApp._build)
        self.assertIn("self.log_text.setMinimumHeight(140)",source)
        self.assertIn("log_box.setMaximumHeight(235)",source)
        fill_source=inspect.getsource(TradingHelperApp._start_fill_worker)
        self.assertNotIn("QMessageBox.question",fill_source)

    def test_header_order_and_no_direct_order_calls_in_reserved_hook(self):
        code=inspect.getsource(TradingHelperApp._build)
        self.assertLess(code.index("top_row.addWidget(self.profile_manage_button)"),
                        code.index("top_row.addWidget(sheet_url_button)"))
        self.assertLess(code.index("top_row.addWidget(sheet_url_button)"),
                        code.index("top_row.addWidget(self.display_settings_button)"))
        self.assertIn("automation_layout.addWidget(self.auto_entry_on_fill_both)",code)
        self.assertIn("top_row.addWidget(nav)",code)
        self.assertLess(code.index("top_row.addWidget(self.display_settings_button)"),
                        code.index("top_row.addLayout(chrome_controls)"))
        self.assertIn("chrome_controls.addWidget(self.chrome_close)", code)
        self.assertIn("display_layout.addWidget(self.tv_draw_internal)", code)
        self.assertIn("display_layout.addWidget(self.always_on_top)", code)
        log=MagicMock()
        fake=SimpleNamespace(
            log=log,
            emergency=SimpleNamespace(guard=MagicMock()),
            automation=MagicMock(),
            profiles=SimpleNamespace(active_name="DemoOnly"),
            store=SimpleNamespace(data={"sheet":{"spreadsheet_url":"test"}}),
        )
        with patch("trading_helper.gui.DemoUiBrokerPort") as adapter, \
             patch("trading_helper.gui.AutoEntryWorkflow") as flow:
            flow.return_value.run.side_effect=AutomationError(
                "Demo 持倉驗證尚未完成，拒絕送單。"
            )
            with self.assertRaisesRegex(AutomationError,"拒絕送單"):
                TradingHelperApp._auto_entry_after_fill_both_pending(
                    fake,"cTrader","MT5","fake"
                )
            adapter.assert_called_once()
            flow.return_value.run.assert_called_once()
        log.assert_not_called()


if __name__=="__main__":
    unittest.main()

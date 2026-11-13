"""Offline tests for recovery choices, dialog ownership and pair dispatch."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QPushButton
from trading_helper import gui
from trading_helper.auto_entry import AutoEntryJournal, AutoEntryWorkflow, Position
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError, WindowInfo
from test_auto_entry_state_machine import instruction
from test_single_leg_test_mode import SingleLegFakePort


class IncidentChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.item=instruction()
        self.fake=SimpleNamespace(
            profiles=SimpleNamespace(active_name="test"),
            store=SimpleNamespace(data={"sheet":{"spreadsheet_url":"sheet"}}),
            instruction=self.item,
            _require_instruction=lambda:replace(self.item),
            internal_platform=SimpleNamespace(currentText=lambda:"cTrader"),
            external_platform=SimpleNamespace(currentText=lambda:"MT5"),
            _auto_entry_receipt=None,
            _remember_successful_expected_sl=MagicMock(),
            _start_user_approved_incident_action=MagicMock(),
            _execute_user_approved_incident_action=MagicMock(),
            _start=MagicMock(),
        )
        self.request=dict(item=replace(self.item),profile_name="test",sheet_url="sheet",
            internal_platform="cTrader",external_platform="MT5",symbol=self.item.symbol,
            account_ids={"internal":"111111","external":"222222"},
            confirmed_role="internal",confirmed_ticket="test-ticket")

    def test_equivalent_instruction_copy_allows_both_explicit_actions(self):
        for action in ("close","reenter"):
            with self.subTest(action=action),patch.object(gui.QMessageBox,"warning") as warning:
                self.fake._start.reset_mock()
                gui.TradingHelperApp._start_user_approved_incident_action(
                    self.fake,action,self.request)
                warning.assert_not_called()
                self.fake._start.assert_called_once()
                self.fake._start.call_args.args[1]()
                self.fake._execute_user_approved_incident_action.assert_called_with(action,self.request)

    def test_actual_direction_lots_and_sl_changes_still_reject(self):
        for changed in (
            replace(self.item,sheet_direction="SELL"),
            replace(self.item,internal=replace(self.item.internal,lot=D("99"))),
            replace(self.item,expected_sl_points=D("-99")),
        ):
            with self.subTest(changed=changed),patch.object(gui.QMessageBox,"warning") as warning:
                self.fake._require_instruction=lambda:changed
                gui.TradingHelperApp._start_user_approved_incident_action(self.fake,"close",self.request)
                warning.assert_called_once()
                self.fake._start.assert_not_called()

    def test_plan_sheet_platform_symbol_and_account_context_still_required(self):
        for changes in (dict(profile_name="other"),dict(sheet_url="other"),
                        dict(external_platform="cTrader"),dict(symbol="BTCUSD"),dict(account_ids={})):
            with self.subTest(changes=changes),patch.object(gui.QMessageBox,"warning") as warning:
                gui.TradingHelperApp._start_user_approved_incident_action(
                    self.fake,"reenter",dict(self.request,**changes))
                warning.assert_called_once()
                self.fake._start.assert_not_called()

    def test_role_labels_and_owned_warning_above_result(self):
        for role,close,reenter in (("internal","平掉場內","補進場外"),
                                   ("external","平掉場外","補進場內")):
            gui.TradingHelperApp._show_auto_entry_result(self.fake,dict(
                title="TEST",message="TEST",single_confirmed_role=role,
                incident_action_request=dict(self.request,confirmed_role=role)))
            dialog=self.fake._auto_entry_receipt
            try:
                self.assertEqual(dialog.findChild(QPushButton,"autoEntryIncidentCloseButton").text(),close)
                self.assertEqual(dialog.findChild(QPushButton,"autoEntryIncidentReentryButton").text(),reenter)
                self.request["profile_name"]="changed"
                observed=[]
                def dismiss_warning():
                    box=next(w for w in self.app.topLevelWidgets()
                             if isinstance(w,gui.ThemedMessageBox) and w.isVisible())
                    observed.append((box.parentWidget(),box.windowFlags(),box.windowModality()))
                    box._buttons[0].click()
                QTimer.singleShot(0,dismiss_warning)
                gui.TradingHelperApp._start_user_approved_incident_action(self.fake,"close",self.request)
                self.assertEqual(len(observed),1)
                parent,flags,modality=observed[0]
                self.assertIs(parent,dialog)
                self.assertTrue(flags & Qt.WindowStaysOnTopHint)
                self.assertEqual(modality,Qt.WindowModal)
                self.assertTrue(dialog.isVisible())
            finally:
                dialog.close()

    def test_fast_preference_is_captured_before_test_worker(self):
        for action in ("weekend:BTCUSD","reentry:internal","close:external"):
            fake=SimpleNamespace(
                auto_entry_on_fill_both=SimpleNamespace(isChecked=lambda:False),
                auto_fast_pair=MagicMock(),_start=MagicMock(),
                _run_complete_test_scenario=MagicMock())
            fake.auto_fast_pair.isChecked.return_value=True
            gui.TradingHelperApp._start_fill_worker(fake,("internal","external"),
                {"internal":"cTrader","external":"MT5"},test_action=action)
            fake.auto_fast_pair.isChecked.side_effect=AssertionError("Qt read from worker")
            fake._start.call_args.args[1]()
            self.assertTrue(fake._run_complete_test_scenario.call_args.kwargs["fast_pair"])

    def test_complete_test_routes_only_dual_initial_entries_as_fast(self):
        for action in ("weekend:BTCUSD","close:internal","close:external","reentry:internal","reentry:external"):
            fake=SimpleNamespace(_fill_both_task=MagicMock())
            gui.TradingHelperApp._run_complete_test_scenario(fake,action,
                {"internal":"cTrader","external":"MT5"},fast_pair=True)
            self.assertEqual(fake._fill_both_task.call_args.kwargs["fast_pair"],not action.startswith("reentry:"))

    def test_fill_does_not_drop_fast_option_before_test_entry(self):
        fake=SimpleNamespace(_require_instruction=instruction,automation=MagicMock(),
            _auto_entry_after_fill_both_pending=MagicMock(),log=MagicMock())
        gui.TradingHelperApp._fill_both_task(fake,"cTrader","MT5",True,
            fast_pair=True,test_scenario="close:external")
        self.assertTrue(fake._auto_entry_after_fill_both_pending.call_args.kwargs["fast_pair"])


class FastScenarioOrderTests(unittest.TestCase):
    def test_pair_dispatch_precedes_confirmation_in_both_platform_directions(self):
        for reverse in (False,True):
            for fast in (False,True):
                for scenario in ("weekend:BTCUSD","close:internal","close:external","reentry:internal","reentry:external"):
                    with self.subTest(reverse=reverse,fast=fast,scenario=scenario),tempfile.TemporaryDirectory() as tmp:
                        port=SingleLegFakePort(mt5_internal=reverse)
                        flow=AutoEntryWorkflow(port,AutoEntryJournal(Path(tmp)/"journal.json"),lambda:None,lambda _:None)
                        platforms=("MT5","cTrader") if reverse else ("cTrader","MT5")
                        flow.run_test_scenario(instruction(),*platforms,"test","sheet",
                            scenario=scenario,test_run_id="test",fast_pair=fast)
                        events=port.events
                        submits=[i for i,x in enumerate(events) if x[0]=="submit"]
                        first_confirm=next(i for i,x in enumerate(events) if x[0]=="confirm")
                        self.assertEqual(submits[1]<first_confirm,fast and not scenario.startswith("reentry:"))


class VerifiedModifyCleanupTests(unittest.TestCase):
    def setUp(self):
        self.windows=MagicMock()
        self.automation=SimpleNamespace(windows=self.windows,emergency=SimpleNamespace(guard=lambda:None))
        self.log=MagicMock()
        self.port=DemoUiBrokerPort(self.automation,self.log)
        self.pos=Position("test","111111","MT5","XAUUSD","SELL",D("0.2"),D("4100"),D("4110"),D("4080"))
        self.port._ticket_role[("MT5","test")]="external"
        self.port.snapshot_positions=MagicMock(return_value=(self.pos,))
        self.window=WindowInfo(2,"Modify",0,0,800,600)

    def test_matching_position_dismisses_only_the_remaining_modify_window(self):
        self.windows.list_windows.side_effect=[ [self.window], [] ]
        self.port.verify_position_sl_tp(self.pos,self.pos.sl,self.pos.tp,modify_window=self.window)
        self.windows.press.assert_called_once_with(self.window,"esc")
        self.windows.click.assert_not_called()

    def test_already_closed_modify_window_needs_no_escape(self):
        self.windows.list_windows.return_value=[]
        self.port.verify_position_sl_tp(self.pos,self.pos.sl,self.pos.tp,modify_window=self.window)
        self.windows.press.assert_not_called()

    def test_wrong_price_or_changed_position_never_dismisses_or_claims_success(self):
        for changed in (replace(self.pos,sl=D("1")),replace(self.pos,account_id="222222")):
            self.port.snapshot_positions.return_value=(changed,)
            with patch("trading_helper.demo_broker_port.time.monotonic",side_effect=[0,9]):
                with self.assertRaises(AutomationError):
                    self.port.verify_position_sl_tp(self.pos,self.pos.sl,self.pos.tp,modify_window=self.window)
            self.windows.press.assert_not_called()

    def test_same_existing_values_do_not_open_or_submit_an_unchanged_modification(self):
        self.port.set_position_sl_tp(self.pos,self.pos.sl,self.pos.tp)
        self.windows.double_click.assert_not_called()
        self.windows.click.assert_not_called()
        self.assertIn("4110",self.log.call_args_list[0].args[0])

    def test_automatic_modify_remembers_exact_dialog_until_verified(self):
        target_sl,target_tp=D("4111"),D("4079")
        points={name:{"id":name} for name in ("position_order_row","position_sl_input",
                    "position_tp_input","position_modify_confirm")}
        self.port._bound=lambda *args:({"points":points},WindowInfo(1,"MT5",0,0,800,600))
        self.automation._normalize_numeric_input=lambda raw,value:D(raw)
        self.windows.wait_for_active_window_change.return_value=self.window
        self.windows.read_edit_value.side_effect=[str(target_sl),str(target_tp)]
        self.port.set_position_sl_tp(self.pos,target_sl,target_tp)
        self.windows.click.assert_called_once_with(self.window,points["position_modify_confirm"])
        self.windows.press.assert_not_called()
        self.port.snapshot_positions.return_value=(replace(self.pos,sl=target_sl,tp=target_tp),)
        self.windows.list_windows.side_effect=[[self.window],[]]
        self.port.verify_position_sl_tp(self.pos,target_sl,target_tp)
        self.windows.press.assert_called_once_with(self.window,"esc")


if __name__ == "__main__":
    unittest.main()

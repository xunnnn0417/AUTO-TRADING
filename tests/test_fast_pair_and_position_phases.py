"""Offline tests for explicit fast dual dispatch, phased calibration, and ambiguity guards."""
import unittest
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from tempfile import TemporaryDirectory
from pathlib import Path

from trading_helper.auto_entry import AutoEntryWorkflow,AutoEntryJournal,RecoveryRequired
from trading_helper.position_calibration import (
    scan_position_grid,select_modify_dialog,POSITION_GRID_KEYS,
    POSITION_EDIT_KEYS,
)
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.windows import AutomationError
from test_auto_entry_state_machine import FakeBrokerPort,instruction

class FastPairSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port=FakeBrokerPort()
        self.journal=AutoEntryJournal(Path(self.tmp.name)/"journal.json")
        self.workflow=AutoEntryWorkflow(self.port,self.journal,lambda:None,lambda _:None)
        self.item=instruction()
    def run_case(self,internal="cTrader",external="MT5"):
        return self.workflow.run(
            self.item,internal,external,"A","sheet",
            sync_sl_tp=False,draw_tv=False,fast_pair=True,
        )
    def test_rapid_mode_dispatches_both_before_position_polling(self):
        self.run_case()
        events=self.port.events
        sends=[i for i,x in enumerate(events) if x[0]=="submit"]
        verifies=[i for i,x in enumerate(events) if x[0]=="confirm"]
        self.assertEqual(len(sends),2)
        self.assertTrue(max(sends)<min(verifies))
        self.assertEqual(
            [x[1] for x in events if x[0]=="submit"],
            ["internal","external"]
        )
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        key=self.workflow.fingerprint("A","sheet",accounts,self.item)
        self.assertEqual(self.journal.status(key),"complete")
    def test_fastpair_still_checks_mt5_if_ctrader_readback_unknown(self):
        self.port.fail_confirm="internal"
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        self.assertEqual(
            [e[1] for e in self.port.events if e[0]=="confirm"],
            ["internal","external"],
        )
        self.assertEqual(
            [e[1] for e in self.port.events if e[0]=="submit"],
            ["internal","external"],
        )
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        key=self.workflow.fingerprint("A","sheet",accounts,self.item)
        entry=self.journal.entry(key)
        self.assertEqual(entry["status"],"attention_required")
        self.assertEqual(entry["confirmed_legs"],{"external":"T-external"})
        self.assertNotIn("confirmed_both",entry)

    def test_fastpair_records_internal_if_mt5_readback_unknown(self):
        self.port.fail_confirm="external"
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        key=self.workflow.fingerprint("A","sheet",accounts,self.item)
        entry=self.journal.entry(key)
        self.assertEqual(entry["confirmed_legs"],{"internal":"T-internal"})
        self.assertNotIn("confirmed_both",entry)

    def test_success_stores_both_verified_tickets(self):
        self.run_case()
        accounts=(self.port.accounts["internal"],self.port.accounts["external"])
        key=self.workflow.fingerprint("A","sheet",accounts,self.item)
        entry=self.journal.entry(key)
        self.assertEqual(entry["confirmed_legs"],{
            "internal":"T-internal","external":"T-external",
        })
        self.assertEqual(entry["status"],"complete")

    def test_no_unapproved_platform_pairs(self):
        with self.assertRaisesRegex(AutomationError,"目前只支援"):
            self.run_case("MT5","cTrader")
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))
    def test_failed_first_send_must_not_dispatch_external(self):
        self.port.fail_submit="internal"
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        self.assertEqual(
            [x[1] for x in self.port.events if x[0]=="submit"],["internal"]
        )
    def test_failed_second_send_never_retries_or_pretends_complete(self):
        self.port.fail_submit="external"
        with self.assertRaises(RecoveryRequired):
            self.run_case()
        self.assertEqual(
            [x[1] for x in self.port.events if x[0]=="submit"],
            ["internal","external"]
        )
        self.assertFalse(any(x[0]=="confirm" for x in self.port.events))
    def test_bad_form_and_existing_positions_block_both_clicks(self):
        self.port.bad_form=True
        with self.assertRaises(AutomationError):
            self.run_case()
        self.assertFalse(any(x[0]=="submit" for x in self.port.events))

class PhasedCalibrationUnitTests(unittest.TestCase):
    def test_group_keys_3_and_3(self):
        self.assertEqual(len(POSITION_GRID_KEYS),3)
        self.assertEqual(len(POSITION_EDIT_KEYS),3)
        self.assertFalse(set(POSITION_GRID_KEYS)&set(POSITION_EDIT_KEYS))
    def test_select_only_owned_process_matching_modify_dialog(self):
        main=SimpleNamespace(handle=1,title="cTrader",width=1800)
        one=SimpleNamespace(handle=2,title="Modify order or position - cTrader")
        wrong=SimpleNamespace(handle=3,title="Other program Modify position")
        lookup=lambda handle:123 if handle in (1,2) else 555
        self.assertEqual(
            select_modify_dialog(main,[main,wrong,one],"cTrader",lookup),one
        )
        self.assertIsNone(
            select_modify_dialog(main,[main,wrong],"cTrader",lookup)
        )
    def test_mt5_normal_order_window_is_not_position_modify(self):
        main=SimpleNamespace(handle=1,title="MT5")
        normal=SimpleNamespace(handle=2,title="Order: XAUUSD+ - Gold")
        lookup=lambda h:7
        self.assertIsNone(select_modify_dialog(main,[main,normal],"MT5",lookup))
    def test_failed_grid_scan_returns_no_fake_coordinates(self):
        with patch("pywinauto.Desktop") as desktop:
            desktop.return_value.window.side_effect=RuntimeError("unreadable")
            report=scan_position_grid(
                123,"MT5",
                tuple((k,k) for k in POSITION_GRID_KEYS)
            )
        self.assertFalse(report.candidates)
        self.assertTrue(report.warnings)
    def test_mt5_multiple_blank_win32_rows_fail_closed(self):
        port=DemoUiBrokerPort(MagicMock(),lambda x:None)
        v=MagicMock()
        v.class_name.return_value="SysListView32"
        v.control_id.return_value=10328
        v.is_visible.return_value=True
        v.item_count.return_value=2
        v.columns.return_value=[object()]*10
        v.get_item.return_value.text.return_value=""
        root=MagicMock()
        root.descendants.return_value=[v]
        with patch.object(port,"_bound",return_value=({},SimpleNamespace(handle=90))), \
             patch("pywinauto.Desktop") as dt:
            dt.return_value.window.return_value=root
            with self.assertRaisesRegex(AutomationError,"無法證明空倉"):
                port._mt5_positions(
                    "MT5","external",SimpleNamespace(account_id="123456")
                )

if __name__=="__main__":
    unittest.main()

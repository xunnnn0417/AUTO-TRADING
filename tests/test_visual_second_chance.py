"""Read-only post-timeout position recovery: no duplicate broker orders."""
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from trading_helper.auto_entry import (
    AutoEntryJournal, AutoEntryWorkflow, Position, RecoveryRequired,
)
from trading_helper.windows import AutomationError
from test_auto_entry_state_machine import FakeBrokerPort, instruction


class DelayedPositionBroker(FakeBrokerPort):
    def __init__(self, late_role="external", missing=False,
                 transient=False, wrong_direction=False, duplicates=False):
        super().__init__()
        self.late_role=late_role
        self.missing=missing
        self.transient=transient
        self.wrong_direction=wrong_direction
        self.duplicates=duplicates
        self.snapshot_after_timeout=0
        self.failed_once=False
    def confirm_new_position(self,platform,role,before,direction,volume,account_id):
        if role==self.late_role and not self.failed_once:
            self.failed_once=True
            if not self.missing:
                self.open_positions[role]=(
                    Position(
                        ticket="LATE-"+role,account_id=account_id,
                        platform=platform,symbol="XAUUSD",
                        direction=("SELL" if direction=="BUY" else "BUY")
                          if self.wrong_direction else direction,
                        volume=volume,entry_price=Decimal("4101.65"),
                    ),
                )
            raise AutomationError("position rendering timed out")
        return super().confirm_new_position(
            platform,role,before,direction,volume,account_id)
    def snapshot_positions(self,platform,role):
        if role==self.late_role and self.failed_once:
            self.snapshot_after_timeout+=1
            if self.transient and self.snapshot_after_timeout==1:
                raise AutomationError("temporary cTrader DataGrid UIA read")
            if self.duplicates:
                one=self.open_positions[role][0]
                return (one,Position(
                    ticket="LATE-EXTRA",account_id=one.account_id,
                    platform=one.platform,symbol=one.symbol,
                    direction=one.direction,volume=one.volume,
                    entry_price=one.entry_price,
                ))
        return super().snapshot_positions(platform,role)


class VisualSecondChanceTests(unittest.TestCase):
    def scenario(self,role="external",fast=True,**kwargs):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        port=DelayedPositionBroker(late_role=role,**kwargs)
        logs=[]
        journal=AutoEntryJournal(Path(folder.name)/"trades.json")
        flow=AutoEntryWorkflow(port,journal,lambda:None,logs.append)
        def run():
            return flow.run(instruction(),"cTrader","MT5",
                            "VisualTest","fake-sheet",fast_pair=fast,
                            sync_sl_tp=False,draw_tv=False)
        return port,journal,flow,logs,run

    def test_external_delayed_visible_recovered_without_resend_fast(self):
        port,journal,flow,logs,run=self.scenario()
        run()
        self.assertEqual(
            [e[1] for e in port.events if e[0]=="submit"],
            ["internal","external"],
        )
        self.assertTrue(any("沒有重新送單" in line for line in logs))
        self.assertEqual(journal.status(flow.last_key),"complete")
        self.assertEqual(journal.entry(flow.last_key)["confirmed_legs"]["external"],
                         "LATE-external")

    def test_internal_delayed_visible_recovered_without_resend_fast(self):
        port,journal,flow,logs,run=self.scenario(role="internal")
        run()
        self.assertEqual(
            [e[1] for e in port.events if e[0]=="submit"],
            ["internal","external"],
        )
        self.assertEqual(journal.entry(flow.last_key)["confirmed_legs"]["internal"],
                         "LATE-internal")

    def test_external_delayed_visible_recovered_without_resend_sequential(self):
        port,journal,flow,logs,run=self.scenario(fast=False)
        run()
        self.assertEqual(
            [e[1] for e in port.events if e[0]=="submit"],
            ["internal","external"],
        )
        self.assertEqual(journal.status(flow.last_key),"complete")

    def test_temporary_unreadable_grid_rechecked_once(self):
        port,journal,flow,logs,run=self.scenario(transient=True)
        run()
        self.assertEqual(port.snapshot_after_timeout,2)
        self.assertTrue(any("持倉補讀未成功" in msg for msg in logs))
        self.assertEqual(len([x for x in port.events if x[0]=="submit"]),2)

    def test_late_ctrader_external_binding_registered_for_sl_tp_sync(self):
        from unittest.mock import MagicMock
        port,journal,flow,logs,_=self.scenario()
        port.accounts=FakeBrokerPort(mt5_internal=True).accounts
        remember=MagicMock()
        port.remember_verified_position_role=remember
        flow.run(instruction(),"MT5","cTrader","reverse-late",
                 "fake-sheet",fast_pair=True,sync_sl_tp=False,draw_tv=False)
        remember.assert_called_once()
        plat,role,position=remember.call_args.args
        self.assertEqual((plat,role,position.ticket),
                         ("cTrader","external","LATE-external"))

    def test_empty_twice_is_unknown_not_rejected(self):
        port,journal,flow,logs,run=self.scenario(missing=True)
        with self.assertRaises(RecoveryRequired):
            run()
        self.assertEqual(port.snapshot_after_timeout,2)
        self.assertEqual(len([x for x in port.events if x[0]=="submit"]),2)
        self.assertNotIn("rescued_role",journal.entry(flow.last_key))

    def test_wrong_direction_does_not_count_as_correct_fill(self):
        port,journal,flow,logs,run=self.scenario(wrong_direction=True)
        with self.assertRaises(RecoveryRequired):
            run()
        self.assertEqual(len([x for x in port.events if x[0]=="submit"]),2)
        self.assertNotIn("rescued_role",journal.entry(flow.last_key))

    def test_multiple_new_positions_stop_without_resend(self):
        port,journal,flow,logs,run=self.scenario(duplicates=True)
        with self.assertRaises(RecoveryRequired):
            run()
        self.assertEqual(len([x for x in port.events if x[0]=="submit"]),2)
        self.assertNotIn("rescued_role",journal.entry(flow.last_key))


if __name__=="__main__":
    unittest.main()
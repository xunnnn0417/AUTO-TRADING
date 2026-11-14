"""Fault injection never decides recovery: all broker activity is synthetic."""
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_helper.auto_entry import AutoEntryJournal,AutoEntryWorkflow,Position,RecoveryRequired
from trading_helper.windows import AutomationError
from test_auto_entry_state_machine import instruction
from test_single_leg_test_mode import SingleLegFakePort


class FaultPort(SingleLegFakePort):
    def __init__(self,scenario,reverse=False):
        super().__init__(mt5_internal=reverse)
        self.scenario=scenario
        self.injected=False
        self.on_fault=lambda:None
        self.read_error=None

    def mark_fault(self):
        self.injected=True
        self.events.append(("fault",self.scenario))
        self.on_fault()

    def confirm_new_position(self,*args):
        position=super().confirm_new_position(*args)
        if not self.injected and self.scenario.startswith("reentry:"):
            self.mark_fault()
        return position

    def close_position_once(self,position,role):
        super().close_position_once(position,role)
        if not self.injected:
            self.mark_fault()

    def snapshot_positions(self,platform,role):
        if self.injected and self.read_error==role:
            raise AutomationError("模擬持倉無法讀取")
        return super().snapshot_positions(platform,role)

    def position_for(self,role,ticket="UNEXPECTED"):
        item=instruction()
        account=self.accounts[role]
        direction,values=((item.internal_direction,item.internal) if role=="internal"
                          else (item.external_direction,item.external))
        return Position(ticket,account.account_id,account.platform,item.symbol,direction,
                        values.lot,D("4100"),D("4090") if direction=="BUY" else D("4110"),
                        D("4120") if direction=="BUY" else D("4080"))


class RecoveryReviewTests(unittest.TestCase):
    @contextmanager
    def scenario(self,name,reverse=False):
        with tempfile.TemporaryDirectory() as tmp:
            port=FaultPort(name,reverse)
            flow=AutoEntryWorkflow(port,AutoEntryJournal(Path(tmp)/"journal.json"),lambda:None,lambda _:None)
            platforms=("MT5","cTrader") if reverse else ("cTrader","MT5")
            yield port,flow,platforms

    def execute(self,flow,platforms,name):
        return flow.run_test_scenario(instruction(),*platforms,"test","sheet",
                                      scenario=name,test_run_id="CASE",fast_pair=True)

    def after_fault(self,port):
        index=next(i for i,e in enumerate(port.events) if e[0]=="fault")
        return port.events[index+1:]

    def test_all_four_scenarios_read_both_real_states_before_recovery_in_both_platform_orders(self):
        for reverse in (False,True):
            for name in ("reentry:internal","reentry:external","close:internal","close:external"):
                with self.subTest(reverse=reverse,name=name),self.scenario(name,reverse) as (port,flow,platforms):
                    with patch.object(flow,"_review_recovery_pair",wraps=flow._review_recovery_pair) as review:
                        self.execute(flow,platforms,name)
                    self.assertGreater(review.call_count,0)
                    after=self.after_fault(port)
                    action=next(i for i,e in enumerate(after) if e[0] in ("submit","close"))
                    self.assertEqual({e[1] for e in after[:action] if e[0]=="baseline"},{"internal","external"})
                    self.assertEqual({e[1] for e in after[:action] if e[0]=="account"},{"internal","external"})

    def test_omitted_side_already_has_a_position_never_gets_a_duplicate(self):
        for reverse in (False,True):
            for role in ("internal","external"):
                name="reentry:"+role
                with self.subTest(reverse=reverse,role=role),self.scenario(name,reverse) as (port,flow,platforms):
                    port.on_fault=lambda:port.open_positions.update({role:(port.position_for(role),)})
                    with self.assertRaisesRegex(RecoveryRequired,"仍有持倉"):
                        self.execute(flow,platforms,name)
                    self.assertFalse(any(e[0] in ("submit","close") for e in self.after_fault(port)))

    def test_missing_counterpart_or_unreadable_state_cannot_trigger_scripted_recovery(self):
        for role in ("internal","external"):
            for failure in ("empty","unknown"):
                name="reentry:"+role
                other="external" if role=="internal" else "internal"
                with self.subTest(role=role,failure=failure),self.scenario(name) as (port,flow,platforms):
                    if failure=="empty":
                        port.on_fault=lambda:port.open_positions.update({other:()})
                    else:
                        port.on_fault=lambda:setattr(port,"read_error",other)
                    with self.assertRaises(RecoveryRequired):
                        self.execute(flow,platforms,name)
                    self.assertFalse(any(e[0] in ("submit","close") for e in self.after_fault(port)))

    def test_close_scenario_stops_when_the_closed_side_reappears(self):
        for role in ("internal","external"):
            name="close:"+role
            with self.subTest(role=role),self.scenario(name) as (port,flow,platforms):
                port.on_fault=lambda:port.open_positions.update({role:(port.position_for(role),)})
                with self.assertRaisesRegex(RecoveryRequired,"編號已改變"):
                    self.execute(flow,platforms,name)
                self.assertFalse(any(e[0] in ("submit","close") for e in self.after_fault(port)))

    def test_both_sides_gone_stops_instead_of_reopening_the_selected_side(self):
        for name in ("close:internal","close:external"):
            with self.subTest(name=name),self.scenario(name) as (port,flow,platforms):
                port.on_fault=lambda:port.open_positions.update(internal=(),external=())
                result=self.execute(flow,platforms,name)
                self.assertEqual(result["outcome"],"both_closed_waiting_user")
                self.assertFalse(any(e[0] in ("submit","close") for e in self.after_fault(port)))

    def test_changed_counterpart_or_account_stops_every_scenario(self):
        for name in ("reentry:internal","reentry:external","close:internal","close:external"):
            role=name.split(":")[1]
            other="external" if role=="internal" else "internal"
            for change in ("ticket","account","volume"):
                with self.subTest(name=name,change=change),self.scenario(name) as (port,flow,platforms):
                    def mutate():
                        if change=="account":
                            port.accounts[other]=replace(port.accounts[other],account_id="333333")
                        else:
                            old=port.open_positions[other][0]
                            updated=replace(old,ticket="CHANGED") if change=="ticket" else replace(old,volume=D("99"))
                            port.open_positions[other]=(updated,)
                    port.on_fault=mutate
                    with self.assertRaises(RecoveryRequired):
                        self.execute(flow,platforms,name)
                    self.assertFalse(any(e[0] in ("submit","close") for e in self.after_fault(port)))

    def test_internal_close_rechecks_absent_internal_before_closing_external(self):
        name="close:internal"
        with self.scenario(name) as (port,flow,platforms):
            original=flow._review_recovery_pair
            def review(*args,**kwargs):
                result=original(*args,**kwargs)
                port.open_positions["internal"]=(port.position_for("internal"),)
                return result
            with patch.object(flow,"_review_recovery_pair",side_effect=review):
                with self.assertRaisesRegex(RecoveryRequired,"另一邊目前也有持倉"):
                    self.execute(flow,platforms,name)
            self.assertEqual([role for role,_ in port.closed],["internal"])


if __name__ == "__main__": unittest.main()

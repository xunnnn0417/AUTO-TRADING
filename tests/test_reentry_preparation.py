"""Real recovery orchestration with offline, lifecycle-aware broker forms."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.auto_entry import AutoEntryJournal, AutoEntryWorkflow, RecoveryRequired
from trading_helper.demo_broker_port import DemoUiBrokerPort
from trading_helper.gui import TradingHelperApp
from trading_helper.test_mode import effective_test_symbol, test_symbol_scope
from trading_helper.windows import AutomationError
from test_auto_entry_state_machine import instruction
from test_single_leg_test_mode import SingleLegFakePort, side_position, CloseBrokerPort


class LifecyclePort(SingleLegFakePort):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.forms={"internal":True,"external":True}
        self.after_prepare=lambda:None

    def prepare_reentry(self, platform, role, item):
        super().prepare_reentry(platform,role,item)
        self.forms[role]=True
        self.after_prepare()

    def submit_once(self, platform, role, *args, **kwargs):
        if not self.forms[role]:
            raise AutomationError("訂單視窗已關閉，缺少本次填入核對")
        result=super().submit_once(platform,role,*args,**kwargs)
        self.forms[role]=False
        return result


class ReentryPreparationTests(unittest.TestCase):
    def flow(self,port):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return AutoEntryWorkflow(port,AutoEntryJournal(Path(temp.name)/"journal.json"),
                                 lambda:None,lambda _message:None)

    def test_external_close_reopens_and_fills_form_before_one_reentry_for_both_platform_orders(self):
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                port=LifecyclePort(mt5_internal=reverse)
                platforms=("MT5","cTrader") if reverse else ("cTrader","MT5")
                result=self.flow(port).run_test_scenario(
                    instruction(),*platforms,"test","sheet",scenario="close:external",
                    test_run_id="LIFECYCLE",fast_pair=True,
                )
                self.assertEqual(result["outcome"],"external_reentered")
                prepares=[i for i,e in enumerate(port.events) if e==("prepare","external")]
                self.assertEqual(len(prepares),1)
                i=prepares[0]
                submit=next(j for j in range(i+1,len(port.events))
                            if port.events[j]==("submit","external"))
                reviewed=port.events[i+1:submit]
                for side in ("internal","external"):
                    self.assertIn(("baseline",side),reviewed)
                self.assertEqual(port.events.count(("submit","external")),2)

    def test_user_missing_leg_prepares_form_and_does_not_send_counterpart(self):
        for side in ("internal","external"):
            with self.subTest(side=side):
                port=LifecyclePort()
                other="external" if side=="internal" else "internal"
                port.open_positions[other]=(side_position(other),)
                port.forms[side]=False
                self.flow(port).run_single_leg_test(
                    instruction(),"cTrader","MT5","test","sheet",
                    role=side,sync_sl_tp=True,operation="user",
                )
                self.assertIn(("prepare",side),port.events)
                self.assertEqual([e for e in port.events if e[0]=="submit"],[("submit",side)])

    def test_late_fill_or_changed_counterpart_during_preparation_stops_submission(self):
        for change in ("filled","closed","ticket","account"):
            with self.subTest(change=change):
                port=LifecyclePort()
                original=side_position("internal")
                port.open_positions["internal"]=(original,)
                def mutate():
                    if change=="filled":
                        port.open_positions["external"]=(side_position("external"),)
                    elif change=="closed":
                        port.open_positions["internal"]=()
                    elif change=="ticket":
                        port.open_positions["internal"]=(replace(original,ticket="OTHER"),)
                    else:
                        port.accounts["internal"]=replace(port.accounts["internal"],account_id="333333")
                port.after_prepare=mutate
                with self.assertRaises(RecoveryRequired):
                    self.flow(port).run_single_leg_test(
                        instruction(),"cTrader","MT5","test","sheet",
                        role="external",sync_sl_tp=True,
                    )
                self.assertFalse(any(e[0]=="submit" for e in port.events))

    def test_deadline_expires_during_preparation_without_submit(self):
        port=LifecyclePort()
        port.open_positions["internal"]=(side_position("internal"),)
        clock=[1.0]
        port.after_prepare=lambda:clock.__setitem__(0,20.0)
        with patch("trading_helper.auto_entry.time.monotonic",side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(RecoveryRequired,"15 秒"):
                self.flow(port).run_single_leg_test(
                    instruction(),"cTrader","MT5","test","sheet",
                    role="external",sync_sl_tp=True,submit_deadline=15.0,
                )
        self.assertFalse(any(e[0]=="submit" for e in port.events))

    def test_production_preparation_reuses_ordinary_fill_and_sets_instrument(self):
        automation=SimpleNamespace(fill=MagicMock())
        port=DemoUiBrokerPort(automation,lambda _message:None)
        with test_symbol_scope("ETHUSD"):
            port.prepare_reentry("MT5","external",instruction())
            self.assertEqual(port._expected_symbol,"ETHUSD")
        automation.fill.assert_called_once_with("MT5","external",instruction())

    def test_full_user_reentry_preserves_symbol_inside_worker_without_another_test(self):
        observed=[]
        fake=SimpleNamespace(_fill_both_task=lambda *a,**kw:observed.append(
            (effective_test_symbol("XAUUSD"),kw)))
        TradingHelperApp._fill_approved_reentry(fake,{
            "internal_platform":"cTrader","external_platform":"MT5","symbol":"ETHUSD",
        })
        self.assertEqual(observed[0][0],"ETHUSD")
        self.assertNotIn("test_scenario",observed[0][1])
        self.assertEqual(effective_test_symbol("XAUUSD"),"XAUUSD")

    def test_verified_empty_close_receipt_saves_target_reread_but_still_checks_other(self):
        port=SingleLegFakePort()
        port.open_positions["internal"]=(side_position("internal"),)
        close=port.close_position_once
        def close_with_receipt(pos,role):
            close(pos,role)
            return ()
        port.close_position_once=close_with_receipt
        self.flow(port).run_single_leg_close_test(
            instruction(),"cTrader","MT5","test","sheet",role="internal",
            expected_ticket="OLD-I",require_other_empty=True,
        )
        self.assertEqual(port.events.count(("baseline","internal")),1)
        self.assertEqual(port.events.count(("baseline","external")),2)

    def test_production_close_returns_actual_verified_empty_snapshot(self):
        port=CloseBrokerPort((side_position("internal"),))
        self.assertEqual(port.close_position_once(side_position("internal"),"internal"),())
        self.assertEqual(len(port.automation.windows.clicks),1)

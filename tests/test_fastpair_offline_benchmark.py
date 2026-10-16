"""Safe offline simulation of dispatch gaps and unknown/rejected fills."""
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from trading_helper.auto_entry import AutoEntryJournal,AutoEntryWorkflow,RecoveryRequired
from trading_helper.windows import AutomationError
from test_auto_entry_state_machine import FakeBrokerPort,instruction

class TimedFake(FakeBrokerPort):
    def __init__(self):
        super().__init__()
        self.submit_times={}
        self.confirm_times={}
    def submit_once(self,*args):
        role=args[1]
        self.submit_times[role]=time.perf_counter()
        time.sleep(0.020)
        return super().submit_once(*args)
    def confirm_new_position(self,*args):
        role=args[1]
        self.confirm_times[role]=time.perf_counter()
        time.sleep(0.090)
        return super().confirm_new_position(*args)

class FastPairOfflineBenchmark(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port=TimedFake()
        self.journal=AutoEntryJournal(Path(self.tmp.name)/"journal.json")
        self.logs=[]
        self.flow=AutoEntryWorkflow(self.port,self.journal,lambda:None,self.logs.append)
    def run_flow(self,fast):
        return self.flow.run(instruction(),"cTrader","MT5","bench","fake-sheet",
                             fast_pair=fast,sync_sl_tp=False,draw_tv=False)
    def test_fastpair_measures_dispatch_gap_without_order_io(self):
        self.run_flow(True)
        self.assertEqual([ev[1] for ev in self.port.events if ev[0]=="submit"],
                         ["internal","external"])
        gap=self.port.submit_times["external"]-self.port.submit_times["internal"]
        self.assertGreaterEqual(gap,0.020)
        self.assertLess(gap,0.4)
        self.assertLess(self.port.submit_times["external"],self.port.confirm_times["internal"])
        self.assertTrue(any("送單呼叫開始間隔" in msg for msg in self.logs))
    def test_sequential_waits_for_first_side_confirmation(self):
        self.run_flow(False)
        gap=self.port.submit_times["external"]-self.port.submit_times["internal"]
        self.assertGreaterEqual(gap,0.10)
        self.assertLess(self.port.confirm_times["internal"],self.port.submit_times["external"])
    def test_explicit_second_side_rejection_no_unsafe_retry(self):
        self.port.fail_submit="external"
        with self.assertRaises(RecoveryRequired):self.run_flow(True)
        self.assertEqual(len(self.port.submit_times),2)
        key=self.flow.fingerprint("bench","fake-sheet",
            (self.port.accounts["internal"],self.port.accounts["external"]),instruction())
        self.assertEqual(self.journal.status(key),"attention_required")
        with self.assertRaises(RecoveryRequired):self.run_flow(True)
        self.assertEqual(len([e for e in self.port.events if e[0]=="submit"]),2)
    def test_first_side_submit_timeout_blocks_second_side(self):
        self.port.fail_submit="internal"
        with self.assertRaises(RecoveryRequired):self.run_flow(True)
        self.assertEqual(list(self.port.submit_times),["internal"])
    def test_first_readback_unknown_still_checks_second_but_no_third_order(self):
        self.port.fail_confirm="internal"
        with self.assertRaises(RecoveryRequired):self.run_flow(True)
        self.assertEqual(set(self.port.confirm_times),{"internal","external"})
        self.assertEqual(len([e for e in self.port.events if e[0]=="submit"]),2)
    def test_wrong_account_preflight_never_submits(self):
        from dataclasses import replace
        self.port.accounts["external"]=replace(self.port.accounts["external"],is_demo=False)
        with self.assertRaises(AutomationError):self.run_flow(True)
        self.assertFalse(self.port.submit_times)

if __name__=="__main__":unittest.main()
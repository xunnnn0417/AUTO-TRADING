"""Local flow timing reports are structured, safe, and offline-testable."""
import json
from pathlib import Path
import tempfile
import unittest

from trading_helper.auto_entry import AutoEntryJournal, AutoEntryWorkflow
from trading_helper.phase_timing_report import (
    LocalPhaseTimingStore, PhaseTimingRun, _ACTIVE_REPORT, timed_phase,
)
from trading_helper.gui import TradingHelperApp
from test_auto_entry_state_machine import FakeBrokerPort, instruction


class PhaseTimingReportTests(unittest.TestCase):
    def test_nested_fill_phase_is_recorded_with_platform_and_role(self):
        report = PhaseTimingRun("fill", {})
        token = _ACTIVE_REPORT.set(report)
        try:
            with timed_phase("OCR核對cTrader帳號", platform="cTrader", role="internal"):
                pass
        finally:
            _ACTIVE_REPORT.reset(token)

        phase = report.phases[0]
        self.assertEqual(phase["phase"], "OCR核對cTrader帳號")
        self.assertEqual(phase["platform"], "cTrader")
        self.assertEqual(phase["role"], "internal")
        self.assertEqual(phase["outcome"], "completed")

    def make_flow(self, folder, *, bad_form=False):
        port = FakeBrokerPort()
        port.bad_form = bad_form
        store = LocalPhaseTimingStore(Path(folder) / "reports" / "timings.jsonl")
        flow = AutoEntryWorkflow(
            port,
            AutoEntryJournal(Path(folder) / "journal.json"),
            lambda: None,
            lambda _message: None,
            timing_store=store,
        )
        return flow, port, store.path

    def read_report(self, path):
        rows = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)
        return json.loads(rows[0]), rows[0]

    def test_complete_flow_saves_platform_phase_durations_without_trade_data(self):
        with tempfile.TemporaryDirectory() as folder:
            flow, _port, path = self.make_flow(folder)
            flow.run(
                instruction(), "cTrader", "MT5", "profile", "sheet-url",
                sync_sl_tp=False, draw_tv=False,
            )
            report, raw = self.read_report(path)

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["outcome"], "completed")
        self.assertEqual(report["platforms"], {
            "internal": "cTrader", "external": "MT5",
        })
        names = {phase["phase"] for phase in report["phases"]}
        self.assertTrue({
            "雙邊自動進場", "確認 Demo 帳戶", "讀取交易前持倉",
            "送單表單預檢", "單側送單與成交確認", "成交持倉回讀",
        } <= names)
        self.assertTrue(all(
            isinstance(phase["duration_ms"], (int, float))
            and phase["duration_ms"] >= 0
            for phase in report["phases"]
        ))
        for private_value in (
            "111111", "222222", "XAUUSD", "sheet-url", "T-internal",
        ):
            self.assertNotIn(private_value, raw)

    def test_interrupted_preflight_is_saved_without_exception_text(self):
        with tempfile.TemporaryDirectory() as folder:
            flow, port, path = self.make_flow(folder, bad_form=True)
            with self.assertRaises(Exception):
                flow.run(
                    instruction(), "cTrader", "MT5", "profile", "secret-url",
                    sync_sl_tp=False, draw_tv=False,
                )
            report, raw = self.read_report(path)

        self.assertEqual(report["outcome"], "interrupted")
        self.assertEqual(report["failed_phase"], "送單表單預檢")
        self.assertTrue(report["error_type"])
        self.assertFalse(any(event[0] == "submit" for event in port.events))
        self.assertNotIn("bad form", raw)
        self.assertNotIn("secret-url", raw)

    def test_gui_fill_both_starts_the_report_before_broker_entry_phases(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as folder:
            store = LocalPhaseTimingStore(Path(folder) / "timings.jsonl")
            owner = SimpleNamespace(
                phase_timing_store=store,
                _require_instruction=MagicMock(return_value="offline-item"),
                automation=SimpleNamespace(fill=MagicMock()),
                log=MagicMock(),
                _auto_entry_after_fill_both_pending=MagicMock(),
            )
            TradingHelperApp._fill_both_task(
                owner,"cTrader","MT5",False,
            )
            report, _raw = self.read_report(store.path)

        names = [phase["phase"] for phase in report["phases"]]
        self.assertIn("填入兩邊與自動進場", names)
        self.assertIn("填入場內", names)
        self.assertIn("填入場外", names)
        self.assertEqual(owner.automation.fill.call_count, 2)
        self.assertEqual(report["outcome"], "completed")


if __name__ == "__main__":
    unittest.main()

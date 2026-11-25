"""Live hedge P/L: read-only MT5 side, the other side estimated by ratio."""
import unittest
from types import SimpleNamespace

from trading_helper.live_pnl import SideTargets, model, mt5_targets, side_targets


class LivePnlTests(unittest.TestCase):
    def test_sheet_distances_become_money(self):
        t = side_targets(-12.56, 46.63, 0.19, 100)
        self.assertAlmostEqual(t.sl, -238.64)
        self.assertAlmostEqual(t.tp, 885.97)

    def test_external_mt5_estimates_internal_by_the_same_progress(self):
        # 場外 SL −450 / TP +117; now −164 -> about half way (0.504).
        m = model(mt5_role="external", mt5_pnl=-164, mt5=SideTargets(tp=117, sl=-450),
                  other=SideTargets(tp=875, sl=-576), price=3555.41,
                  mt5_sl_price=3563.4, mt5_tp_price=3550.7)
        self.assertAlmostEqual(m["x"], 286 / 567)
        # 場外 at TP <=> 場內 at SL: 875 + x * (−576 − 875)
        self.assertAlmostEqual(m["internal"]["pnl"], round(875 - 286 / 567 * 1451, 2))
        self.assertAlmostEqual(m["zero"], 450 / 567)
        self.assertEqual(m["estimated"], "internal")
        self.assertEqual((m["sl_price"], m["tp_price"]), (3563.4, 3550.7))

    def test_internal_mt5_flips_the_bar(self):
        # MT5 is 場內: 場內 at its TP means 場外 at its SL (left end).
        m = model(mt5_role="internal", mt5_pnl=875, mt5=SideTargets(tp=875, sl=-576),
                  other=SideTargets(tp=117, sl=-450), price=1.0, mt5_sl_price=2.0, mt5_tp_price=3.0)
        self.assertAlmostEqual(m["x"], 0.0)
        self.assertAlmostEqual(m["external"]["pnl"], -450)
        self.assertEqual((m["sl_price"], m["tp_price"]), (3.0, 2.0))

    def test_position_sl_tp_prices_win_over_the_sheet(self):
        pos = SimpleNamespace(type=1, volume=0.25, price_open=3557.1, sl=3563.4, tp=3550.7)
        targets, sl_price, tp_price = mt5_targets(pos, 100, SideTargets(tp=1, sl=-1))
        self.assertAlmostEqual(targets.tp, 160.0)   # (3557.1−3550.7)×0.25×100
        self.assertAlmostEqual(targets.sl, -157.5)
        # No SL/TP on the position: the sheet amounts, prices derived from them.
        bare = SimpleNamespace(type=1, volume=0.25, price_open=3557.1, sl=0.0, tp=0.0)
        targets, sl_price, tp_price = mt5_targets(bare, 100, SideTargets(tp=117, sl=-450))
        self.assertEqual((targets.tp, targets.sl), (117, -450))
        self.assertAlmostEqual(tp_price, 3557.1 - 117 / 25)
        self.assertAlmostEqual(sl_price, 3557.1 + 450 / 25)


class TestProfileSymbolTests(unittest.TestCase):
    def test_test_profile_reads_the_crypto_from_the_mt5_window_title(self):
        from unittest.mock import patch
        from trading_helper import gui
        app = SimpleNamespace(
            internal_platform=SimpleNamespace(currentText=lambda: "cTrader"),
            external_platform=SimpleNamespace(currentText=lambda: "MT5"),
            log=lambda _t: None)
        for title, expected in (("ETHUSD,M1 - 新訂單", "ETHUSD"), ("BTCUSD: Bitcoin", "BTCUSD"),
                                ("XAUUSD,H1", ""), ("", "")):
            with self.subTest(title=title), patch.object(
                    gui, "_bound_broker_main", return_value=SimpleNamespace(title=title)):
                self.assertEqual(gui.TradingHelperApp._test_profile_symbol(app), expected)
        self.assertEqual(gui.TEST_PROFILE_NAME, "測試")


class LivePublishTests(unittest.TestCase):
    def test_moving_pnl_never_changes_the_command_revision(self):
        import time
        from trading_helper.remote_control import MobileServer
        sent = []
        fake = SimpleNamespace(
            LIVE_KEYS=MobileServer.LIVE_KEYS, _last_encoded=None, lease_until=0.0,
            revision=0, lease="", state=None, sockets={"sock": "phone"},
            store=SimpleNamespace(authorized=lambda _d: True, latest=lambda _d: None),
            send=lambda _sock, data: sent.append(data))
        MobileServer.publish(fake, {"phase": "就緒", "live_pnl": {"x": 0.1}})
        revision, lease = fake.revision, fake.lease
        self.assertEqual(sent[-1]["type"], "state")
        fake.lease_until = time.monotonic() + 30
        MobileServer.publish(fake, {"phase": "就緒", "live_pnl": {"x": 0.2}})
        self.assertEqual((fake.revision, fake.lease), (revision, lease))
        self.assertEqual(sent[-1]["live_pnl"], {"x": 0.2})
        self.assertEqual(sent[-1]["type"], "live")
        self.assertEqual(fake.state["live_pnl"], {"x": 0.2})


if __name__ == "__main__":
    unittest.main()


class ClosedDetectionTests(unittest.TestCase):
    """Only a real close (same account + MT5 exit deal) may start the
    after-close update; another 方案's empty account must not."""

    def setUp(self):
        from trading_helper.live_pnl import LivePnlMonitor
        NS = SimpleNamespace
        self.closed = []
        self.mon = LivePnlMonitor(lambda: None, lambda _v: None, closed=self.closed.append)
        self.deals = []
        self.mt = NS(positions=[NS(ticket=7)], account=NS(login=1, server="S"),
                     history_deals_get=lambda position: self.deals)
        self.mt.account_info = lambda: self.mt.account
        self.mt.positions_get = lambda: self.mt.positions
        self.mt.initialize = lambda **_k: True
        self.entry = {"profile": "測試", "terminal": "T1", "mt5_role": "external",
                      "account": NS(account_id="1", server="S")}
        self.mon._read_account(self.mt, self.entry)   # ticket 7 seen open
        self.mt.positions = []

    def test_exit_deal_on_the_same_account_is_a_close(self):
        self.deals = [SimpleNamespace(entry=0), SimpleNamespace(entry=1)]
        self.mon._read_account(self.mt, self.entry)
        self.assertEqual(self.closed, [{"ticket": 7, "profile": "測試", "outcome": None}])

    def test_tp_or_sl_close_says_which_external_side_hit(self):
        # MT5 is 場外 here: its own TP close (reason 5) is 場外止盈.
        self.deals = [SimpleNamespace(entry=1, reason=5)]
        self.mon._read_account(self.mt, self.entry)
        self.assertEqual(self.closed[-1]["outcome"], "tp")
        from trading_helper.live_pnl import LivePnlMonitor
        # MT5 is 場內: its SL (reason 4) means 場外 hit TP; manual close = none.
        self.deals = [SimpleNamespace(entry=1, reason=4)]
        self.assertEqual(LivePnlMonitor._close_outcome(self.mt, 7, "internal"), "tp")
        self.deals = [SimpleNamespace(entry=1, reason=0)]
        self.assertIsNone(LivePnlMonitor._close_outcome(self.mt, 7, "external"))

    def test_other_account_without_positions_is_not_a_close(self):
        self.deals = [SimpleNamespace(entry=1)]
        self.mt.account = SimpleNamespace(login=2, server="S")
        other = dict(self.entry, profile="別的", terminal="T2",
                     account=SimpleNamespace(account_id="2", server="S"))
        self.mon._read_account(self.mt, other)
        self.assertEqual(self.closed, [])
        self.assertTrue(self.mon._has_position["測試"])   # still open in its own account

    def test_no_exit_deal_is_not_a_close(self):
        self.deals = [SimpleNamespace(entry=0)]
        self.mon._read_account(self.mt, self.entry)
        self.assertEqual(self.closed, [])


class MultiProfileTests(unittest.TestCase):
    """目前持倉 shows the active 方案, or another one that holds a position;
    each position's amounts are remembered from opening until closing."""

    def make(self, tmp):
        from trading_helper.live_pnl import LivePnlMonitor
        NS = SimpleNamespace
        mon = LivePnlMonitor(lambda: None, lambda _v: None, store_path=tmp + "/t.json")
        accounts = {"T1": NS(login=1, server="S", positions=[]),
                    "T2": NS(login=2, server="S", positions=[
                        NS(ticket=9, time_msc=1, symbol="XAUUSD", type=0, volume=0.2, price_open=4000.0,
                           sl=0.0, tp=0.0, profit=10.0, price_current=4005.0)])}
        mt = NS(current="T1", history_deals_get=lambda position: [])
        def initialize(path, timeout):
            mt.current = path
            return True
        mt.initialize = initialize
        mt.account_info = lambda: accounts[mt.current]
        mt.positions_get = lambda: accounts[mt.current].positions
        mt.symbol_info = lambda _s: NS(trade_contract_size=100)
        entries = [{"profile": "A", "terminal": "T1", "mt5_role": "external",
                    "account": NS(account_id="1", server="S"), "instruction": None},
                   {"profile": "B", "terminal": "T2", "mt5_role": "external",
                    "account": NS(account_id="2", server="S"), "instruction": None}]
        return mon, mt, entries

    def test_shows_the_other_profile_with_a_position(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mon, mt, entries = self.make(tmp)
            mon._targets[9] = {"profile": "B", "mt5_role": "external",
                               "mine": [117.0, -450.0], "other": [875.0, -576.0]}
            out = mon._tick(mt, {"active": "A", "profiles": entries}, 100.0)
            self.assertEqual((out["profile"], out["choices"]), ("B", ["B"]))
            self.assertIsNotNone(out["state"])

    def test_amounts_are_saved_until_the_position_closes(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mon, mt, entries = self.make(tmp)
            side = SimpleNamespace(sl_points=10, tp_points=5, lot=0.2)
            entries[1]["instruction"] = SimpleNamespace(external=side, internal=side)
            mon._tick(mt, {"active": "B", "profiles": entries}, 100.0)
            saved = json.load(open(tmp + "/t.json", encoding="utf-8"))
            self.assertIn("9", saved)
            mt.current = "T2"
            mt.account_info().positions = []
            mon._tick(mt, {"active": "B", "profiles": entries}, 200.0)
            self.assertEqual(json.load(open(tmp + "/t.json", encoding="utf-8")), {})


class StaleTargetTests(unittest.TestCase):
    def test_positions_closed_while_not_running_are_forgotten(self):
        import tempfile
        from trading_helper.live_pnl import LivePnlMonitor
        NS = SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            mon = LivePnlMonitor(lambda: None, lambda _v: None, store_path=tmp + "/t.json")
            mon._targets = {5: {"profile": "A", "mine": [1, -1], "other": [1, -1]},
                            6: {"profile": "B", "mine": [1, -1], "other": [1, -1]}}
            closed = []
            mon.closed = closed.append
            mt = NS(account=NS(login=1, server="S"), history_deals_get=lambda position: [NS(entry=1)])
            mt.account_info = lambda: mt.account
            mt.positions_get = lambda: []
            mt.initialize = lambda **_k: True
            mon._read_account(mt, {"profile": "A", "terminal": "T", "account": NS(account_id="1", server="S")})
            self.assertEqual(list(mon._targets), [6])   # A's old ticket dropped, B untouched
            self.assertEqual(closed, [])                # no after-close update for it


class MainScreenLiveProfileTests(unittest.TestCase):
    """Main screen shows the same 方案 as the side panel / phone."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        import sys
        sys.path.insert(0, "tests")
        import test_compact_followup_controls as fx
        fx.CompactFollowUpControlsTests.setUp(self)
        self._fx = fx

    def tearDown(self):
        self._fx.CompactFollowUpControlsTests.tearDown(self)

    def test_main_follows_the_shared_choice(self):
        w = self.w
        state = {"x": 0.5, "zero": 0.5}
        w._show_live_pnl({"profile": "lark", "choices": ["測試", "lark"], "state": state})
        self.assertEqual(w.live_pnl_bar.state, state)          # shown even if not active
        self.assertEqual(w.live_pnl_profile.currentText(), "lark")
        self.assertFalse(w.live_pnl_profile.locked)
        w.set_live_preference("測試")
        self.assertEqual(w._live_prefer, "測試")

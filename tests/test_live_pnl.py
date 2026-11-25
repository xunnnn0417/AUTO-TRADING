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
        self.assertEqual(sent[-1], {"type": "live", "live_pnl": {"x": 0.2}})
        self.assertEqual(fake.state["live_pnl"], {"x": 0.2})


if __name__ == "__main__":
    unittest.main()


class ClosedDetectionTests(unittest.TestCase):
    """Only a real close (same account + MT5 exit deal) may start the
    after-close update; another 方案's empty account must not."""

    def _monitor(self, deals):
        from trading_helper.live_pnl import LivePnlMonitor
        NS = SimpleNamespace
        closed = []
        mon = LivePnlMonitor(lambda: None, lambda _v: None, closed=closed.append)
        mon._connected = "T1"
        mt = NS(positions=[], account=NS(login=1, server="S"),
                history_deals_get=lambda position: deals)
        mt.account_info = lambda: mt.account
        mt.positions_get = lambda: mt.positions
        mt.initialize = lambda **_k: True
        mon._last_ticket, mon._last_key = 7, ("T1", "1", "s")
        mon._ticket_profile[7] = "測試"
        return mon, mt, closed

    def ctx(self, NS, terminal="T1", account="1"):
        return {"terminal": terminal, "account": NS(account_id=account, server="S")}

    def test_exit_deal_on_the_same_account_is_a_close(self):
        NS = SimpleNamespace
        mon, mt, closed = self._monitor([NS(entry=0), NS(entry=1)])
        mon._read(mt, self.ctx(NS))
        self.assertEqual(closed, [{"ticket": 7, "profile": "測試"}])

    def test_other_account_without_positions_is_not_a_close(self):
        NS = SimpleNamespace
        mon, mt, closed = self._monitor([NS(entry=1)])
        mt.account = NS(login=2, server="S")
        mon._connected = "T2"
        mon._read(mt, self.ctx(NS, terminal="T2", account="2"))
        self.assertEqual(closed, [])
        self.assertIsNone(mon._last_ticket)

    def test_no_exit_deal_is_not_a_close(self):
        NS = SimpleNamespace
        mon, mt, closed = self._monitor([NS(entry=0)])
        mon._read(mt, self.ctx(NS))
        self.assertEqual(closed, [])

"""Live floating P/L of the hedge, for display only.

The MT5 side is read through the official READ-ONLY MetaTrader5 connection
(positions_get / account_info / symbol_info only - never order_send or any
write). The other side cannot be read reliably, so it is ESTIMATED from the
MT5 side's progress between its SL and TP: both legs move together, so when
the 場外 reaches its TP the 場內 reaches its SL, and vice versa.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from decimal import Decimal

READ_INTERVAL = 0.1  # seconds; the user asked for 0.1 s


@dataclass(frozen=True)
class SideTargets:
    """Money at TP (positive) and SL (negative) for one leg."""
    tp: float
    sl: float


def side_targets(sl_points, tp_points, lot, contract) -> SideTargets:
    """Sheet distances (price units) -> money at TP / SL."""
    size = float(lot) * float(contract)
    return SideTargets(tp=abs(float(tp_points)) * size, sl=-abs(float(sl_points)) * size)


def mt5_targets(position, contract, fallback: SideTargets) -> tuple[SideTargets, float | None, float | None]:
    """Money and prices at the MT5 position's own SL/TP when they are set;
    the sheet's amounts otherwise. Returns (targets, sl_price, tp_price)."""
    sign = 1.0 if int(position.type) == 0 else -1.0  # 0 = buy, 1 = sell
    size = float(position.volume) * float(contract)
    sl_price = float(position.sl) or None
    tp_price = float(position.tp) or None
    tp = (tp_price - float(position.price_open)) * sign * size if tp_price else fallback.tp
    sl = (sl_price - float(position.price_open)) * sign * size if sl_price else fallback.sl
    if tp_price is None and size:
        tp_price = float(position.price_open) + sign * fallback.tp / size
    if sl_price is None and size:
        sl_price = float(position.price_open) + sign * fallback.sl / size
    return SideTargets(tp=tp, sl=sl), sl_price, tp_price


def model(*, mt5_role: str, mt5_pnl: float, mt5: SideTargets, other: SideTargets,
          price: float, mt5_sl_price, mt5_tp_price, entry_price=None) -> dict | None:
    """Bar model, always oriented by 場外: 0 = 場外 SL (left), 1 = 場外 TP (right)."""
    if mt5.tp <= mt5.sl or other.tp <= other.sl:
        return None
    progress = (mt5_pnl - mt5.sl) / (mt5.tp - mt5.sl)  # 0 at MT5 SL, 1 at MT5 TP
    if mt5_role == "external":
        external, internal = mt5, other
        x = progress
        ext_pnl = mt5_pnl
        # 場外 at TP <=> 場內 at SL
        int_pnl = internal.tp + x * (internal.sl - internal.tp)
        ext_prices = (mt5_sl_price, mt5_tp_price)
    else:
        external, internal = other, mt5
        x = 1.0 - progress
        int_pnl = mt5_pnl
        ext_pnl = external.sl + x * (external.tp - external.sl)
        # 場外 TP is where 場內 hits its SL, and the other way round.
        ext_prices = (mt5_tp_price, mt5_sl_price)
    zero = -external.sl / (external.tp - external.sl)
    return {
        "x": max(0.0, min(1.0, x)), "zero": max(0.0, min(1.0, zero)),
        "estimated": "internal" if mt5_role == "external" else "external",
        "external": {"pnl": round(ext_pnl, 2), "tp": round(external.tp, 2), "sl": round(external.sl, 2)},
        "internal": {"pnl": round(int_pnl, 2), "tp": round(internal.tp, 2), "sl": round(internal.sl, 2)},
        "price": price, "entry_price": entry_price,
        "sl_price": ext_prices[0], "tp_price": ext_prices[1],
    }


class LivePnlMonitor:
    """Background read loop. `context()` (GUI-provided, thread-safe snapshot)
    returns None when there is nothing to show, or a dict with mt5_role,
    terminal path, expected account, instruction and a busy flag."""

    def __init__(self, context, publish, log=None, closed=None):
        self.context, self.publish, self.log = context, publish, log or (lambda _t: None)
        self.closed = closed or (lambda _info: None)
        self._stop = threading.Event()
        self._thread = None
        self._targets = {}  # ticket -> other side's targets frozen at first sight
        self._last_ticket = None
        self._last_key = None  # (terminal, account, server) that held _last_ticket
        self._ticket_profile = {}  # ticket -> 方案 open when it was first seen
        self._connected = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="live-pnl", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        from .mt5_native_readonly import MT5_LOCK, _sdk
        try:
            mt = _sdk()
        except Exception:
            return  # no read-only MT5 package: the feature simply stays hidden
        while not self._stop.wait(READ_INTERVAL):
            try:
                ctx = self.context()
            except Exception:
                ctx = None
            if not ctx or ctx.get("busy"):
                if not ctx:
                    self._shown(None)
                continue  # never read while a trade operation runs
            try:
                with MT5_LOCK:
                    result = self._read(mt, ctx)
            except Exception:
                result = None
                self._connected = None
            self._shown(result)
        try:
            with MT5_LOCK:
                mt.shutdown()
        except Exception:
            pass

    def _read(self, mt, ctx):
        path = str(ctx["terminal"])
        if self._connected != path or mt.account_info() is None:
            if not mt.initialize(path=path, timeout=3000):
                self._connected = None
                return None
            self._connected = path
        account = mt.account_info()
        expected = ctx["account"]
        if (account is None or str(account.login) != expected.account_id
                or str(account.server).casefold() != expected.server.casefold()):
            return None
        key = (path, expected.account_id, expected.server.casefold())
        positions = mt.positions_get()
        if positions is None:
            self._connected = None
            return None
        if not positions:
            if self._last_ticket is not None:
                # Only a real close counts: the SAME account that held the
                # ticket, and MT5's own history shows the closing deal.
                # Another 方案 / account simply having no position is not
                # a close (that used to switch 方案 back and re-update).
                if key == self._last_key and self._has_closing_deal(mt, self._last_ticket):
                    self.closed({"ticket": self._last_ticket,
                                 "profile": self._ticket_profile.get(self._last_ticket, "")})
                self._last_ticket = None
                self._last_key = None
            return None
        position = max(positions, key=lambda p: getattr(p, "time_msc", 0))
        info = mt.symbol_info(position.symbol)
        contract = float(getattr(info, "trade_contract_size", 0) or 100)
        item = ctx["instruction"]
        mt5_role = ctx["mt5_role"]
        other_role = "internal" if mt5_role == "external" else "external"
        ticket = int(position.ticket)
        self._ticket_profile.setdefault(ticket, ctx.get("profile", ""))
        if ticket not in self._targets and item is not None:
            mine, theirs = getattr(item, mt5_role), getattr(item, other_role)
            self._targets[ticket] = (
                side_targets(mine.sl_points, mine.tp_points, mine.lot, contract),
                side_targets(theirs.sl_points, theirs.tp_points, theirs.lot, contract))
        if ticket not in self._targets:
            return None
        self._last_ticket = ticket
        self._last_key = key
        sheet_mine, other = self._targets[ticket]
        mine, sl_price, tp_price = mt5_targets(position, contract, sheet_mine)
        return model(mt5_role=mt5_role, mt5_pnl=float(position.profit), mt5=mine, other=other,
                     price=float(position.price_current), mt5_sl_price=sl_price, mt5_tp_price=tp_price,
                     entry_price=float(position.price_open))

    @staticmethod
    def _has_closing_deal(mt, ticket) -> bool:
        """Read-only history check: an exit deal exists for this position."""
        try:
            deals = mt.history_deals_get(position=int(ticket))
        except Exception:
            return False
        return any(int(getattr(deal, "entry", -1)) in (1, 3) for deal in deals or ())  # OUT / OUT_BY

    def _shown(self, value):
        if value == getattr(self, "_last_shown", object()):
            return  # nothing changed: no repaint / phone message
        self._last_shown = value
        try:
            self.publish(value)
        except Exception:
            pass

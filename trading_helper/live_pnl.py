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


def _window_alive(hwnd) -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsWindow(int(hwnd)))
    except Exception:
        return True


SCAN_INTERVAL = 3.0  # seconds between looks at the OTHER 方案's accounts


class LivePnlMonitor:
    """Background read loop over every 方案 that has exactly one MT5 side.

    `context()` (GUI-provided, thread-safe snapshot) returns None, or
    {"busy", "active", "prefer", "profiles": [{"profile", "mt5_role",
    "terminal", "account", "instruction"}]} - instruction only for the active
    方案 (the sheet that is loaded). The shown 方案 is read every 0.1 s; the
    others every few seconds, only to know whether they hold a position.

    Each position's money at TP/SL is remembered from the moment it is first
    seen until it is closed (saved to disk, so a restart keeps it)."""

    def __init__(self, context, publish, log=None, closed=None, store_path=None):
        self.context, self.publish, self.log = context, publish, log or (lambda _t: None)
        self.closed = closed or (lambda _info: None)
        self.store_path = store_path
        self._stop = threading.Event()
        self._thread = None
        self._targets = self._load_targets()   # ticket -> remembered targets
        self._ticket_profile = {t: v.get("profile", "") for t, v in self._targets.items()}
        self._open = {}          # account key -> {ticket: 方案}
        self._has_position = {}  # 方案 -> bool (from the latest read of its account)
        self._last_scan = -1e9
        self._connected = None

    # -- remembered targets ---------------------------------------------------
    def _load_targets(self):
        import json
        try:
            with open(self.store_path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception:
            return {}
        return {int(k): v for k, v in raw.items() if isinstance(v, dict)}

    def _save_targets(self):
        import json
        if not self.store_path:
            return
        try:
            with open(self.store_path, "w", encoding="utf-8") as handle:
                json.dump({str(k): v for k, v in self._targets.items()}, handle, ensure_ascii=False)
        except Exception:
            pass

    # -- loop -----------------------------------------------------------------
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
                    result = self._tick(mt, ctx, time.monotonic())
            except Exception:
                result = None
                self._connected = None
            self._shown(result)
        try:
            with MT5_LOCK:
                mt.shutdown()
        except Exception:
            pass

    def _tick(self, mt, ctx, now):
        entries = [e for e in ctx.get("profiles", ()) if e]
        if not entries:
            return None
        active = ctx.get("active", "")
        if now - self._last_scan >= SCAN_INTERVAL:
            self._last_scan = now
            # Active first: a ticket seen there belongs to the active 方案.
            for entry in sorted(entries, key=lambda e: e["profile"] != active):
                self._read_account(mt, entry)
        choices = [e["profile"] for e in entries if self._has_position.get(e["profile"])]
        prefer = ctx.get("prefer")
        shown = (prefer if prefer in choices else active if active in choices
                 else choices[0] if choices else active)
        entry = next((e for e in entries if e["profile"] == shown), None)
        state = self._state(mt, entry) if entry is not None and shown in choices else None
        return {"profile": shown, "choices": choices, "state": state}

    def _connect(self, mt, entry):
        path = str(entry["terminal"])
        hwnd = entry.get("hwnd")
        if hwnd and not _window_alive(hwnd):
            return None  # terminal closed: never let initialize() start it again
        if self._connected != path or mt.account_info() is None:
            if not mt.initialize(path=path, timeout=3000):
                self._connected = None
                return None
            self._connected = path
        account = mt.account_info()
        expected = entry["account"]
        if (account is None or str(account.login) != expected.account_id
                or str(account.server).casefold() != expected.server.casefold()):
            return None
        return (path, expected.account_id, expected.server.casefold())

    def _read_account(self, mt, entry):
        """This 方案's positions in its account; notices closes. None = unknown."""
        key = self._connect(mt, entry)
        if key is None:
            return None
        positions = mt.positions_get()
        if positions is None:
            self._connected = None
            return None
        before = self._open.get(key, {})
        now_open = {}
        for position in positions:
            ticket = int(position.ticket)
            self._ticket_profile.setdefault(ticket, before.get(ticket) or entry["profile"])
            now_open[ticket] = self._ticket_profile[ticket]
        for ticket, profile in before.items():
            if ticket not in now_open:
                # Only a real close counts: same account, and MT5's own
                # history shows the closing deal.
                if self._has_closing_deal(mt, ticket):
                    self.closed({"ticket": ticket, "profile": profile,
                                 "outcome": self._close_outcome(mt, ticket, entry.get("mt5_role"))})
                if self._targets.pop(ticket, None) is not None:
                    self._save_targets()
        if key not in self._open:
            # First look at this account since start-up: amounts remembered
            # for this 方案's positions that were closed while the helper was
            # not running are dropped (no update is triggered for them).
            stale = [t for t, v in self._targets.items()
                     if v.get("profile") == entry["profile"] and t not in now_open]
            for ticket in stale:
                self._targets.pop(ticket, None)
            if stale:
                self._save_targets()
        self._open[key] = now_open
        for name in {entry["profile"], *before.values(), *now_open.values()}:
            self._has_position[name] = any(
                p == name for tickets in self._open.values() for p in tickets.values())
        return [p for p in positions if self._ticket_profile.get(int(p.ticket)) == entry["profile"]]

    def _state(self, mt, entry):
        positions = self._read_account(mt, entry)
        if not positions:
            return None
        position = max(positions, key=lambda p: getattr(p, "time_msc", 0))
        info = mt.symbol_info(position.symbol)
        contract = float(getattr(info, "trade_contract_size", 0) or 100)
        ticket = int(position.ticket)
        mt5_role = entry["mt5_role"]
        if ticket not in self._targets and entry.get("instruction") is not None:
            item = entry["instruction"]
            other_role = "internal" if mt5_role == "external" else "external"
            mine, theirs = getattr(item, mt5_role), getattr(item, other_role)
            a = side_targets(mine.sl_points, mine.tp_points, mine.lot, contract)
            b = side_targets(theirs.sl_points, theirs.tp_points, theirs.lot, contract)
            self._targets[ticket] = {"profile": entry["profile"], "mt5_role": mt5_role,
                                     "mine": [a.tp, a.sl], "other": [b.tp, b.sl]}
            self._save_targets()
        saved = self._targets.get(ticket)
        if saved is None:
            return None  # an older position of another 方案: amounts unknown
        sheet_mine = SideTargets(*saved["mine"])
        other = SideTargets(*saved["other"])
        mine, sl_price, tp_price = mt5_targets(position, contract, sheet_mine)
        return model(mt5_role=saved.get("mt5_role", mt5_role), mt5_pnl=float(position.profit),
                     mt5=mine, other=other, price=float(position.price_current),
                     mt5_sl_price=sl_price, mt5_tp_price=tp_price,
                     entry_price=float(position.price_open))

    @staticmethod
    def _has_closing_deal(mt, ticket) -> bool:
        """Read-only history check: an exit deal exists for this position."""
        try:
            deals = mt.history_deals_get(position=int(ticket))
        except Exception:
            return False
        return any(int(getattr(deal, "entry", -1)) in (1, 3) for deal in deals or ())  # OUT / OUT_BY

    @staticmethod
    def _close_outcome(mt, ticket, mt5_role):
        """Read-only: "tp" when the 場外 side hit its TP, "sl" when it hit
        its SL, None when unknown. MT5 holds one side; the other is opposite."""
        try:
            deals = mt.history_deals_get(position=int(ticket)) or ()
            reasons = {int(getattr(d, "reason", -1)) for d in deals
                       if int(getattr(d, "entry", -1)) in (1, 3)}
        except Exception:
            return None
        # MT5 DEAL_REASON_SL = 4, DEAL_REASON_TP = 5; anything else (manual,
        # stop-out, ...) is not a TP/SL close.
        mine = "tp" if 5 in reasons else "sl" if 4 in reasons else None
        if mine is None or mt5_role not in ("external", "internal"):
            return None
        return mine if mt5_role == "external" else ("sl" if mine == "tp" else "tp")

    def _shown(self, value):
        if value == getattr(self, "_last_shown", object()):
            return  # nothing changed: no repaint / phone message
        self._last_shown = value
        try:
            self.publish(value)
        except Exception:
            pass

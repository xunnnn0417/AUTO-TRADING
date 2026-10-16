"""Guarded post-fill trade automation, testable without a broker.

Execution uses a strict BrokerExecutionPort. All transactions require verified
DEMO accounts and uniquely identified positions. No click or retry on
uncertain state. The default Windows UI adapter refuses submission until
the real GUI readback contract has been proven for BOTH brokers.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol, Callable
import hashlib
import json
import os
import threading
import time

from .windows import AutomationError
from .recovery_policy import validate_terminal_rejection


@dataclass(frozen=True)
class DemoAccount:
    platform: str
    account_id: str
    server: str
    is_demo: bool
    verified: bool


@dataclass(frozen=True)
class Position:
    ticket: str
    account_id: str
    platform: str
    symbol: str
    direction: str
    volume: Decimal
    entry_price: Decimal
    sl: Decimal | None = None
    tp: Decimal | None = None


class BrokerExecutionPort(Protocol):
    def inspect_account(self, platform: str, role: str) -> DemoAccount: ...
    def snapshot_positions(self, platform: str, role: str) -> tuple[Position, ...]: ...
    def verify_order_form(self, platform: str, role: str, direction: str,
                          lot: Decimal) -> None: ...
    def submit_once(self, platform: str, role: str, direction: str,
                    lot: Decimal, key: str) -> None: ...
    def confirm_new_position(self, platform: str, role: str,
                             baseline: tuple[Position, ...],
                             direction: str, volume: Decimal,
                             account_id: str) -> Position: ...
    def verify_internal_protection(self, pos: Position,
                                    sl_points: Decimal,
                                    tp_points: Decimal) -> None: ...
    def set_position_sl_tp(self, pos: Position, sl: Decimal, tp: Decimal) -> None: ...
    def verify_position_sl_tp(self, pos: Position, sl: Decimal,
                               tp: Decimal) -> None: ...
    def draw_tradingview(self, instruction, internal_platform: str,
                         entry: Decimal, draw_internal: bool) -> None: ...
    def prove_terminal_rejection(self, platform: str, role: str,
                                 attempt_key: str, account_id: str,
                                 symbol: str): ...


class RecoveryRequired(AutomationError):
    """A trade might have been submitted; user must reconcile manually."""


class DuplicateEntryDecisionRequired(RecoveryRequired):
    """Request explicit consent for a known earlier attempt; no broker click."""

    def __init__(self, key: str, entry: dict, retryable: bool):
        self.key = key
        self.entry = dict(entry)
        self.retryable = retryable
        self.manual_review_possible = AutoEntryWorkflow.manual_review_possible(entry)
        self.request = None
        super().__init__("此方案已有進場紀錄，為防止重複下單，等待使用者選擇。")


class AutoEntryJournal:
    """Durable acknowledgement barrier against accidental repeated entries."""
    def __init__(self, path: Path):
        self.path=path
        self._lock=threading.Lock()
    def _all(self) -> dict:
        try:
            data=json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise RecoveryRequired(f"自動進場紀錄無法讀取，已禁止再送單：{exc}") from exc
    def entry(self, key: str) -> dict | None:
        with self._lock:
            item = self._all().get(key)
            return dict(item) if isinstance(item, dict) else None

    def status(self, key: str) -> str | None:
        entry = self.entry(key)
        return entry.get("status") if entry else None

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),
                       encoding="utf-8")
        os.replace(tmp,self.path)

    def prepare_confirmed_retry(
        self, key: str, previous: dict, *, manually_reconciled: bool=False
    ) -> None:
        """Atomically archive one known attempt; never erase trade history."""
        with self._lock:
            data=self._all()
            old=data.get(key)
            if not isinstance(old,dict) or old!=previous:
                raise RecoveryRequired(
                    "確認後進場紀錄已改變，為避免重複下單已取消。"
                )
            history=list(old.get("history", []))
            historical={k:v for k,v in old.items() if k!="history"}
            history.append(historical)
            data[key]={
                "status":"retry_authorized",
                "details":"使用者明確同意重新檢查及進場",
                "time":time.strftime("%Y-%m-%d %H:%M:%S"),
                "history":history,
                "manual_reconciliation_confirmed":manually_reconciled,
            }
            self._write(data)

    def reserve_verified_rescue(self, key: str, role: str, order_id: str) -> None:
        """Durably consume the sole retry permit BEFORE any new broker click."""
        if role not in ("internal","external") or not order_id:
            raise RecoveryRequired("補單場別或原始訂單編號不明。")
        with self._lock:
            data=self._all()
            current=data.get(key)
            if not isinstance(current,dict):
                raise RecoveryRequired("不存在首次送單紀錄，拒絕補單。")
            if current.get("rescue_attempted") or current.get("rescued_role"):
                raise RecoveryRequired("此交易已啟動過補單，禁止再次補單。")
            current["rescue_attempted"]=True
            current["rescue_role"]=role
            current["rescue_rejected_order_id"]=order_id
            current["status"]="rescue_reserved"
            current["time"]=time.strftime("%Y-%m-%d %H:%M:%S")
            data[key]=current
            self._write(data)

    def record_verified_leg(self, key: str, role: str, pos: Position) -> None:
        """Persist independent confirmed tickets before inspecting the other side."""
        if role not in ("internal","external"):
            raise RecoveryRequired("未知的雙邊成交記錄場別。")
        with self._lock:
            data=self._all()
            entry=data.get(key)
            if not isinstance(entry,dict):
                raise RecoveryRequired("尚無交易紀錄，不可記錄成交。")
            confirmed=dict(entry.get("confirmed_legs",{}))
            if role in confirmed and confirmed[role]!=pos.ticket:
                raise RecoveryRequired("同一邊出現不同的成交編號，不可補單。")
            confirmed[role]=pos.ticket
            entry["confirmed_legs"]=confirmed
            entry["status"]=f"confirmed_{role}"
            entry["time"]=time.strftime("%Y-%m-%d %H:%M:%S")
            data[key]=entry
            self._write(data)

    def record(self, key: str, status: str, details: str = "") -> None:
        with self._lock:
            data=self._all()
            old=data.get(key)
            entry=dict(old) if isinstance(old,dict) else {}
            entry.update({
                "status":status, "details":details,
                "time":time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            if status in ("filled_internal", "filled_external"):
                # Sequential entry uses the same durable per-leg receipt
                # as fast pair. This is recorded after unique fill readback,
                # using the existing atomic journal write (no added wait).
                role=status.removeprefix("filled_")
                ticket = details.removeprefix("ticket=").strip()
                if not details.startswith("ticket=") or not ticket:
                    raise RecoveryRequired("成交編號無效，拒絕記錄為已成交。")
                confirmed=dict(entry.get("confirmed_legs",{}))
                if role in confirmed and confirmed[role]!=ticket:
                    raise RecoveryRequired("同一場別出現不同成交編號。")
                confirmed[role]=ticket
                entry["confirmed_legs"]=confirmed
            if status=="both_confirmed":
                entry["confirmed_both"]=details
            if status=="rescue_confirmed":
                if details not in ("internal","external"):
                    raise RecoveryRequired("補單成功場別無效。")
                entry["rescued_role"]=details
            if status=="internal_protected":
                entry["internal_protected"]=True
            if status=="synchronized":
                # Only recorded AFTER modifying and reading back the SL/TP.
                entry["sl_tp_synchronized"]=True
            data[key]=entry
            self._write(data)


class AutoEntryWorkflow:
    def __init__(self, port: BrokerExecutionPort, journal: AutoEntryJournal,
                 guard: Callable[[], None], log: Callable[[str], None]):
        self.port=port
        self.journal=journal
        self.guard=guard
        self.log=log

    def _rescue_only_proven_rejection(
        self, *, key: str, platform: str, role: str, direction: str,
        lot: Decimal, account: DemoAccount, baseline: tuple[Position,...],
        verified_other: Position, other_platform: str, other_role: str,
        other_account: DemoAccount, other_direction: str, other_lot: Decimal,
        instruction,
    ) -> Position | None:
        """Once-only rescue, ONLY with a broker's final rejection proof.

        The existing Windows UI broker adapter cannot produce this proof.
        All unknown/timeouts remain fail-closed. No place-order click without
        identity, other-leg and zero-pending/fill checks.
        """
        certify=getattr(self.port,"prove_terminal_rejection",None)
        if not callable(certify):
            return None
        self.guard()
        proof=validate_terminal_rejection(
            certify(platform,role,key,account.account_id,instruction.symbol),
            attempt_key=key,platform=platform,role=role,
            account_id=account.account_id,symbol=instruction.symbol,
        )
        if proof is None:
            return None
        # Reject stale account changes, other-leg movement or ambiguous
        # missing-leg positions even if the broker proof was genuine.
        for plat,side,expected_account in (
            (platform,role,account),
            (other_platform,other_role,other_account),
        ):
            fresh=self.port.inspect_account(plat,side)
            if fresh!=expected_account or not fresh.verified or not fresh.is_demo:
                raise RecoveryRequired("補單前 Demo 帳戶身分已變動，禁止再送單。")
        current_other=self.port.snapshot_positions(other_platform,other_role)
        matches=[p for p in current_other if p.ticket==verified_other.ticket]
        if len(current_other)!=1 or len(matches)!=1:
            raise RecoveryRequired("補單前另一邊已成交持倉不再唯一，停止。")
        self._validate_position(
            matches[0],other_platform,other_direction,
            other_lot,other_account,instruction.symbol
        )
        current_missing=self.port.snapshot_positions(platform,role)
        if current_missing!=baseline or current_missing:
            raise RecoveryRequired("拒單側持倉已變動或非空，禁止補單。")
        self.port.verify_order_form(platform,role,direction,lot)
        # Reservation is the crash-safe barrier. A restart cannot resend.
        self.journal.reserve_verified_rescue(
            key,role,proof.original_broker_order_id
        )
        self.log(f"{role} 有最終拒單證明，僅嘗試補開一次。")
        pos=self._submit_and_confirm(
            platform,role,direction,lot,account,baseline,
            instruction.symbol,key
        )
        self.journal.record_verified_leg(key,role,pos)
        self.journal.record(key,"rescue_confirmed",role)
        self.log(f"{role} 補單已唯一成交確認：{pos.ticket}")
        return pos

    @staticmethod
    def fingerprint(profile: str, sheet_url: str, accounts: tuple[DemoAccount,...],
                    instruction) -> str:
        parts={
            "profile":profile,
            "sheet":sheet_url.strip(),
            "accounts":[(a.platform,a.account_id,a.server) for a in accounts],
            "symbol":instruction.symbol,
            "direction":instruction.internal_direction,
            "internal":list(map(str,(
                instruction.internal.lot,
                instruction.internal.sl_points,
                instruction.internal.tp_points))),
            "external":list(map(str,(
                instruction.external.lot,
                instruction.external.sl_points,
                instruction.external.tp_points))),
            "sheet_row":instruction.source_row,
        }
        return hashlib.sha256(
            json.dumps(parts,sort_keys=True,ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_position(pos: Position, platform: str, direction: str,
                           volume: Decimal, account: DemoAccount,
                           symbol: str) -> None:
        if not pos.ticket or pos.ticket in {"0","-"}:
            raise RecoveryRequired("找不到可靠的成交持倉識別碼。")
        def canonical_symbol(raw: str) -> str:
            s=str(raw).strip().upper()
            # Explicit XAUUSD/GOLD alias; retain other symbols exactly.
            if s=="GOLD" or s=="XAUUSD" or (
                s.startswith("XAUUSD") and s[6:7] in (".","+","-")
            ):
                return "XAUUSD"
            return s
        if (pos.platform != platform or pos.account_id != account.account_id
            or pos.direction != direction
            or canonical_symbol(pos.symbol)!=canonical_symbol(symbol)
            or pos.volume != volume or not pos.entry_price.is_finite()
            or pos.entry_price <= 0):
            raise RecoveryRequired(
                "成交持倉的帳戶、商品、方向、手數或成交價不一致，"
                "已停止；請手動確認持倉。"
            )

    @staticmethod
    def retryable_duplicate(entry: dict) -> bool:
        status=str(entry.get("status",""))
        if status in {
            "complete", "synchronized", "prepared",
            "retry_authorized", "pre_submit_aborted",
        }:
            return True
        if status=="attention_required":
            # Existing historical data lacks a structured pre-click marker.
            # Only the exact known UIA safety failures are provably pre-click.
            safe_preclick=frozenset({
                "cTrader 校準位置不在送單鍵內。",
                "cTrader 找不到唯一 Place order 按鈕。",
                "cTrader 尚未人工校準真正的 Place order。",
            })
            return str(entry.get("details","")) in safe_preclick
        return False

    @staticmethod
    def manual_review_possible(entry: dict) -> bool:
        """Unknown after-send outcomes require BOTH brokers' manual histories."""
        return str(entry.get("status","")) in {
            "attention_required", "sending_internal", "sending_external",
            "filled_internal", "internal_protected", "filled_external",
            "retry_authorized", "confirmed_internal","confirmed_external",
            "both_confirmed",
        }

    def _visual_second_chance(
        self, platform: str, role: str, baseline: tuple[Position, ...],
        direction: str, volume: Decimal, account: DemoAccount,
        symbol: str, key: str,
    ) -> Position | None:
        """Two READ-ONLY checks after an ambiguous confirm; never resend.

        A position may become visible slightly after the original 12-second
        observation window or after a transient UIA read failure. A unique,
        correct *new* position is positive evidence. An empty or unreadable
        grid is UNKNOWN, never a terminal rejection. No broker order clicks.
        """
        previous = {p.ticket for p in baseline}
        for attempt in range(2):
            self.guard()
            try:
                observed = self.port.snapshot_positions(platform, role)
            except AutomationError as exc:
                # The adapter failed to read an authoritative current
                # snapshot. Allow another read; never treat this as empty.
                self.log(f"{role} {platform} 持倉補讀未成功：{exc}")
            else:
                newly_seen = [p for p in observed if p.ticket not in previous]
                if len(newly_seen) == 1 and len(observed) == len(baseline) + 1:
                    position = newly_seen[0]
                    self._validate_position(
                        position, platform, direction, volume, account, symbol
                    )
                    remember=getattr(
                        self.port,"remember_verified_position_role",None
                    )
                    if callable(remember):
                        remember(platform,role,position)
                    self.journal.record_verified_leg(key, role, position)
                    self.log(
                        f"{role} {platform} 補讀辨識到原本已成交持倉："
                        f"{position.ticket}；沒有重新送單。"
                    )
                    return position
                if newly_seen or len(observed) != len(baseline) or (
                    {p.ticket for p in observed} != previous
                ):
                    raise RecoveryRequired(
                        f"{role} {platform} 補讀發現不唯一／不符合基準的"
                        "持倉變化，不能推定未成交或自動補單。"
                    )
            if attempt == 0:
                time.sleep(0.15)
        return None

    def _submit_and_confirm(self, platform: str, role: str, direction: str,
                            volume: Decimal, account: DemoAccount,
                            before: tuple[Position,...], symbol: str,
                            key: str) -> Position:
        self.guard()
        self.port.verify_order_form(platform,role,direction,volume)
        # Mark MAY_HAVE_SENT *before* any click: if the process dies, a
        # later invocation must not blindly send the same trade again.
        self.journal.record(key,f"sending_{role}","尚未確認是否有成交")
        self.port.submit_once(platform,role,direction,volume,key)
        # No retries on Send. Even a timeout may mean a successful fill.
        pos=self.port.confirm_new_position(
            platform,role,before,direction,volume,account.account_id
        )
        self._validate_position(pos,platform,direction,volume,account,symbol)
        self.journal.record(key,f"filled_{role}",f"ticket={pos.ticket}")
        self.log(f"{role} {platform} Demo 成交已確認：{pos.ticket}")
        return pos

    def run(self, instruction, internal_platform: str, external_platform: str,
            profile: str, sheet_url: str, *,
            sync_sl_tp: bool, draw_tv: bool,
            draw_internal: bool=False,
            duplicate_confirmation: tuple[str,str,str,str] | None = None,
            manual_reconciliation_confirmed: bool = False,
            fast_pair: bool = False,
            ) -> tuple[Position,Position]:
        self.last_key = None
        self.journal_current_attempt = False
        precheck_started=time.perf_counter()
        self.guard()
        if hasattr(self.port, "set_expected_symbol"):
            self.port.set_expected_symbol(instruction.symbol)
        if draw_tv and not sync_sl_tp:
            raise AutomationError("自動繪製 TV 必須先啟用並完成 SL/TP 同步。")
        if fast_pair and (internal_platform, external_platform) not in {
            ("cTrader", "MT5"), ("MT5", "cTrader"),
        }:
            raise AutomationError(
                "快速雙邊目前只支援 cTrader + MT5 的雙 Demo 配置"
                "（兩者場內／場外可互換）；本次未送單。"
            )
        # The fill workflow leaves MT5/external on top. Verify its identity
        # first, then switch to internal; never guess stale HWND coordinates.
        account_e=self.port.inspect_account(external_platform,"external")
        account_i=self.port.inspect_account(internal_platform,"internal")
        for account,platform in ((account_i,internal_platform),
                                 (account_e,external_platform)):
            if (not account.verified or not account.is_demo
                or not account.account_id or not account.server
                or account.platform!=platform):
                raise AutomationError(
                    f"{platform} 未證實為已登入的 Demo 帳戶，拒絕自動送單。"
                )
        if (account_i.platform,account_i.account_id,account_i.server)==(
            account_e.platform,account_e.account_id,account_e.server):
            raise AutomationError("場內與場外不可使用同一交易帳戶。")
        key=self.fingerprint(profile,sheet_url,(account_i,account_e),instruction)
        # Diagnostic only: the receipt can report the associated journal
        # without any broker access or change to order execution.
        self.last_key=key
        existing=self.journal.entry(key)
        if existing:
            status=str(existing.get("status",""))
            stamp=str(existing.get("time",""))
            details=str(existing.get("details",""))
            expected=(key,status,stamp,details)
            retryable=self.retryable_duplicate(existing)
            manual_possible=self.manual_review_possible(existing)
            if (duplicate_confirmation!=expected or
                (not retryable and not
                 (manual_possible and manual_reconciliation_confirmed))):
                raise DuplicateEntryDecisionRequired(key, existing, retryable)
        elif duplicate_confirmation is not None:
            raise RecoveryRequired(
                "原本的重複進場紀錄已改變，請重新確認，不會送單。"
            )
        before_e=self.port.snapshot_positions(external_platform,"external")
        before_i=self.port.snapshot_positions(internal_platform,"internal")
        # A previously interrupted attempt may already have filled BOTH
        # accounts. After explicit manual history review, permit a strict
        # NO-SUBMIT reconciliation of the two *existing* unique positions.
        # A missing/ambiguous side must never turn into a guess-and-resend.
        if before_i or before_e:
            if (not existing or not manual_reconciliation_confirmed
                or duplicate_confirmation is None):
                raise AutomationError(
                    "Demo 已存在持倉。請先核對兩個帳戶的交易歷史，"
                    "使用舊交易紀錄的明確確認流程；不會新增訂單。"
                )
            if len(before_i)!=1 or len(before_e)!=1:
                raise RecoveryRequired(
                    "目前 Demo 已存在持倉，但雙邊未找到各一筆唯一對應持倉，"
                    "不能將缺少的交易視為拒單，也不會自動補單。"
                )
            first,second=before_i[0],before_e[0]
            self._validate_position(
                first,internal_platform,instruction.internal_direction,
                instruction.internal.lot,account_i,instruction.symbol,
            )
            self._validate_position(
                second,external_platform,instruction.external_direction,
                instruction.external.lot,account_e,instruction.symbol,
            )
            self.port.verify_internal_protection(
                first,instruction.internal.sl_points,instruction.internal.tp_points
            )
            # Require proper SL/TP on the second live position too; do not
            # mark a dual hedge complete with one completely unprotected leg.
            if (second.sl is None or second.tp is None or
                second.sl<=0 or second.tp<=0 or
                (second.direction=="BUY" and not
                 (second.sl<second.entry_price<second.tp)) or
                (second.direction=="SELL" and not
                 (second.tp<second.entry_price<second.sl))):
                raise RecoveryRequired(
                    "另一邊既有持倉的 SL/TP 尚未證實有效，拒絕當成完整對沖。"
                )
            self.journal.prepare_confirmed_retry(
                key,existing,manually_reconciled=True
            )
            self.journal_current_attempt = True
            self.journal.record_verified_leg(key,"internal",first)
            self.journal.record_verified_leg(key,"external",second)
            self.journal.record(key,"internal_protected",first.ticket)
            self.journal.record(
                key,"both_confirmed",first.ticket+"/"+second.ticket
            )
            try:
                if sync_sl_tp:
                    sl,tp=instruction.estimated_prices(
                        instruction.external_direction,
                        instruction.external,first.entry_price
                    )
                    self.port.set_position_sl_tp(second,sl,tp)
                    self.port.verify_position_sl_tp(second,sl,tp)
                    self.journal.record(
                        key,"synchronized",first.ticket+"/"+second.ticket
                    )
                if draw_tv:
                    self.port.draw_tradingview(
                        instruction,internal_platform,
                        first.entry_price,draw_internal
                    )
                self.journal.record(
                    key,"complete",first.ticket+"/"+second.ticket
                )
                self.log(
                    "原有兩筆 Demo 持倉已核對完成；未再送單，"
                    "僅執行明確勾選的後續工作。"
                )
                return first,second
            except Exception as exc:
                self.journal.record(key,"attention_required",str(exc))
                raise RecoveryRequired(
                    "已核對到既有雙邊持倉，但後續同步未完成。"
                    "未追加任何新訂單，請人工確認：" + str(exc)
                ) from exc
        # Check every stage-specific calibration and downstream dependency
        # BEFORE any order can be sent (otherwise a late failure can leave
        # one side open even though the missing setting was knowable).
        validate=getattr(self.port,"validate_auto_entry_capabilities",None)
        if validate is not None:
            validate(
                internal_platform,external_platform,
                instruction.internal_direction,instruction.external_direction,
                sync_sl_tp=sync_sl_tp,draw_tv=draw_tv,
            )
        # After the external-side fill is complete, inspect its form
        # first, then the internal side. Both checks remain mandatory.
        self.port.verify_order_form(
            external_platform,"external",
            instruction.external_direction,instruction.external.lot)
        self.port.verify_order_form(
            internal_platform,"internal",
            instruction.internal_direction,instruction.internal.lot)
        if existing is not None:
            # User approval alone is never sufficient: DEMO identity,
            # zero current positions, all calibrations, both form readbacks
            # have already been revalidated above.
            self.journal.prepare_confirmed_retry(
                key, existing,
                manually_reconciled=(
                    manual_reconciliation_confirmed and not
                    self.retryable_duplicate(existing)
                ),
            )
        self.journal.record(key,"prepared","兩側預檢完成")
        self.journal_current_attempt = True
        precheck_finished=time.perf_counter()
        self.log(
            "自動進場預檢完成："
            f"{(precheck_finished-precheck_started)*1000:.0f}ms，"
            "已準備送單。兩側表單在送單前仍會再次唯讀核對。"
        )
        try:
            if fast_pair:
                # Explicitly opted-in Demo-only rapid hedge: BOTH dialogs
                # are checked before the first click.  Submission itself
                # is still reverified once by submit_once, exactly one click.
                # We do NOT wait for first-side position polling to finish
                # before dispatching the other side. If either submit raises,
                # we stop, never click again or attempt a rescue order.
                # These are workflow dispatch timestamps, NOT the broker's
                # real fill times or exact OS mouse-down timestamps.
                dispatch_start = {}
                for plat,role,direction,lot in (
                    (internal_platform,"internal",
                     instruction.internal_direction,instruction.internal.lot),
                    (external_platform,"external",
                     instruction.external_direction,instruction.external.lot),
                ):
                    self.guard()
                    # Both forms were checked BEFORE the first click.
                    # The real DemoUiBrokerPort.submit_once does another
                    # fresh per-click form readback itself. A third scan
                    # here only delayed the next click without adding an
                    # independent safety property.
                    self.journal.record(
                        key,f"sending_{role}",
                        "快速雙邊送出中，成交狀態仍未知"
                    )
                    dispatch_start[role]=time.perf_counter()
                    self.port.submit_once(plat,role,direction,lot,key)
                if len(dispatch_start)==2:
                    gap_ms=(
                        dispatch_start["external"]-
                        dispatch_start["internal"]
                    )*1000
                    self.log(
                        f"快速雙邊：兩側送單呼叫開始間隔 {gap_ms:.0f} ms；"
                        "非實際成交價差或券商成交延遲。"
                    )
                    readings=getattr(self.port,"submit_phase_timings",None)
                    if isinstance(readings,dict) and all(
                        role in readings and
                        {"start","form_verified","click_started","click_returned"}
                          <=set(readings[role])
                        for role in ("internal","external")
                    ):
                        in_t=readings["internal"]
                        ex_t=readings["external"]
                        click_gap_ms=(
                            ex_t["click_started"]-in_t["click_started"]
                        )*1000
                        self.log(
                            "快速雙邊診斷：兩次實際點擊函式"
                            f"開始間隔 {click_gap_ms:.0f}ms；"
                            "場內送單前表單核對 "
                            f"{(in_t['form_verified']-in_t['start'])*1000:.0f}ms，"
                            "場外送單前表單核對 "
                            f"{(ex_t['form_verified']-ex_t['start'])*1000:.0f}ms，"
                            "首筆點擊至返回 "
                            f"{(in_t['click_returned']-in_t['click_started'])*1000:.0f}ms，"
                            "場外 UIA 按鈕定位 "
                            f"{(ex_t['click_started']-ex_t['form_verified'])*1000:.0f}ms。"
                            "時間是 Python 視窗點擊函式，"
                            "不是券商真實成交回報。"
                        )
                # Check BOTH sides independently. A failed cTrader read
                # must not suppress our MT5 read-only native inspection.
                # A confirmed ticket is persisted before checking the other
                # side; UNKNOWN is never mistaken for a rejected order.
                verified={}
                uncertainty={}
                for plat,role,direction,lot,baseline,account in (
                    (internal_platform,"internal",
                     instruction.internal_direction,instruction.internal.lot,
                     before_i,account_i),
                    (external_platform,"external",
                     instruction.external_direction,instruction.external.lot,
                     before_e,account_e),
                ):
                    self.guard()
                    try:
                        pos=self.port.confirm_new_position(
                            plat,role,baseline,direction,lot,account.account_id
                        )
                        self._validate_position(
                            pos,plat,direction,lot,account,instruction.symbol,
                        )
                        self.journal.record_verified_leg(key,role,pos)
                        verified[role]=pos
                    except Exception as exc:
                        uncertainty[role]=str(exc)
                # First prefer a fresh visual/native position readback:
                # delayed display is not a failed order and needs no rescue.
                for plat,role,direction,lot,baseline,account in (
                    (internal_platform,"internal",
                     instruction.internal_direction,instruction.internal.lot,
                     before_i,account_i),
                    (external_platform,"external",
                     instruction.external_direction,instruction.external.lot,
                     before_e,account_e),
                ):
                    if role in uncertainty:
                        recovered=self._visual_second_chance(
                            plat,role,baseline,direction,lot,account,
                            instruction.symbol,key
                        )
                        if recovered is not None:
                            verified[role]=recovered
                            uncertainty.pop(role)
                if len(uncertainty)==1 and len(verified)==1:
                    missing_role=next(iter(uncertainty))
                    remaining={
                        "internal":(internal_platform,
                                    instruction.internal_direction,
                                    instruction.internal.lot,before_i,account_i,
                                    external_platform,"external",account_e,
                                    instruction.external_direction,
                                    instruction.external.lot),
                        "external":(external_platform,
                                    instruction.external_direction,
                                    instruction.external.lot,before_e,account_e,
                                    internal_platform,"internal",account_i,
                                    instruction.internal_direction,
                                    instruction.internal.lot),
                    }
                    (plat,direction,lot,baseline,account,op,other_role,
                     other_account,other_dir,other_lot)=remaining[missing_role]
                    rescued=self._rescue_only_proven_rejection(
                        key=key,platform=plat,role=missing_role,
                        direction=direction,lot=lot,account=account,
                        baseline=baseline,verified_other=verified[other_role],
                        other_platform=op,other_role=other_role,
                        other_account=other_account,other_direction=other_dir,
                        other_lot=other_lot,instruction=instruction,
                    )
                    if rescued is not None:
                        verified[missing_role]=rescued
                        uncertainty.pop(missing_role)
                if uncertainty:
                    states=[
                        f"{role}: "+("已確認成交" if role in verified
                                     else "尚未確認成交，不能推定拒單")
                        for role in ("internal","external")
                    ]
                    raise RecoveryRequired(
                        "；".join(states)+"。"
                        "已保存可確認的持倉編號；"
                        "無法證明未成交前禁止自動補單。"
                    )
                first=verified["internal"]
                second=verified["external"]
                self.journal.record(
                    key,"both_confirmed",first.ticket+"/"+second.ticket
                )
                # When MT5 is internal, the preliminary on-form SL/TP
                # was based on a reference quote. In rapid mode BOTH
                # clicks have already been sent, so we must amend MT5
                # using its real executed entry before declaring it safe
                # or synchronizing the external cTrader position.
                if "MT5" in internal_platform.upper():
                    sl_i,tp_i=instruction.estimated_prices(
                        instruction.internal_direction,
                        instruction.internal,first.entry_price
                    )
                    self.port.set_position_sl_tp(first,sl_i,tp_i)
                    self.port.verify_position_sl_tp(first,sl_i,tp_i)
                self.port.verify_internal_protection(
                    first,instruction.internal.sl_points,instruction.internal.tp_points
                )
                self.journal.record(key,"internal_protected",first.ticket)
            else:
                first=self._submit_and_confirm(
                    internal_platform,"internal",instruction.internal_direction,
                    instruction.internal.lot,account_i,before_i,instruction.symbol,key)
            self.guard()
            # MT5 pre-submit SL/TP are based on a *reference quote*. Amend
            # the actual position using its executed price before other side.
            if not fast_pair:
                if "MT5" in internal_platform.upper():
                    sl,tp=instruction.estimated_prices(
                        instruction.internal_direction,
                        instruction.internal,first.entry_price
                    )
                    self.port.set_position_sl_tp(first,sl,tp)
                    self.port.verify_position_sl_tp(first,sl,tp)
                else:
                    self.port.verify_internal_protection(
                        first,instruction.internal.sl_points,
                        instruction.internal.tp_points
                    )
                self.journal.record(key,"internal_protected",first.ticket)
                try:
                    second=self._submit_and_confirm(
                        external_platform,"external",instruction.external_direction,
                        instruction.external.lot,account_e,before_e,instruction.symbol,key)
                except Exception:
                    # Recheck the existing Positions tab first: a delayed
                    # fill is success, not proof that we should click twice.
                    second=self._visual_second_chance(
                        external_platform,"external",before_e,
                        instruction.external_direction,
                        instruction.external.lot,account_e,
                        instruction.symbol,key
                    )
                    if second is None:
                        second=self._rescue_only_proven_rejection(
                        key=key,platform=external_platform,role="external",
                        direction=instruction.external_direction,
                        lot=instruction.external.lot,account=account_e,
                        baseline=before_e,verified_other=first,
                        other_platform=internal_platform,other_role="internal",
                        other_account=account_i,
                        other_direction=instruction.internal_direction,
                            other_lot=instruction.internal.lot,
                            instruction=instruction,
                        )
                    if second is None:
                        raise
                self.guard()
                # A genuine both-entered milestone requires two independently
                # confirmed tickets, not only two dispatched mouse clicks.
                self.journal.record(
                    key,"both_confirmed",first.ticket+"/"+second.ticket
                )
            if sync_sl_tp:
                sl,tp=instruction.estimated_prices(
                    instruction.external_direction,
                    instruction.external,first.entry_price
                )
                self.port.set_position_sl_tp(second,sl,tp)
                self.port.verify_position_sl_tp(second,sl,tp)
                self.journal.record(key,"synchronized",
                                    first.ticket+"/"+second.ticket)
            if draw_tv:
                self.port.draw_tradingview(
                    instruction,internal_platform,first.entry_price,draw_internal
                )
            self.journal.record(key,"complete",first.ticket+"/"+second.ticket)
            self.log("雙 Demo 自動進場、成交核對及已啟用的後續步驟完成。")
            return first,second
        except Exception as exc:
            # Persist uncertainty, do not auto-close, retry a submit, or
            # blindly hedge the other side. No hidden recovery actions.
            self.journal.record(key,"attention_required",str(exc))
            raise RecoveryRequired(
                "自動進場中斷，可能有單邊 Demo 持倉。"
                "已停下且不會重複送單或自行平倉；"
                f"請人工確認兩邊帳戶後再處理。原因：{exc}"
            ) from exc
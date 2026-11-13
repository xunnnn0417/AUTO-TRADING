"""Guarded post-fill trade automation, testable without a broker.

Execution uses a strict BrokerExecutionPort. Normal paired entry requires
verified accounts and uniquely identified positions; explicitly selected
recovery tests use the same identity checks. Account type labels are
informational only. No click or
retry on uncertain state. The default Windows UI adapter refuses submission
until the real GUI readback contract has been proven for BOTH brokers.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

from .test_mode import effective_test_symbol
from pathlib import Path
from typing import Protocol, Callable
import hashlib
import json
import os
import threading
import time

from .windows import AutomationError
from .recovery_policy import validate_terminal_rejection
from .phase_timing_report import (
    LocalPhaseTimingStore, record_submit_timings, timed_call, timed_operation,
)


@dataclass(frozen=True)
class DemoAccount:
    platform: str
    account_id: str
    server: str
    # Kept for compatibility with stored callers; account type is not read.
    is_demo: bool | None
    verified: bool


def _same_account_identity(current: DemoAccount, expected: DemoAccount) -> bool:
    """Compare account identity without treating Demo/Live labels as identity."""
    return (
        current.platform.casefold() == expected.platform.casefold()
        and current.account_id == expected.account_id
        and (
            not current.server
            or not expected.server
            or current.server.casefold() == expected.server.casefold()
        )
    )


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
                    lot: Decimal, key: str,
                    submit_deadline: float | None = None) -> None: ...
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
        # The journal prevents blind duplicate orders after a restart.
        # Flush its contents before replacing the last confirmed record.
        with tmp.open("w",encoding="utf-8") as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
            stream.flush()
            os.fsync(stream.fileno())
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
                 guard: Callable[[], None], log: Callable[[str], None],
                 timing_store: LocalPhaseTimingStore | None = None):
        self.port=port
        self.journal=journal
        self.guard=guard
        self.log=log
        self.phase_timing_store=timing_store
        self.last_account_ids={}

    @staticmethod
    def _effective_test_symbol(symbol: str) -> str:
        return effective_test_symbol(symbol)

    def _inspect_entry_accounts(
        self, instruction, internal_platform: str, external_platform: str,
        profile: str, sheet_url: str, *, authorized_reentry_id: str = "",
        prechecked_accounts: tuple[DemoAccount,DemoAccount] | None = None,
    ) -> tuple[DemoAccount, DemoAccount, str, float]:
        """Read and validate account identities, without reading positions."""
        if prechecked_accounts is None:
            accounts_started=time.perf_counter()
            account_e=timed_call(
                "確認交易帳戶",self.port.inspect_account,
                external_platform,"external",
                platform=external_platform,role="external",
            )
            account_i=timed_call(
                "確認交易帳戶",self.port.inspect_account,
                internal_platform,"internal",
                platform=internal_platform,role="internal",
            )
            account_read_ms=(time.perf_counter()-accounts_started)*1000
            set_expected=getattr(self.port,"set_expected_accounts",None)
            if callable(set_expected):
                set_expected({})
        else:
            if (not isinstance(prechecked_accounts,(tuple,list))
                or len(prechecked_accounts)!=2):
                raise AutomationError("進場前帳戶核對資料格式錯誤；未送單。")
            account_i,account_e=prechecked_accounts
            if not all(isinstance(a,DemoAccount) for a in (account_i,account_e)):
                raise AutomationError("進場前帳戶核對資料不完整；未送單。")
            account_read_ms=0.0
            set_expected=getattr(self.port,"set_expected_accounts",None)
            if callable(set_expected):
                set_expected({
                    (internal_platform,"internal"):account_i,
                    (external_platform,"external"):account_e,
                })
        for account,platform in ((account_i,internal_platform),
                                 (account_e,external_platform)):
            if (not account.verified
                or not account.account_id
                or (not account.server and platform.casefold() not in {
                    "ctrader", "gooeytrade",
                })
                or account.platform!=platform):
                raise AutomationError(
                    f"{platform} 帳戶身分未完整核對，拒絕自動送單。"
                )
        if _same_account_identity(account_i,account_e):
            raise AutomationError("場內與場外不可使用同一交易帳戶。")
        self.last_account_ids={
            "internal":account_i.account_id,
            "external":account_e.account_id,
        }
        key=self.fingerprint(profile,sheet_url,(account_i,account_e),instruction)
        if authorized_reentry_id:
            key=hashlib.sha256(
                f"{key}|user-approved-reentry|{authorized_reentry_id}".encode("utf-8")
            ).hexdigest()
        return account_i,account_e,key,account_read_ms

    def preflight_duplicate_entry(
        self, instruction, internal_platform: str, external_platform: str,
        profile: str, sheet_url: str,
    ) -> tuple[DemoAccount,DemoAccount]:
        """Stop on an exact previous attempt before either form is filled."""
        self.guard()
        execution_symbol=self._effective_test_symbol(instruction.symbol)
        if hasattr(self.port,"set_expected_symbol"):
            self.port.set_expected_symbol(execution_symbol)
        account_i,account_e,key,_elapsed=self._inspect_entry_accounts(
            instruction,internal_platform,external_platform,profile,sheet_url
        )
        self.last_key=key
        existing=self.journal.entry(key)
        if existing:
            raise DuplicateEntryDecisionRequired(
                key,existing,self.retryable_duplicate(existing)
            )
        return account_i,account_e

    @timed_operation("拒單證實後補進")
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
        symbol=self._effective_test_symbol(instruction.symbol)
        certify=getattr(self.port,"prove_terminal_rejection",None)
        if not callable(certify):
            return None
        self.guard()
        proof=validate_terminal_rejection(
            certify(platform,role,key,account.account_id,symbol),
            attempt_key=key,platform=platform,role=role,
            account_id=account.account_id,symbol=symbol,
        )
        if proof is None:
            return None
        # Start the recovery clock when a correlated final rejection is
        # established. Unknown or delayed fills never enter this path.
        recovery_deadline=time.monotonic()+15.0
        # Reject stale account changes, other-leg movement or ambiguous
        # missing-leg positions even if the broker proof was genuine.
        for plat,side,expected_account in (
            (platform,role,account),
            (other_platform,other_role,other_account),
        ):
            fresh=self.port.inspect_account(plat,side)
            if (not fresh.verified
                    or not _same_account_identity(fresh,expected_account)):
                raise RecoveryRequired("補單前帳戶身分已變動，禁止再送單。")
        current_other=self.port.snapshot_positions(other_platform,other_role)
        matches=[p for p in current_other if p.ticket==verified_other.ticket]
        if len(current_other)!=1 or len(matches)!=1:
            raise RecoveryRequired("補單前另一邊已成交持倉不再唯一，停止。")
        self._validate_position(
            matches[0],other_platform,other_direction,
            other_lot,other_account,symbol
        )
        current_missing=self.port.snapshot_positions(platform,role)
        if current_missing!=baseline or current_missing:
            raise RecoveryRequired("拒單側持倉已變動或非空，禁止補單。")
        # Reservation is the crash-safe barrier. A restart cannot resend.
        self.journal.reserve_verified_rescue(
            key,role,proof.original_broker_order_id
        )
        self.log(f"{role} 有最終拒單證明，僅嘗試補開一次。")
        pos=self._submit_and_confirm(
            platform,role,direction,lot,account,baseline,
            symbol,key,submit_deadline=recovery_deadline
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

    @timed_operation("成交結果補讀")
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
        started=time.perf_counter()
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
                        f"{position.ticket}；沒有重新送單；"
                        f"補讀耗時 {(time.perf_counter()-started)*1000:.0f}ms。"
                    )
                    return position
                if newly_seen or len(observed) != len(baseline) or (
                    {p.ticket for p in observed} != previous
                ):
                    raise RecoveryRequired(
                        f"{role} {platform} 補讀發現不唯一／不符合基準的"
                        "持倉變化，不能推定未成交或自動補單；"
                        f"補讀耗時 {(time.perf_counter()-started)*1000:.0f}ms。"
                    )
            if attempt == 0:
                time.sleep(0.15)
        self.log(
            f"{role} {platform} 成交後補讀：2 次，"
            f"總耗時 {(time.perf_counter()-started)*1000:.0f}ms；"
            "仍未證實成交或拒單。"
        )
        return None

    @timed_operation("單側送單與成交確認")
    def _submit_and_confirm(self, platform: str, role: str, direction: str,
                            volume: Decimal, account: DemoAccount,
                            before: tuple[Position,...], symbol: str,
                            key: str,
                            submit_deadline: float | None = None) -> Position:
        started=time.perf_counter()
        phase_times={}
        try:
            self.guard()
            if (submit_deadline is not None
                    and time.monotonic()>=submit_deadline):
                raise RecoveryRequired(
                    "15 秒補進時限已過，未送出恢復單。"
                )
            # Mark MAY_HAVE_SENT *before* any click: if the process dies, a
            # later invocation must not blindly send the same trade again.
            # submit_once performs the mandatory fresh form readback and
            # checks the deadline immediately before its one broker click.
            self.journal.record(key,f"sending_{role}","尚未確認是否有成交")
            submit_started=time.perf_counter()
            try:
                if submit_deadline is None:
                    timed_call(
                        "最終表單核對與送單",self.port.submit_once,
                        platform,role,direction,volume,key,
                        platform=platform,role=role,
                    )
                else:
                    timed_call(
                        "限時補進的最終核對與送單",self.port.submit_once,
                        platform,role,direction,volume,key,
                        submit_deadline=submit_deadline,
                        platform=platform,role=role,
                    )
            finally:
                phase_times["平台核對與送單呼叫"]=(
                    time.perf_counter()-submit_started
                )*1000
            # No retries on Send. Even a timeout may mean a successful fill.
            confirm_started=time.perf_counter()
            try:
                pos=timed_call(
                    "成交持倉回讀",self.port.confirm_new_position,
                    platform,role,before,direction,volume,account.account_id,
                    platform=platform,role=role,
                )
            finally:
                # Preserve duration when confirmation fails or times out.
                phase_times["成交確認"]=(time.perf_counter()-confirm_started)*1000
            validate_started=time.perf_counter()
            timed_call(
                "成交資料核對",self._validate_position,
                pos,platform,direction,volume,account,symbol,
                platform=platform,role=role,
            )
            phase_times["成交資料核對"]=(time.perf_counter()-validate_started)*1000
            self.journal.record(key,f"filled_{role}",f"ticket={pos.ticket}")
            self.log(f"{role} {platform} 成交已確認：{pos.ticket}")
            return pos
        finally:
            elapsed=(time.perf_counter()-started)*1000
            parts=[
                f"{name} {duration:.0f}ms"
                for name,duration in phase_times.items()
            ]
            submit_phases=getattr(
                self.port,"submit_phase_timings",{}
            )
            port_times=(
                submit_phases.get(role,{})
                if isinstance(submit_phases,dict) else {}
            )
            if (isinstance(port_times,dict)
                    and port_times.get("start",0)>=started):
                if "form_verified" in port_times:
                    parts.append(
                        "送單前表單讀回 "
                        f"{(port_times['form_verified']-port_times.get('form_check_started',port_times['start']))*1000:.0f}ms"
                    )
                elif "form_check_started" in port_times:
                    parts.append(
                        "送單前表單讀回中斷 "
                        f"{(time.perf_counter()-port_times['form_check_started'])*1000:.0f}ms"
                    )
                if "window_bound" in port_times:
                    parts.append(
                        "送單視窗定位 "
                        f"{(port_times['window_bound']-port_times['start'])*1000:.0f}ms"
                    )
                if "uia_inventory_returned" in port_times:
                    parts.append(
                        "cTrader UIA清單 "
                        f"{(port_times['uia_inventory_returned']-port_times.get('uia_inventory_started',port_times['start']))*1000:.0f}ms"
                    )
                elif "uia_inventory_started" in port_times:
                    parts.append(
                        "cTrader UIA清單中斷 "
                        f"{(time.perf_counter()-port_times['uia_inventory_started'])*1000:.0f}ms"
                    )
                if "submit_target_verified" in port_times:
                    parts.append(
                        "送單鍵定位核對 "
                        f"{(port_times['submit_target_verified']-port_times.get('submit_target_started',port_times['form_verified']))*1000:.0f}ms"
                    )
                elif "submit_target_started" in port_times:
                    parts.append(
                        "送單鍵定位中斷 "
                        f"{(time.perf_counter()-port_times['submit_target_started'])*1000:.0f}ms"
                    )
                if {"click_started","click_returned"}<=set(port_times):
                    parts.append(
                        "點擊呼叫 "
                        f"{(port_times['click_returned']-port_times['click_started'])*1000:.0f}ms"
                    )
                polls=port_times.get("confirm_snapshot_count")
                if isinstance(polls,int):
                    parts.append(
                        f"成交讀取 {polls} 次／平台讀取合計 "
                        f"{port_times.get('confirm_snapshot_total_ms',0):.0f}ms"
                    )
                remaining=port_times.get("deadline_remaining_ms")
                if isinstance(remaining,(int,float)):
                    parts.append(
                        f"點擊前期限剩餘 {remaining:.0f}ms"
                        if remaining>=0 else f"點擊前已逾時 {-remaining:.0f}ms"
                    )
            parts.append(f"本階段總計 {elapsed:.0f}ms")
            try:
                record_submit_timings(self.port,platform,role)
                self.log(
                    f"{role} {platform} 進場分段計時："
                    + "；".join(parts)
                )
            except Exception:
                pass

    @timed_operation("單側重新進場")
    def run_single_leg_test(
        self, instruction, internal_platform: str, external_platform: str,
        profile: str, sheet_url: str, *, role: str,
        sync_sl_tp: bool,
        submit_deadline: float | None = None,
        expected_other_ticket: str | None = None,
        expected_account_ids: dict | None = None,
        draw_tv: bool = False,
        draw_internal: bool = False,
        operation: str = "test",
    ) -> tuple[Position, Position]:
        """Re-enter only the missing leg while preserving its counterpart."""
        if role not in ("internal", "external"):
            raise RecoveryRequired("單邊重進測試場別無效。")
        if operation not in ("test", "user"):
            raise RecoveryRequired("單邊重進操作類型無效。")
        if draw_tv and not sync_sl_tp:
            raise RecoveryRequired("繪製 TradingView 前必須完成 SL／TP 同步。")
        self.guard()
        if submit_deadline is not None and time.monotonic()>=submit_deadline:
            raise RecoveryRequired("15 秒補進時限已過，未送出恢復單。")
        platforms={"internal":internal_platform,"external":external_platform}
        instruction_legs={
            "internal":(instruction.internal_direction,instruction.internal),
            "external":(instruction.external_direction,instruction.external),
        }
        accounts={}
        for side,platform in platforms.items():
            accounts[side]=timed_call(
                "確認交易帳戶",self.port.inspect_account,
                platform,side,platform=platform,role=side,
            )
        for side, account in accounts.items():
            if (not account.verified or not account.account_id
                    or (not account.server and platforms[side].casefold()
                        not in {"ctrader","gooeytrade"})
                    or account.platform != platforms[side]):
                raise RecoveryRequired(
                    f"{platforms[side]} 帳戶身分未完整核對，停止單邊重進。"
                )
            if (isinstance(expected_account_ids,dict)
                    and expected_account_ids.get(side)
                    and account.account_id!=expected_account_ids[side]):
                raise RecoveryRequired(
                    f"{platforms[side]} 帳戶已改變，停止單邊重進。"
                )
        if _same_account_identity(
            accounts["internal"],accounts["external"]
        ):
            raise RecoveryRequired("場內與場外是同一帳戶，停止單邊重進。")
        symbol=self._effective_test_symbol(instruction.symbol)
        snapshots={}
        for side in ("internal","external"):
            snapshots[side]=timed_call(
                "核對目前持倉",self.port.snapshot_positions,
                platforms[side],side,platform=platforms[side],role=side,
            )
        other="external" if role=="internal" else "internal"
        if snapshots[role]:
            raise RecoveryRequired(
                f"{role} 目前仍有持倉，不會重複進場。"
            )
        if len(snapshots[other])!=1:
            raise RecoveryRequired(
                f"{other} 需要恰有一筆可核對持倉，才允許單邊重進。"
            )
        if (expected_other_ticket is not None
                and snapshots[other][0].ticket!=expected_other_ticket):
            raise RecoveryRequired(
                f"{other} 持倉編號已改變，停止單邊重進。"
            )
        other_direction,other_values=instruction_legs[other]
        self._validate_position(
            snapshots[other][0],platforms[other],other_direction,
            other_values.lot,accounts[other],symbol,
        )
        other_position=snapshots[other][0]
        if (other_position.sl is None or other_position.tp is None
                or other_position.sl<=0 or other_position.tp<=0
                or (other_position.direction=="BUY" and not
                    other_position.sl<other_position.entry_price<other_position.tp)
                or (other_position.direction=="SELL" and not
                    other_position.tp<other_position.entry_price<other_position.sl)):
            raise RecoveryRequired(
                f"{other} 現有持倉缺少可確認的 SL／TP，停止單邊重進。"
            )
        remember=getattr(self.port,"remember_verified_position_role",None)
        if callable(remember):
            remember(platforms[other],other,other_position)
        direction,values=instruction_legs[role]
        target_platform=platforms[role]
        if sync_sl_tp:
            target_points=self.port.automation.config["platforms"][target_platform].get(
                "points",{}
            )
            required_modify=(
                "position_order_row","position_sl_input",
                "position_tp_input","position_modify_confirm",
            )
            if any(not isinstance(target_points.get(key),dict)
                   or not target_points[key] for key in (
                       "lot_input","sl_input","tp_input",
                       "order_submit_button" if "MT5" not in target_platform.upper()
                       else ("order_submit_buy" if direction=="BUY"
                             else "order_submit_sell"),
                   )):
                raise RecoveryRequired(
                    f"{target_platform} 缺少單邊重進所需的欄位校準。"
                )
            modify_roles=["external"]
            if role=="internal" and "MT5" in target_platform.upper():
                modify_roles.append("internal")
            for modify_role in modify_roles:
                modify_points=self.port.automation.config["platforms"][
                    platforms[modify_role]
                ].get("points",{})
                if any(not isinstance(modify_points.get(key),dict)
                       or not modify_points[key] for key in required_modify):
                    raise RecoveryRequired(
                        f"{platforms[modify_role]} 缺少 SL／TP 修改校準，"
                        "未送出重進單。"
                    )
        journal_prefix="user-reentry" if operation=="user" else "test-reentry"
        complete_status=(
            "user_reentry_complete" if operation=="user"
            else "test_reentry_complete"
        )
        self.last_key=journal_prefix+"-"+hashlib.sha256(
            f"{profile}|{sheet_url}|{accounts}|{role}|{time.time_ns()}".encode()
        ).hexdigest()
        self.journal_current_attempt=True
        self.journal.record(
            self.last_key,
            "prepared_user_reentry" if operation=="user"
            else "prepared_test_reentry",
            role,
        )
        try:
            new_position=self._submit_and_confirm(
                target_platform,role,direction,values.lot,accounts[role],
                snapshots[role],symbol,self.last_key,
                submit_deadline=submit_deadline,
            )
            if role=="internal":
                if "MT5" in target_platform.upper():
                    sl,tp=instruction.estimated_prices(
                        direction,values,new_position.entry_price
                    )
                    timed_call(
                        "重新進場設定 SL/TP",self.port.set_position_sl_tp,
                        new_position,sl,tp,platform=target_platform,role=role,
                    )
                    timed_call(
                        "重新進場核對 SL/TP",self.port.verify_position_sl_tp,
                        new_position,sl,tp,platform=target_platform,role=role,
                    )
                else:
                    timed_call(
                        "重新進場核對 SL/TP",self.port.verify_internal_protection,
                        new_position,values.sl_points,values.tp_points,
                        platform=target_platform,role=role,
                    )
                reference_entry=new_position.entry_price
            else:
                reference_entry=snapshots["internal"][0].entry_price
            if sync_sl_tp:
                external=snapshots["external"][0] if role=="internal" else new_position
                sl,tp=instruction.estimated_prices(
                    instruction.external_direction,
                    instruction.external,reference_entry,
                )
                timed_call(
                    "重新同步場外 SL/TP",self.port.set_position_sl_tp,
                    external,sl,tp,platform=platforms["external"],
                    role="external",
                )
                timed_call(
                    "重新核對場外 SL/TP",self.port.verify_position_sl_tp,
                    external,sl,tp,platform=platforms["external"],
                    role="external",
                )
                self.journal.record(self.last_key,"synchronized",external.ticket)
            current={}
            for side in ("internal","external"):
                current[side]=timed_call(
                    "重新讀取雙邊持倉",self.port.snapshot_positions,
                    platforms[side],side,
                    platform=platforms[side],role=side,
                )
            expected_tickets={role:new_position.ticket,other:snapshots[other][0].ticket}
            for side in ("internal","external"):
                if (len(current[side])!=1 or
                        current[side][0].ticket!=expected_tickets[side]):
                    raise RecoveryRequired(
                        f"單邊重進後 {side} 持倉與預期不符，停止後續操作。"
                    )
            if draw_tv:
                tv_started=time.perf_counter()
                internal_position=current["internal"][0]
                timed_call(
                    "TradingView 繪圖",self.port.draw_tradingview,
                    instruction,internal_platform,
                    internal_position.entry_price,draw_internal,
                )
                self.log(
                    "單邊補進後 TradingView 繪圖："
                    f"{(time.perf_counter()-tv_started)*1000:.0f}ms。"
                )
                self.journal.record(self.last_key,"tv_drawn",role)
            self.journal.record(self.last_key,complete_status,role)
            return current["internal"][0],current["external"][0]
        except Exception as exc:
            self.journal.record(self.last_key,"attention_required",str(exc))
            raise RecoveryRequired(
                f"單邊重進測試在 {role} 階段中斷；不會再次送單。原因：{exc}"
            ) from exc

    @timed_operation("單側平倉")
    def run_single_leg_close_test(
        self, instruction, internal_platform: str, external_platform: str,
        profile: str, sheet_url: str, *, role: str,
        expected_ticket: str | None = None,
        expected_account_ids: dict | None = None,
        require_other_empty: bool = False,
        operation: str = "test",
    ) -> Position:
        """Close one explicitly selected, uniquely matched position."""
        if role not in ("internal", "external"):
            raise RecoveryRequired("單邊平倉測試場別無效。")
        if operation not in ("test", "user"):
            raise RecoveryRequired("單邊平倉操作類型無效。")
        self.guard()
        platforms={"internal":internal_platform,"external":external_platform}
        direction,values=(
            (instruction.internal_direction,instruction.internal)
            if role=="internal" else
            (instruction.external_direction,instruction.external)
        )
        account=timed_call(
            "平倉前確認交易帳戶",self.port.inspect_account,
            platforms[role],role,platform=platforms[role],role=role,
        )
        if (not account.verified or not account.account_id
                or account.platform!=platforms[role]):
            raise RecoveryRequired("平倉前無法確認交易帳戶，未操作。")
        if (isinstance(expected_account_ids,dict)
                and expected_account_ids.get(role)
                and account.account_id!=expected_account_ids[role]):
            raise RecoveryRequired("平倉前帳戶已改變，未操作。")
        other="external" if role=="internal" else "internal"
        if require_other_empty:
            other_account=timed_call(
                "核對配對帳戶",self.port.inspect_account,
                platforms[other],other,
                platform=platforms[other],role=other,
            )
            if (not other_account.verified or not other_account.account_id
                    or other_account.platform!=platforms[other]
                    or (isinstance(expected_account_ids,dict)
                        and expected_account_ids.get(other)
                        and other_account.account_id!=expected_account_ids[other])):
                raise RecoveryRequired("另一個交易帳戶身分已改變，停止平倉。")
            if timed_call(
                "核對配對持倉",self.port.snapshot_positions,
                platforms[other],other,platform=platforms[other],role=other,
            ):
                raise RecoveryRequired(
                    "另一邊目前也有持倉；狀態已改變，停止平倉。"
                )
        positions=timed_call(
            "讀取待平倉持倉",getattr(
                self.port,"snapshot_for_close",self.port.snapshot_positions
            ),
            platforms[role],role,platform=platforms[role],role=role,
        )
        if len(positions)!=1:
            raise RecoveryRequired(
                f"{role} 持倉不是唯一一筆；不會猜測要平哪一筆。"
            )
        position=positions[0]
        if expected_ticket is not None and position.ticket!=expected_ticket:
            raise RecoveryRequired("平倉目標編號已改變，未操作。")
        self._validate_position(
            position,platforms[role],direction,values.lot,account,
            self._effective_test_symbol(instruction.symbol),
        )
        journal_prefix="user-close" if operation=="user" else "test-close"
        self.last_key=journal_prefix+"-"+hashlib.sha256(
            f"{profile}|{sheet_url}|{account}|{position.ticket}|{time.time_ns()}".encode()
        ).hexdigest()
        self.journal_current_attempt=True
        self.journal.record(
            self.last_key,
            "prepared_user_close" if operation=="user" else "prepared_test_close",
            position.ticket,
        )
        try:
            close_once=getattr(self.port,"close_position_once",None)
            if not callable(close_once):
                raise RecoveryRequired("交易介面尚未支援校準平倉按鈕。")
            timed_call(
                "執行平倉按鈕",close_once,position,role,
                platform=platforms[role],role=role,
            )
            if require_other_empty:
                for side in ("internal","external"):
                    if timed_call(
                        "平倉後持倉回讀",self.port.snapshot_positions,
                        platforms[side],side,
                        platform=platforms[side],role=side,
                    ):
                        raise RecoveryRequired(
                            "平倉後仍讀到配對持倉；請人工核對，不會重試。"
                        )
            self.journal.record(
                self.last_key,
                "user_close_confirmed" if operation=="user"
                else "test_close_confirmed",
                position.ticket,
            )
            return position
        except Exception as exc:
            self.journal.record(self.last_key,"attention_required",str(exc))
            raise RecoveryRequired(
                f"單邊平倉測試尚未確認完成；不會再次點擊。原因：{exc}"
            ) from exc

    @timed_operation("雙邊自動進場")
    def run(self, instruction, internal_platform: str, external_platform: str,
            profile: str, sheet_url: str, *,
            sync_sl_tp: bool, draw_tv: bool,
            draw_internal: bool=False,
            duplicate_confirmation: tuple[str,str,str,str] | None = None,
            manual_reconciliation_confirmed: bool = False,
            fast_pair: bool = False,
            test_skip_role: str | None = None,
            test_run_id: str = "",
            test_delay: bool = False,
            authorized_reentry_id: str = "",
            prechecked_accounts: tuple[DemoAccount,DemoAccount] | None = None,
            ) -> tuple[Position,Position]:
        self.last_key = None
        self.journal_current_attempt = False
        self._test_delay_expired_role = None
        precheck_started=time.perf_counter()
        self.guard()
        execution_symbol=self._effective_test_symbol(instruction.symbol)
        if hasattr(self.port, "set_expected_symbol"):
            self.port.set_expected_symbol(execution_symbol)
        if draw_tv and not sync_sl_tp:
            raise AutomationError("自動繪製 TV 必須先啟用並完成 SL/TP 同步。")
        if test_skip_role not in (None,"internal","external"):
            raise AutomationError("測試故障注入場別無效；尚未送單。")
        if test_skip_role and (not test_run_id or fast_pair):
            raise AutomationError(
                "單邊重進測試需要唯一測試編號並使用逐邊核對；尚未送單。"
            )
        if authorized_reentry_id and not authorized_reentry_id.strip():
            raise AutomationError("重新進場識別碼無效；尚未送單。")
        if fast_pair and (internal_platform, external_platform) not in {
            ("cTrader", "MT5"), ("MT5", "cTrader"),
        }:
            raise AutomationError(
                "快速雙邊目前只支援 cTrader + MT5 的已核對帳戶"
                "（兩者場內／場外可互換）；本次未送單。"
            )
        # The fill workflow leaves MT5/external on top. Verify its identity
        # first, then switch to internal; never guess stale HWND coordinates.
        account_i,account_e,key,account_read_ms=self._inspect_entry_accounts(
            instruction,internal_platform,external_platform,profile,sheet_url,
            authorized_reentry_id=authorized_reentry_id,
            prechecked_accounts=prechecked_accounts,
        )
        if test_run_id:
            key=hashlib.sha256(
                f"{key}|test|{test_run_id}".encode("utf-8")
            ).hexdigest()
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
        positions_started=time.perf_counter()
        before_e=timed_call(
            "讀取交易前持倉",self.port.snapshot_positions,
            external_platform,"external",
            platform=external_platform,role="external",
        )
        before_i=timed_call(
            "讀取交易前持倉",self.port.snapshot_positions,
            internal_platform,"internal",
            platform=internal_platform,role="internal",
        )
        position_read_ms=(time.perf_counter()-positions_started)*1000
        self.log(
            "交易前讀取耗時："
            f"帳戶確認 {account_read_ms:.0f}ms；"
            f"兩側持倉讀取 {position_read_ms:.0f}ms。"
        )
        # A previously interrupted attempt may already have filled BOTH
        # accounts. After explicit manual history review, permit a strict
        # NO-SUBMIT reconciliation of the two *existing* unique positions.
        # A missing/ambiguous side must never turn into a guess-and-resend.
        if before_i or before_e:
            if (not existing or not manual_reconciliation_confirmed
                or duplicate_confirmation is None):
                raise AutomationError(
                    "已選帳戶存在持倉。請先核對兩個帳戶的交易歷史，"
                    "使用舊交易紀錄的明確確認流程；不會新增訂單。"
                )
            if len(before_i)!=1 or len(before_e)!=1:
                raise RecoveryRequired(
                    "目前已選帳戶存在持倉，但雙邊未找到各一筆唯一對應持倉，"
                    "不能將缺少的交易視為拒單，也不會自動補單。"
                )
            first,second=before_i[0],before_e[0]
            self._validate_position(
                first,internal_platform,instruction.internal_direction,
                instruction.internal.lot,account_i,execution_symbol,
            )
            self._validate_position(
                second,external_platform,instruction.external_direction,
                instruction.external.lot,account_e,execution_symbol,
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
                    "原有兩筆持倉已核對完成；未再送單，"
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
        capabilities_started=time.perf_counter()
        if validate is not None:
            timed_call(
                "校準與操作能力預檢",validate,
                internal_platform,external_platform,
                instruction.internal_direction,instruction.external_direction,
                sync_sl_tp=sync_sl_tp,draw_tv=draw_tv,
                platform=internal_platform,role="internal",
            )
        capabilities_ms=(time.perf_counter()-capabilities_started)*1000
        # After the external-side fill is complete, inspect its form
        # first, then the internal side. Both checks remain mandatory.
        external_form_started=time.perf_counter()
        timed_call(
            "送單表單預檢",self.port.verify_order_form,
            external_platform,"external",
            instruction.external_direction,instruction.external.lot,
            platform=external_platform,role="external",
        )
        external_form_ms=(time.perf_counter()-external_form_started)*1000
        internal_form_started=time.perf_counter()
        timed_call(
            "送單表單預檢",self.port.verify_order_form,
            internal_platform,"internal",
            instruction.internal_direction,instruction.internal.lot,
            platform=internal_platform,role="internal",
        )
        internal_form_ms=(time.perf_counter()-internal_form_started)*1000
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
            f"能力核對 {capabilities_ms:.0f}ms，"
            f"場外表單 {external_form_ms:.0f}ms，"
            f"場內表單 {internal_form_ms:.0f}ms；"
            "已準備送單。最後送出前仍會各做一次最新唯讀核對。"
        )
        try:
            if fast_pair:
                # Explicitly opted-in rapid hedge: BOTH dialogs
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
                    try:
                        timed_call(
                            "快速雙邊最終核對與送單",
                            self.port.submit_once,plat,role,direction,lot,key,
                            platform=plat,role=role,
                        )
                    finally:
                        record_submit_timings(self.port,plat,role)
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
                        inventory_at=ex_t.get("uia_inventory_returned")
                        if inventory_at is not None:
                            self.log(
                                "快速雙邊 cTrader：送單呼叫至新鮮 UIA 清單"
                                f" {((inventory_at-ex_t['start'])*1000):.0f}ms；"
                                "清單回傳至帳戶／商品／欄位核對完成 "
                                f"{((ex_t['form_verified']-inventory_at)*1000):.0f}ms。"
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
                    confirm_started=time.perf_counter()
                    try:
                        pos=timed_call(
                            "成交持倉回讀",self.port.confirm_new_position,
                            plat,role,baseline,direction,lot,account.account_id,
                            platform=plat,role=role,
                        )
                        timed_call(
                            "成交資料核對",self._validate_position,
                            pos,plat,direction,lot,account,execution_symbol,
                            platform=plat,role=role,
                        )
                        self.journal.record_verified_leg(key,role,pos)
                        verified[role]=pos
                    except Exception as exc:
                        uncertainty[role]=str(exc)
                    finally:
                        record_submit_timings(self.port,plat,role)
                        confirm_elapsed=(time.perf_counter()-confirm_started)*1000
                        timing_reader=getattr(
                            self.port,"submit_phase_timings",{}
                        )
                        timing=(
                            timing_reader.get(role,{})
                            if isinstance(timing_reader,dict) else {}
                        )
                        reads=timing.get("confirm_snapshot_count")
                        read_note=(
                            f"，持倉讀取 {reads} 次／累計 "
                            f"{timing.get('confirm_snapshot_total_ms',0):.0f}ms"
                            if isinstance(reads,int) else ""
                        )
                        self.log(
                            f"{role} {plat} 成交確認耗時 "
                            f"{confirm_elapsed:.0f}ms{read_note}。"
                        )
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
                            execution_symbol,key
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
                    role_labels={
                        "internal":f"場內（{internal_platform}）",
                        "external":f"場外（{external_platform}）",
                    }
                    read_details=[
                        f"{role_labels[role]}：{str(uncertainty[role])[:140]}"
                        for role in ("internal","external")
                        if role in uncertainty
                    ]
                    detail_summary=(
                        "持倉核對原因："+"；".join(read_details)+"。"
                        if read_details else ""
                    )
                    raise RecoveryRequired(
                        "；".join(states)+"。"+detail_summary+
                        "已保存可確認的持倉編號；"
                        "無法證明未成交前禁止自動補單。"
                    )
                first=verified["internal"]
                second=verified["external"]
                self.journal.record(
                    key,"both_confirmed",first.ticket+"/"+second.ticket
                )
                protection_started=time.perf_counter()
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
                    timed_call(
                        "場內設定 SL/TP",self.port.set_position_sl_tp,
                        first,sl_i,tp_i,platform=internal_platform,
                        role="internal",
                    )
                    timed_call(
                        "場內核對 SL/TP",self.port.verify_position_sl_tp,
                        first,sl_i,tp_i,platform=internal_platform,
                        role="internal",
                    )
                timed_call(
                    "場內止盈止損核對",self.port.verify_internal_protection,
                    first,instruction.internal.sl_points,
                    instruction.internal.tp_points,
                    platform=internal_platform,role="internal",
                )
                self.log(
                    "場內止盈止損設定與核對："
                    f"{(time.perf_counter()-protection_started)*1000:.0f}ms。"
                )
                self.journal.record(key,"internal_protected",first.ticket)
            else:
                if test_skip_role == "internal":
                    # Deterministic test-only omission: no internal submit
                    # call was made, so the missing order is provably unsent.
                    self.journal.record(
                        key,"test_injected_skip_internal",
                        "明確略過場內首筆送單；沒有送出場內訂單"
                    )
                    second=self._submit_and_confirm(
                        external_platform,"external",
                        instruction.external_direction,instruction.external.lot,
                        account_e,before_e,execution_symbol,key,
                    )
                    self.journal.record(
                        key,"test_recovery_started_internal",
                        "已確認場內從未送出；立即開始一次性補進"
                    )
                    recovery_deadline=time.monotonic()+15.0
                    if test_delay:
                        self._wait_test_timeout(recovery_deadline, "internal")
                    first=self._submit_and_confirm(
                        internal_platform,"internal",
                        instruction.internal_direction,instruction.internal.lot,
                        account_i,before_i,execution_symbol,key,
                        submit_deadline=recovery_deadline,
                    )
                else:
                    first=self._submit_and_confirm(
                        internal_platform,"internal",instruction.internal_direction,
                        instruction.internal.lot,account_i,before_i,execution_symbol,key)
            self.guard()
            # MT5 pre-submit SL/TP are based on a *reference quote*. Amend
            # the actual position using its executed price before other side.
            if not fast_pair:
                protection_started=time.perf_counter()
                if "MT5" in internal_platform.upper():
                    sl,tp=instruction.estimated_prices(
                        instruction.internal_direction,
                        instruction.internal,first.entry_price
                    )
                    timed_call(
                        "場內設定 SL/TP",self.port.set_position_sl_tp,
                        first,sl,tp,platform=internal_platform,
                        role="internal",
                    )
                    timed_call(
                        "場內核對 SL/TP",self.port.verify_position_sl_tp,
                        first,sl,tp,platform=internal_platform,
                        role="internal",
                    )
                else:
                    timed_call(
                        "場內止盈止損核對",self.port.verify_internal_protection,
                        first,instruction.internal.sl_points,
                        instruction.internal.tp_points,
                        platform=internal_platform,role="internal",
                    )
                self.log(
                    "場內止盈止損設定與核對："
                    f"{(time.perf_counter()-protection_started)*1000:.0f}ms。"
                )
                self.journal.record(key,"internal_protected",first.ticket)
                if test_skip_role == "internal":
                    # Both legs are already confirmed: external entered first,
                    # then the intentionally skipped internal recovery.
                    pass
                else:
                    if test_skip_role == "external":
                        self.journal.record(
                            key,"test_injected_skip_external",
                            "明確略過場外首筆送單；沒有送出場外訂單"
                        )
                        self.journal.record(
                            key,"test_recovery_started_external",
                            "已確認場外從未送出；立即開始一次性補進"
                        )
                        recovery_deadline=time.monotonic()+15.0
                        if test_delay:
                            self._wait_test_timeout(recovery_deadline, "external")
                    else:
                        recovery_deadline=None
                    try:
                        second=self._submit_and_confirm(
                            external_platform,"external",instruction.external_direction,
                            instruction.external.lot,account_e,before_e,
                            execution_symbol,key,
                            submit_deadline=recovery_deadline,
                        )
                    except Exception:
                    # Recheck the existing Positions tab first: a delayed
                    # fill is success, not proof that we should click twice.
                        second=self._visual_second_chance(
                            external_platform,"external",before_e,
                            instruction.external_direction,
                            instruction.external.lot,account_e,
                            execution_symbol,key
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
                sync_started=time.perf_counter()
                sl,tp=instruction.estimated_prices(
                    instruction.external_direction,
                    instruction.external,first.entry_price
                )
                timed_call(
                    "場外同步 SL/TP",self.port.set_position_sl_tp,
                    second,sl,tp,platform=external_platform,
                    role="external",
                )
                timed_call(
                    "場外核對 SL/TP",self.port.verify_position_sl_tp,
                    second,sl,tp,platform=external_platform,
                    role="external",
                )
                self.journal.record(key,"synchronized",
                                    first.ticket+"/"+second.ticket)
                self.log(
                    "場外 SL／TP 同步與讀回："
                    f"{(time.perf_counter()-sync_started)*1000:.0f}ms。"
                )
            if draw_tv:
                tv_started=time.perf_counter()
                timed_call(
                    "TradingView 繪圖",self.port.draw_tradingview,
                    instruction,internal_platform,first.entry_price,
                    draw_internal,
                )
                self.log(
                    "TradingView 繪圖："
                    f"{(time.perf_counter()-tv_started)*1000:.0f}ms。"
                )
            self.journal.record(key,"complete",first.ticket+"/"+second.ticket)
            self.log("雙邊自動進場、成交核對及已啟用的後續步驟完成。")
            return first,second
        except Exception as exc:
            # Persist uncertainty, do not auto-close, retry a submit, or
            # blindly hedge the other side. No hidden recovery actions.
            self.journal.record(key,"attention_required",str(exc))
            raise RecoveryRequired(
                "自動進場中斷，可能有單邊持倉。"
                "已停下且不會重複送單或自行平倉；"
                f"請人工確認兩邊帳戶後再處理。原因：{exc}"
            ) from exc

    @timed_operation("完整測試情境")
    def run_test_scenario(
        self, instruction, internal_platform: str, external_platform: str,
        profile: str, sheet_url: str, *, scenario: str,
        test_run_id: str, draw_tv: bool = False,
        draw_internal: bool = False,
        test_delay: bool = False,
    ) -> dict:
        """Run one complete, explicitly selected recovery test."""
        if not test_run_id.strip():
            raise RecoveryRequired("缺少本次測試識別碼；尚未送單。")
        if scenario not in {
            "weekend:BTCUSD", "weekend:ETHUSD",
            "reentry:internal", "reentry:external",
            "close:internal", "close:external",
        }:
            raise RecoveryRequired("完整測試情境無效；尚未操作交易平台。")
        if scenario in ("weekend:BTCUSD","weekend:ETHUSD"):
            positions=self.run(
                instruction,internal_platform,external_platform,
                profile,sheet_url,sync_sl_tp=True,draw_tv=draw_tv,
                draw_internal=draw_internal,fast_pair=False,
                test_run_id=test_run_id,
            )
            return {
                "scenario":scenario,"outcome":"weekend_pair_confirmed",
                "positions":positions,
            }
        role=scenario.rsplit(":",1)[1]
        if scenario.startswith("reentry:"):
            try:
                positions=self.run(
                    instruction,internal_platform,external_platform,
                    profile,sheet_url,sync_sl_tp=True,draw_tv=draw_tv,
                    draw_internal=draw_internal,fast_pair=False,
                    test_skip_role=role,test_run_id=test_run_id,
                    test_delay=test_delay,
                )
            except RecoveryRequired:
                if not (test_delay and role=="internal" and
                        self._test_delay_expired_role=="internal"):
                    raise
                confirmed=self.journal.entry(self.last_key).get("confirmed_legs",{})
                ticket=confirmed.get("external")
                if not ticket or confirmed.get("internal"):
                    raise
                self.run_single_leg_close_test(
                    instruction,internal_platform,external_platform,
                    profile,sheet_url,role="external",expected_ticket=ticket,
                    expected_account_ids=self.last_account_ids,
                    require_other_empty=True,
                )
                return {"scenario":scenario,"outcome":"external_closed_after_timeout",
                        "positions":()}
            return {
                "scenario":scenario,"outcome":"reentry_confirmed",
                "positions":positions,
            }

        first,second=self.run(
            instruction,internal_platform,external_platform,
            profile,sheet_url,sync_sl_tp=True,draw_tv=draw_tv,
            draw_internal=draw_internal,fast_pair=False,
            test_run_id=test_run_id,
        )
        initial={"internal":first,"external":second}
        closed_roles=[]
        try:
            self.run_single_leg_close_test(
                instruction,internal_platform,external_platform,
                profile,sheet_url,role=role,
            )
            closed_roles.append(role)
            if role=="internal":
                # Internal is the risk baseline: once its confirmed position
                # closes, close the still-open external Demo side, then stop.
                self.run_single_leg_close_test(
                    instruction,internal_platform,external_platform,
                    profile,sheet_url,role="external",
                )
                closed_roles.append("external")
                return {
                    "scenario":scenario,"outcome":"both_closed_waiting_user",
                    "initial_positions":initial,"positions":(),
                }

            # A confirmed external fill that is then closed is known to have
            # exited. Re-enter that external role once and resynchronize SL/TP.
            recovery_deadline=time.monotonic()+15.0
            if test_delay:
                self._wait_test_timeout(recovery_deadline, "external")
            final=self.run_single_leg_test(
                instruction,internal_platform,external_platform,
                profile,sheet_url,role="external",sync_sl_tp=True,
                submit_deadline=recovery_deadline,
            )
            return {
                "scenario":scenario,"outcome":"external_reentered",
                "initial_positions":initial,"positions":final,
            }
        except Exception as exc:
            setattr(exc,"test_scenario",scenario)
            setattr(exc,"test_initial_positions",initial)
            setattr(exc,"test_closed_roles",tuple(closed_roles))
            setattr(exc,"test_recovery_timeout",bool(
                test_delay and self._test_delay_expired_role=="external"
            ))
            raise

    @timed_operation("測試注入15秒延遲")
    def _wait_test_timeout(self, deadline: float, role: str) -> None:
        self.log("測試延遲中：將超過 15 秒補進時限；Esc 或右鍵可停止。")
        while time.monotonic() <= deadline:
            self.guard()
            time.sleep(min(0.1, max(0.001, deadline-time.monotonic()+0.01)))
        self.guard()
        self._test_delay_expired_role=role

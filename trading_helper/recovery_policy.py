"""Explicit, machine-verifiable terminal rejection proof for one-time rescue.

The current graphical Demo adapter does NOT have broker order identifiers or
authoritative terminal-order status and MUST return None. Never infer a
rejection from a position list, timeout, absence, or an error string.
"""
from __future__ import annotations
from dataclasses import dataclass
from time import monotonic
from .windows import AutomationError


@dataclass(frozen=True)
class TerminalRejectionProof:
    attempt_key: str
    platform: str
    role: str
    account_id: str
    symbol: str
    original_broker_order_id: str
    terminal_status: str
    original_not_filled: bool
    no_pending_order: bool
    server_confirmed: bool
    captured_monotonic: float


def validate_terminal_rejection(
    proof: TerminalRejectionProof | None, *,
    attempt_key: str, platform: str, role: str,
    account_id: str, symbol: str,
) -> TerminalRejectionProof | None:
    """Only a matching, fresh broker-native FINAL rejection qualifies."""
    if proof is None:
        return None
    if not isinstance(proof, TerminalRejectionProof):
        raise AutomationError("拒單證據格式不可信；拒絕自動補單。")
    if (
        proof.attempt_key != attempt_key or proof.platform != platform
        or proof.role != role or proof.account_id != account_id
        or proof.symbol.upper() != symbol.upper()
        or not proof.original_broker_order_id.strip()
        or proof.terminal_status != "REJECTED"
        or not proof.original_not_filled
        or not proof.no_pending_order
        or not proof.server_confirmed
        or not (0 <= monotonic()-proof.captured_monotonic <= 5)
    ):
        raise AutomationError("未具備可對應原訂單的最終拒單及無掛單證據；不補單。")
    return proof

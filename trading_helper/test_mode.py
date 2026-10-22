"""Narrow, process-scoped helpers for the temporary LAB test mode."""
from __future__ import annotations

import os

SUPPORTED_TEST_SYMBOLS = frozenset({"BTCUSD", "ETHUSD"})


def active_test_symbol_override() -> str:
    """Return the temporary override only when both explicit flags are set."""
    override=str(os.environ.get(
        "TRADING_HELPER_TEST_SYMBOL_OVERRIDE", ""
    )).strip().upper()
    skip_symbol_check=str(os.environ.get(
        "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK", ""
    )).strip() == "1"
    if override in SUPPORTED_TEST_SYMBOLS and skip_symbol_check:
        return override
    return ""


def effective_test_symbol(symbol: str) -> str:
    """Apply the supported test symbol only when both explicit flags are set."""
    override = active_test_symbol_override()
    if override:
        return override
    return symbol

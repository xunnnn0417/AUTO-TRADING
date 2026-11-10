"""Narrow, process-scoped helpers for the temporary LAB test mode."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

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


@contextmanager
def test_symbol_scope(symbol: str | None) -> Iterator[None]:
    """Apply an explicit test override only for one user-started workflow."""
    keys = (
        "TRADING_HELPER_TEST_SYMBOL_OVERRIDE",
        "TRADING_HELPER_TEST_SKIP_SYMBOL_CHECK",
    )
    previous = {key: os.environ.get(key) for key in keys}
    normalized = str(symbol or "").strip().upper()
    if normalized in SUPPORTED_TEST_SYMBOLS:
        os.environ[keys[0]] = normalized
        os.environ[keys[1]] = "1"
    else:
        os.environ.pop(keys[0], None)
        os.environ.pop(keys[1], None)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

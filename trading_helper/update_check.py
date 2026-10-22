"""Best-effort version check for the public LAB branch.

The check is read-only. It never downloads or installs application files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen


UPDATE_BRANCH = "lab/2026-10-16-safe-defaults-preflight"
UPDATE_PAGE_URL = (
    "https://github.com/xunnnn0417/AUTO-TRADING/tree/"
    "lab/2026-10-16-safe-defaults-preflight"
)
VERSION_SOURCE_URL = (
    "https://raw.githubusercontent.com/xunnnn0417/AUTO-TRADING/"
    "lab/2026-10-16-safe-defaults-preflight/trading_helper/__init__.py"
)
_VERSION_LINE = re.compile(r"^\s*__version__\s*=\s*['\"]([^'\"]+)['\"]", re.M)
_VERSION_NUMBER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class UpdateNotice:
    current_version: str
    latest_version: str
    page_url: str = UPDATE_PAGE_URL


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    match = _VERSION_NUMBER.fullmatch(version.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def fetch_latest_version(timeout: float = 2.5) -> str | None:
    """Read only the version constant from the configured GitHub LAB branch."""
    request = Request(
        VERSION_SOURCE_URL,
        headers={"User-Agent": "HedgeAssistant-LAB-version-check"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            source = response.read(32_768).decode("utf-8-sig", errors="replace")
    except (OSError, TimeoutError, URLError, ValueError):
        return None
    match = _VERSION_LINE.search(source)
    return match.group(1).strip() if match else None


def check_for_update(
    current_version: str,
    latest_version: str | None = None,
) -> UpdateNotice | None:
    """Return a notice only when GitHub has a strictly newer valid version."""
    if latest_version is None:
        latest_version = fetch_latest_version()
    current = _version_tuple(current_version)
    latest = _version_tuple(latest_version or "")
    if current is None or latest is None or latest <= current:
        return None
    return UpdateNotice(current_version.strip(), latest_version.strip())

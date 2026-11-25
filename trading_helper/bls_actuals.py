"""Released values (公布值) from the US Bureau of Labor Statistics.

Forex Factory's free feed has only 預期 / 前值. BLS publishes the official
numbers through its public API the moment a release goes out, with no key
(v1: limited daily requests, so we only ask a few times right after a
release). Only the headline figures Forex Factory lists are covered; GDP and
PCE come from BEA and are not handled here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.request import Request, urlopen

API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
# Seconds after the release time when we ask BLS (a handful per release).
ATTEMPTS = (20, 60, 150, 300, 900)
WINDOW = timedelta(hours=2)

# Forex Factory title -> (BLS series, how the headline figure is computed)
SERIES = {
    "cpi m/m": ("CUSR0000SA0", "mom"),
    "core cpi m/m": ("CUSR0000SA0L1E", "mom"),
    "cpi y/y": ("CUUR0000SA0", "yoy"),
    "core cpi y/y": ("CUUR0000SA0L1E", "yoy"),
    "ppi m/m": ("WPSFD4", "mom"),
    "core ppi m/m": ("WPSFD49104", "mom"),
    "non-farm employment change": ("CES0000000001", "change_k"),
    "unemployment rate": ("LNS14000000", "level"),
    "average hourly earnings m/m": ("CES0500000003", "mom"),
}


def series_for(title: str):
    return SERIES.get(str(title or "").strip().casefold())


def expected_period(release: datetime) -> tuple[int, int]:
    """These releases report the previous month."""
    year, month = release.year, release.month - 1
    return (year - 1, 12) if month == 0 else (year, month)


def _one_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def headline_value(kind: str, rows, release: datetime) -> str | None:
    """rows: [(year, month, Decimal)] newest first. None until BLS has the
    month this release is about."""
    monthly = {(year, month): value for year, month, value in rows}
    target = expected_period(release)
    if target not in monthly:
        return None
    year, month = target
    previous = (year - 1, 12) if month == 1 else (year, month - 1)
    current = monthly[target]
    if kind == "level":
        return _one_decimal(current) + "%"
    if kind == "change_k":
        if previous not in monthly:
            return None
        return f"{int((current - monthly[previous]).to_integral_value(ROUND_HALF_UP))}K"
    base = monthly.get((year - 1, month) if kind == "yoy" else previous)
    if not base:
        return None
    return _one_decimal((current / base - 1) * 100) + "%"


def fetch(series_ids, now: datetime, timeout=8) -> dict[str, list]:
    """One request for all due series. Read-only public data, no key."""
    body = json.dumps({"seriesid": sorted(set(series_ids)),
                       "startyear": str(now.year - 1), "endyear": str(now.year)}).encode()
    request = Request(API, data=body, headers={"Content-Type": "application/json",
                                               "User-Agent": "TradingWorkflowHelper/0.1"})
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read(2_000_000).decode("utf-8"))
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS: " + "; ".join(map(str, data.get("message") or [])))
    result = {}
    for series in data.get("Results", {}).get("series", []):
        rows = []
        for point in series.get("data", []):
            period = str(point.get("period", ""))
            if not period.startswith("M") or period == "M13":
                continue
            try:
                rows.append((int(point["year"]), int(period[1:]), Decimal(str(point["value"]))))
            except (KeyError, ValueError, ArithmeticError):
                continue
        result[str(series.get("seriesID"))] = rows
    return result

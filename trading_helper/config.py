from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "TradingWorkflowHelper"
CONFIG_PATH = APP_DIR / "config.json"
FALLBACK_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "sheet": {
        "mode": "csv",
        "data_layout": "row",
        "spreadsheet_url": "",
        "worksheet": "Sheet1",
        "gid": "0",
        "service_account_file": "",
        "row_number": 2,
        "status_value": "READY",
        "columns": {
            "status": "Status",
            "symbol": "Symbol",
            "direction": "Direction",
            "internal_lot": "Internal Lot",
            "internal_sl_points": "Internal SL points",
            "internal_tp_points": "Internal TP points",
            "external_lot": "External Lot",
            "external_sl_points": "External SL points",
            "external_tp_points": "External TP points",
            "estimated_price": "Estimated Price",
            "point_size": "Point Size",
            "price_digits": "Price Digits",
            "internal_entry_price": "Internal Entry Price",
            "final_external_sl_price": "Final External SL price",
            "final_external_tp_price": "Final External TP price",
        },
        "defaults": {"point_size": "0.0001", "price_digits": "5"},
    },
    "platforms": {
        "cTrader": {
            "window_title": {"internal": "cTrader", "external": "cTrader"},
            "points": {},
            "open_panel_before_fill": False,
        },
        "MT5": {
            "window_title": {"internal": "MetaTrader", "external": "MetaTrader"},
            "points": {},
            "open_panel_before_fill": False,
        },
        "TradingView": {
            "window_title": {"internal": "TradingView", "external": "TradingView"},
            "points": {},
            "open_panel_before_fill": False,
        },
    },
    "ui": {
        "internal_platform": "cTrader",
        "external_platform": "MT5",
    },
}


def _merge(default: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(default)
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class ConfigStore:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.data = self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return deepcopy(DEFAULT_CONFIG)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            return _merge(DEFAULT_CONFIG, loaded)
        except (OSError, json.JSONDecodeError):
            return deepcopy(DEFAULT_CONFIG)

    def save(self) -> None:
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(payload, encoding="utf-8")
        except OSError:
            self.path = FALLBACK_CONFIG_PATH
            self.path.write_text(payload, encoding="utf-8")

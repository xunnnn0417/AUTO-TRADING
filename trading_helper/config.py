from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "TradingWorkflowHelper"
CONFIG_PATH = APP_DIR / "config.json"
PROFILES_PATH = APP_DIR / "profiles.json"
FALLBACK_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_PROFILE_NAME = "預設方案"

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
            "daily_pnl": "Daily PnL",
            "internal_balance": "Internal Balance",
            "expected_sl_points": "Expected SL points",
            "expected_sl_percent": "Expected SL %",
        },
        "defaults": {"point_size": "0.0001", "price_digits": "5"},
    },
    "platforms": {
        "GooeyTrade": {
            "window_title": {
                "internal": "GooeyTrade",
                "external": "GooeyTrade",
            },
            "points": {},
            "open_panel_before_fill": False,
        },
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
        "tv_draw_internal": False,
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


def _ensure_platform(platforms: dict[str, Any], platform: str) -> dict[str, Any]:
    platforms.setdefault(platform, deepcopy(DEFAULT_CONFIG["platforms"][platform]))
    return platforms[platform]


def _copy_platform_data_if_empty(
    platforms: dict[str, Any],
    source: str,
    target: str,
) -> None:
    if source not in platforms:
        return
    target_profile = _ensure_platform(platforms, target)
    source_profile = platforms[source]
    if source_profile.get("points") and not target_profile.get("points"):
        target_profile["points"] = deepcopy(source_profile["points"])
    source_titles = source_profile.get("window_title", {})
    target_titles = target_profile.setdefault("window_title", {})
    for role in ("internal", "external"):
        if source_titles.get(role) and not target_titles.get(role):
            target_titles[role] = source_titles[role]
    if source_profile.get("open_panel_before_fill") and not target_profile.get(
        "open_panel_before_fill"
    ):
        target_profile["open_panel_before_fill"] = True


def _migrate_legacy_ctrader(config: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(config)
    platforms = migrated.setdefault("platforms", {})
    _ensure_platform(platforms, "cTrader")
    _copy_platform_data_if_empty(platforms, "GooeyTrade", "cTrader")
    ui = migrated.setdefault("ui", {})
    if ui.get("internal_platform") == "GooeyTrade":
        ui["internal_platform"] = "cTrader"
    if ui.get("external_platform") == "GooeyTrade":
        ui["external_platform"] = "cTrader"
    return migrated


def _migrate_legacy_mt5(config: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(config)
    platforms = migrated.setdefault("platforms", {})
    _ensure_platform(platforms, "MT5")
    _copy_platform_data_if_empty(platforms, "BYBIT MT5", "MT5")
    _copy_platform_data_if_empty(platforms, "原版MT5", "MT5")
    ui = migrated.setdefault("ui", {})
    if ui.get("internal_platform") in {"BYBIT MT5", "原版MT5"}:
        ui["internal_platform"] = "MT5"
    if ui.get("external_platform") in {"BYBIT MT5", "原版MT5"}:
        ui["external_platform"] = "MT5"
    return migrated


def _migrate_config(config: dict[str, Any]) -> dict[str, Any]:
    return _migrate_legacy_mt5(_migrate_legacy_ctrader(config))


class ConfigStore:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.data = self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return deepcopy(DEFAULT_CONFIG)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            return _merge(DEFAULT_CONFIG, _migrate_config(loaded))
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


class ProfileStore:
    def __init__(
        self,
        initial_config: dict[str, Any],
        path: Path = PROFILES_PATH,
    ):
        self.path = path
        self.data = self._load(initial_config)
        self.save()

    @property
    def active_name(self) -> str:
        return str(self.data["active"])

    def names(self) -> list[str]:
        return list(self.data["profiles"])

    def load_profile(self, name: str | None = None) -> dict[str, Any]:
        profile_name = name or self.active_name
        return _merge(DEFAULT_CONFIG, deepcopy(self.data["profiles"][profile_name]))

    def save_profile(self, name: str, config: dict[str, Any]) -> None:
        self.data["profiles"][name] = deepcopy(config)
        self.data["active"] = name
        self.save()

    def create(self, name: str, config: dict[str, Any]) -> None:
        self._validate_new_name(name)
        self.data["profiles"][name] = deepcopy(config)
        self.data["active"] = name
        self.save()

    def rename(self, old_name: str, new_name: str) -> None:
        if old_name not in self.data["profiles"]:
            raise ValueError("找不到要重新命名的方案。")
        self._validate_new_name(new_name)
        profiles = self.data["profiles"]
        rebuilt: dict[str, Any] = {}
        for name, config in profiles.items():
            rebuilt[new_name if name == old_name else name] = config
        self.data["profiles"] = rebuilt
        if self.active_name == old_name:
            self.data["active"] = new_name
        self.save()

    def delete(self, name: str) -> str:
        profiles = self.data["profiles"]
        if name not in profiles:
            raise ValueError("找不到要刪除的方案。")
        if len(profiles) <= 1:
            raise ValueError("至少必須保留一個方案。")
        del profiles[name]
        next_name = next(iter(profiles))
        if self.active_name == name:
            self.data["active"] = next_name
        self.save()
        return self.active_name

    def set_active(self, name: str) -> None:
        if name not in self.data["profiles"]:
            raise ValueError("找不到指定方案。")
        self.data["active"] = name
        self.save()

    def sync_calibration_point(
        self,
        platform: str,
        point_name: str,
        point: dict[str, Any],
    ) -> None:
        target_platforms = (
            ("cTrader", "GooeyTrade")
            if platform in {"GooeyTrade", "cTrader"}
            else ("MT5", "BYBIT MT5", "原版MT5")
            if platform in {"MT5", "BYBIT MT5", "原版MT5"}
            else (platform,)
        )
        for config in self.data["profiles"].values():
            for target_platform in target_platforms:
                config["platforms"].setdefault(
                    target_platform,
                    deepcopy(
                        DEFAULT_CONFIG["platforms"].get(
                            target_platform,
                            DEFAULT_CONFIG["platforms"]["MT5"],
                        )
                    ),
                )
                synced_point = deepcopy(point)
                if target_platform != "TradingView":
                    synced_point.pop("window_title", None)
                config["platforms"][target_platform].setdefault("points", {})[
                    point_name
                ] = synced_point
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self, initial_config: dict[str, Any]) -> dict[str, Any]:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                profiles = loaded.get("profiles")
                active = loaded.get("active")
                if (
                    isinstance(profiles, dict)
                    and profiles
                    and isinstance(active, str)
                    and active in profiles
                ):
                    return {
                        "active": active,
                        "profiles": {
                            str(name): _merge(
                                DEFAULT_CONFIG,
                                _migrate_config(config),
                            )
                            for name, config in profiles.items()
                            if isinstance(config, dict)
                        },
                    }
            except (OSError, json.JSONDecodeError):
                pass
        seeded = {
            "active": DEFAULT_PROFILE_NAME,
            "profiles": {DEFAULT_PROFILE_NAME: deepcopy(initial_config)},
        }
        self.data = seeded
        self.save()
        return seeded

    def _validate_new_name(self, name: str) -> None:
        if not name.strip():
            raise ValueError("方案名稱不能空白。")
        if name in self.data["profiles"]:
            raise ValueError("方案名稱已存在。")

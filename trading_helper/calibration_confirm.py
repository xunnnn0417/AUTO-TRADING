"""Explicit opt-in saving of individually previewed UIA calibration locations.

No trading-platform input is performed here. Writes only confirmed calibration
points in the test configuration and scheme profiles. Existing other points
are preserved. File writes are staged and rolled back on recoverable failure.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Iterable

from .calibration_scan import ScanReport
from .windows import WindowInfo


class CalibrationConfirmationError(ValueError):
    pass


def candidate_calibration_points(
    report: ScanReport,
    selected_keys: Iterable[str],
    visible_windows: Iterable[WindowInfo],
    original_window: WindowInfo,
    expected_pid: int,
    pid_for_window: Callable[[int], int],
) -> dict[str, dict]:
    """Convert explicitly confirmed rects to the existing window-relative format.

    Requiring a single exact platform process, and the smallest containing
    top-level window, avoids mapping MT5 popup controls onto the main window.
    """
    selected=tuple(selected_keys)
    if not selected or len(set(selected))!=len(selected):
        raise CalibrationConfirmationError("尚未選擇有效的確認項目")
    if report.warnings:
        raise CalibrationConfirmationError("掃描不完整或有警示；拒絕儲存，請重新掃描")
    declared={key for key,_ in report.targets}
    if any(key not in declared or key not in report.candidates for key in selected):
        raise CalibrationConfirmationError("包含未辨識或不屬於這次掃描的項目")
    if expected_pid<=0 or pid_for_window(original_window.handle)!=expected_pid:
        raise CalibrationConfirmationError("交易平台主視窗程序已變更；請重新掃描")
    windows=[w for w in visible_windows
             if w.width>0 and w.height>0 and pid_for_window(w.handle)==expected_pid]
    if not any(w.handle==original_window.handle and
               (w.left,w.top,w.right,w.bottom)==
               (original_window.left,original_window.top,original_window.right,original_window.bottom)
               for w in windows):
        raise CalibrationConfirmationError("原始掃描視窗已移動或尺寸改變；請重新掃描")
    results={}
    for key in selected:
        l,t,r,b=report.candidates[key].rect
        if r-l<8 or b-t<8:
            raise CalibrationConfirmationError(f"{key} 的候選外框無效")
        matches=[w for w in windows if w.left<=l<r<=w.right and w.top<=t<b<=w.bottom]
        if not matches:
            raise CalibrationConfirmationError(f"{key} 的候選不在同程序可見視窗內")
        # Post-entry scans explicitly identify the broker MAIN window for
        # the positions grid or the unique MODIFY popup for its edit fields.
        # When those top-level windows overlap, the previous generic
        # "smallest enclosing window" rule silently saved MAIN grid points
        # against the overlapping MODIFY popup. Honor the scanned HWND.
        stage_bound_keys={
            "positions_entry_price","position_order_lot","position_order_row",
            "position_sl_input","position_tp_input","position_modify_confirm",
        }
        if key in stage_bound_keys:
            exact=[w for w in matches if w.handle==original_window.handle]
            if len(exact)!=1:
                raise CalibrationConfirmationError(
                    f"{key} 不在當次掃描的指定平台視窗內"
                )
            win=exact[0]
        else:
            smallest=min(w.width*w.height for w in matches)
            nearest=[w for w in matches if w.width*w.height==smallest]
            if len(nearest)!=1:
                raise CalibrationConfirmationError(f"{key} 對應多個同大小視窗，拒絕猜測")
            win=nearest[0]
        x,y=(l+r)//2,(t+b)//2
        results[key]={
            "x":round((x-win.left)/win.width,6),
            "y":round((y-win.top)/win.height,6),
            "x_px":x-win.left,"y_px":y-win.top,
            "window_width":win.width,"window_height":win.height,
            "window_title":re.escape(win.title),
            "calibration_window_title":re.escape(win.title),
        }
    return results


def _replace_json_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(obj,ensure_ascii=False,indent=2).encode("utf-8")
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",prefix=".p2cal-",suffix=".tmp",
            dir=str(path.parent),delete=False
        ) as f:
            tmp=Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


def _restore_bytes(path: Path, blob: bytes | None) -> None:
    if blob is None:
        if path.exists():path.unlink()
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",prefix=".p2cal-rollback-",suffix=".tmp",
            dir=str(path.parent),delete=False
        ) as f:
            temp=Path(f.name)
            f.write(blob);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if temp and temp.exists():temp.unlink()


def save_confirmed_points(app, platform: str, points: dict[str,dict]) -> None:
    """Save only selected points to test config and associated saved profiles.

    Use one transaction, not a per-key loop of config/profile writes.
    If any disk write fails, restore the prior on-disk data and memory.
    """
    if not points:
        raise CalibrationConfirmationError("沒有勾選任何候選位置")
    if platform not in {"cTrader","MT5","BYBIT MT5","原版MT5"}:
        raise CalibrationConfirmationError("本流程只允許 cTrader、MT5 的人工確認校準")
    old_config=copy.deepcopy(app.store.data)
    old_profiles=copy.deepcopy(app.profiles.data)
    new_config=copy.deepcopy(old_config)
    new_profiles=copy.deepcopy(old_profiles)
    try:
        active=app.profiles.active_name
        if active not in new_profiles["profiles"]:
            raise CalibrationConfirmationError("目前使用中的方案不存在")
        new_config["platforms"][platform].setdefault("points",{}).update(copy.deepcopy(points))
        # Match the existing single-capture behaviour: active profile is the
        # current settings, then confirmed roles sync across profiles and
        # platform aliases. Unselected keys remain bit-for-bit unchanged.
        new_profiles["profiles"][active]=copy.deepcopy(new_config)
        aliases=(
            ("cTrader","GooeyTrade") if platform=="cTrader"
            else ("MT5","BYBIT MT5","原版MT5")
        )
        for profile in new_profiles["profiles"].values():
            for alias in aliases:
                if alias not in profile["platforms"]:
                    continue
                destination=profile["platforms"][alias].setdefault("points",{})
                for key, point in points.items():
                    cloned=copy.deepcopy(point)
                    if alias not in {"MT5","BYBIT MT5","原版MT5","TradingView"}:
                        cloned.pop("window_title",None)
                        cloned.pop("calibration_window_title",None)
                    destination[key]=cloned
        # The source config must reflect the active profile, as the existing
        # capture flow always reloads the saved active profile afterward.
        new_config=copy.deepcopy(new_profiles["profiles"][active])
        config_path=Path(app.store.path)
        profiles_path=Path(app.profiles.path)
        if config_path.resolve()==profiles_path.resolve():
            raise CalibrationConfirmationError("設定與方案不能使用同一檔案")
        backups={p:p.read_bytes() if p.exists() else None
                 for p in (config_path,profiles_path)}
        try:
            _replace_json_atomic(profiles_path,new_profiles)
            _replace_json_atomic(config_path,new_config)
        except Exception as exc:
            rollback_errors=[]
            for p, blob in backups.items():
                try:_restore_bytes(p,blob)
                except Exception as undo:rollback_errors.append(str(undo))
            if rollback_errors:
                raise RuntimeError(
                    "儲存失敗且備份還原失敗，請先保留檔案並人工檢查："+
                    "; ".join(rollback_errors)
                ) from exc
            raise
        app.profiles.data=new_profiles
        app.store.data=new_config
        app.automation.config=app.store.data
    except Exception:
        app.profiles.data=old_profiles
        app.store.data=old_config
        app.automation.config=app.store.data
        raise

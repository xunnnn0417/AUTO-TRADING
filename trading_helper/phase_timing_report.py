"""Local, privacy-minimized timing reports for complete workflow runs."""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from collections import deque
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
from pathlib import Path
import re
import threading
import time
import uuid


_ACTIVE_REPORT: ContextVar["PhaseTimingRun | None"] = ContextVar(
    "active_phase_timing_report", default=None,
)
_REPORT_FILE_LOCK = threading.Lock()
_PLATFORMS = {"cTrader", "MT5"}
_ROLES = {"internal", "external"}
_SCENARIOS = {
    "weekend:BTCUSD": "weekend_test",
    "weekend:ETHUSD": "weekend_test",
    "reentry:internal": "reentry_internal",
    "reentry:external": "reentry_external",
    "close:internal": "close_internal",
    "close:external": "close_external",
}


class PhaseTimingRun:
    """Keep a run's timing in memory and write it once at the end."""

    def __init__(self, workflow: str, metadata: dict):
        self.run_id = uuid.uuid4().hex
        self.workflow = workflow
        self.metadata = metadata
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self._started = time.perf_counter()
        self._sequence = 0
        self._stack: list[int] = []
        self.phases: list[dict] = []
        self.outcome = "running"
        self.failed_phase: str | None = None
        self.error_type: str | None = None
        self.error_summary: str | None = None

    @contextmanager
    def phase(
        self, name: str, *, platform: str | None = None,
        role: str | None = None,
    ):
        self._sequence += 1
        phase_id = self._sequence
        started = time.perf_counter()
        row = {
            "id": phase_id,
            "parent_id": self._stack[-1] if self._stack else None,
            "phase": name,
            "start_offset_ms": round((started - self._started) * 1000, 3),
            "duration_ms": None,
            "outcome": "running",
        }
        if platform in _PLATFORMS:
            row["platform"] = platform
        if role in _ROLES:
            row["role"] = role
        self.phases.append(row)
        self._stack.append(phase_id)
        try:
            yield
        except BaseException:
            row["outcome"] = "interrupted"
            if self.failed_phase is None:
                self.failed_phase = name
            raise
        else:
            row["outcome"] = "completed"
        finally:
            row["duration_ms"] = round(
                max(0.0, (time.perf_counter() - started) * 1000), 3,
            )
            if self._stack and self._stack[-1] == phase_id:
                self._stack.pop()

    def add_duration(
        self, name: str, started: float, duration_ms: float, *,
        platform: str | None = None, role: str | None = None,
        count: int | None = None,
    ) -> None:
        """Add an adapter's monotonic timing without persisting raw clocks."""
        self._sequence += 1
        row = {
            "id": self._sequence,
            "parent_id": self._stack[-1] if self._stack else None,
            "phase": name,
            "start_offset_ms": round((started - self._started) * 1000, 3),
            "duration_ms": round(max(0.0, float(duration_ms)), 3),
            "outcome": "completed",
        }
        if platform in _PLATFORMS:
            row["platform"] = platform
        if role in _ROLES:
            row["role"] = role
        if isinstance(count, int) and count >= 0:
            row["count"] = count
        self.phases.append(row)

    def finish(
        self, outcome: str, error: BaseException | None = None
    ) -> None:
        self.outcome = "completed" if outcome == "completed" else "interrupted"
        if error is not None:
            self.error_type = type(error).__name__[:80]
            self.error_summary = _safe_error_summary(error)

    def as_dict(self) -> dict:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "started_at_utc": self.started_at,
            "workflow": self.workflow,
            "scenario": self.metadata.get("scenario", "standard"),
            "platforms": self.metadata.get("platforms", {}),
            "fast_pair": self.metadata.get("fast_pair", False),
            "sync_sl_tp": self.metadata.get("sync_sl_tp", False),
            "draw_tv": self.metadata.get("draw_tv", False),
            "duration_ms": round(max(0.0, (time.perf_counter() - self._started) * 1000), 3),
            "outcome": self.outcome,
            "failed_phase": self.failed_phase,
            "error_type": self.error_type,
            "error_summary": self.error_summary,
            "phases": sorted(self.phases, key=lambda item: item["start_offset_ms"]),
        }


class LocalPhaseTimingStore:
    """Append one JSON object per completed or interrupted run."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, report: PhaseTimingRun) -> None:
        with _REPORT_FILE_LOCK:
            payload=report.as_dict()
            if payload["outcome"]=="completed" and self.path.exists():
                # Link a quick successful retry to its earlier interruption.
                # Local-only, uses the existing scrubbed reason, no account IDs.
                with self.path.open("rb") as source:
                    source.seek(max(0,self.path.stat().st_size-65536))
                    recent=deque(source.read().decode("utf-8",errors="replace").splitlines(),maxlen=20)
                for line in reversed(recent):
                    try:
                        old=json.loads(line)
                        same=all(old.get(key)==payload.get(key) for key in (
                            "workflow","scenario","platforms"
                        ))
                        gap=(datetime.fromisoformat(payload["started_at_utc"])-
                             datetime.fromisoformat(old["started_at_utc"])).total_seconds()
                    except (ValueError,KeyError,TypeError):
                        continue
                    if same and 0<=gap<=600:
                        if old.get("outcome")=="interrupted":
                            payload["successful_retry_after"]={key:old.get(key) for key in (
                                "run_id","failed_phase","error_summary"
                            )}
                        break
            line=json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")


def _safe_metadata(function, args, kwargs) -> dict:
    bound = inspect.signature(function).bind_partial(*args, **kwargs)
    values = bound.arguments
    metadata: dict = {}
    internal = values.get("internal_platform")
    external = values.get("external_platform")
    platforms = {}
    if internal in _PLATFORMS:
        platforms["internal"] = internal
    if external in _PLATFORMS:
        platforms["external"] = external
    if platforms:
        metadata["platforms"] = platforms

    scenario = values.get("scenario") or values.get("test_scenario")
    if scenario in _SCENARIOS:
        metadata["scenario"] = _SCENARIOS[scenario]
    elif values.get("test_skip_role") in _ROLES:
        metadata["scenario"] = "reentry_" + values["test_skip_role"]
    elif values.get("test_run_id"):
        metadata["scenario"] = "weekend_test"
    else:
        metadata["scenario"] = "standard"
    metadata["fast_pair"] = bool(values.get("fast_pair", False))
    metadata["sync_sl_tp"] = bool(values.get("sync_sl_tp", False))
    metadata["draw_tv"] = bool(values.get("draw_tv", False))
    return metadata


def _safe_error_summary(error: BaseException) -> str | None:
    """Keep actionable app errors while removing account and local secrets."""
    from .windows import AutomationError

    if not isinstance(error, AutomationError):
        return None
    text = str(error).strip()
    text = re.sub(r"https?://\S+", "[網址]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\b[A-Z]:\\[^\s,;，。]+", "[本機路徑]", text,
    )
    text = re.sub(
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[電子郵件]", text,
    )
    text = re.sub(r"(?<!\w)\d{4,}(?!\w)", "[數字]", text)
    text = " ".join(text.split())
    return text[:240] or None


def timed_operation(name: str):
    """Record a top-level flow and nested instrumented operations."""
    def decorate(function):
        @wraps(function)
        def wrapped(self, *args, **kwargs):
            active = _ACTIVE_REPORT.get()
            owns_report = active is None
            store = getattr(self, "phase_timing_store", None)
            if owns_report and store is None:
                return function(self, *args, **kwargs)
            bound = inspect.signature(function).bind_partial(
                self, *args, **kwargs,
            ).arguments
            if owns_report:
                active = PhaseTimingRun(
                    name, _safe_metadata(function, (self, *args), kwargs),
                )
                token = _ACTIVE_REPORT.set(active)
            else:
                token = None

            error: BaseException | None = None
            outcome = "completed"
            try:
                with active.phase(
                    name,
                    platform=bound.get("platform"),
                    role=bound.get("role"),
                ):
                    return function(self, *args, **kwargs)
            except BaseException as exc:
                outcome = "interrupted"
                error = exc
                raise
            finally:
                if owns_report:
                    active.finish(outcome, error)
                    try:
                        store.append(active)
                    except Exception:
                        # A diagnostics-file problem must never affect a trade.
                        log = getattr(self, "log", None)
                        if callable(log):
                            try:
                                log("本機流程計時報告寫入失敗；交易流程不受影響。")
                            except Exception:
                                pass
                    finally:
                        _ACTIVE_REPORT.reset(token)

        return wrapped
    return decorate


def timed_call(
    name: str, callback, *args, platform: str | None = None,
    role: str | None = None, **kwargs,
):
    report = _ACTIVE_REPORT.get()
    if report is None:
        return callback(*args, **kwargs)
    with report.phase(name, platform=platform, role=role):
        return callback(*args, **kwargs)


@contextmanager
def timed_phase(
    name: str, *, platform: str | None = None, role: str | None = None,
):
    """Measure a block when a workflow report is active; otherwise do nothing."""
    report = _ACTIVE_REPORT.get()
    if report is None:
        yield
        return
    with report.phase(name, platform=platform, role=role):
        yield


def record_submit_timings(port, platform: str, role: str) -> None:
    report = _ACTIVE_REPORT.get()
    if report is None:
        return
    timings = getattr(port, "submit_phase_timings", None)
    values = timings.get(role) if isinstance(timings, dict) else None
    if not isinstance(values, dict):
        return
    recorded = getattr(report, "_recorded_adapter_spans", None)
    if recorded is None:
        recorded = set()
        report._recorded_adapter_spans = recorded
    start = values.get("start")
    if not isinstance(start, (int, float)):
        return
    spans = (
        ("送單視窗定位", "start", "window_bound"),
        ("原生控制項清單讀取", "uia_inventory_started", "uia_inventory_returned"),
        ("送單前表單讀回", "form_check_started", "form_verified"),
        ("送單按鈕定位與驗證", "submit_target_started", "submit_target_verified"),
        ("送單點擊呼叫", "click_started", "click_returned"),
    )
    for label, first, last in spans:
        begin, end = values.get(first), values.get(last)
        if isinstance(begin, (int, float)) and isinstance(end, (int, float)) and end >= begin:
            marker = (role, label, begin, end)
            if marker in recorded:
                continue
            report.add_duration(
                label, begin, (end - begin) * 1000,
                platform=platform, role=role,
            )
            recorded.add(marker)
    polls = values.get("confirm_snapshot_count")
    total = values.get("confirm_snapshot_total_ms")
    if isinstance(total, (int, float)) and total >= 0:
        marker = (role, "確認輪詢", polls, total)
        if marker in recorded:
            return
        report.add_duration(
            "成交回讀－平台讀取累計",
            time.perf_counter() - total / 1000,
            total,
            platform=platform, role=role,
            count=polls if isinstance(polls, int) else None,
        )
        recorded.add(marker)

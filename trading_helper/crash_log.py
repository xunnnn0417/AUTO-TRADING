"""Keep otherwise-silent errors: pythonw has no console for Qt slot tracebacks.

Only local diagnostics are written (beside the other LAB diagnostics); nothing
is uploaded and no trading state is changed.
"""
from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

LOG_NAME = "unhandled-errors.log"
MAX_BYTES = 512 * 1024
# Only the real app (main.py) enables file output; offline tests that hit a
# recovery path must not write into the user's application-data folder.
_enabled = False


def log_path() -> Path:
    from .config import APP_DIR
    return Path(APP_DIR) / "diagnostics" / LOG_NAME


def record(context: str, exc_type=None, exc=None, tb=None, *, path: Path | None = None) -> None:
    """Append one traceback; never raises (it runs inside error handling)."""
    if path is None and not _enabled:
        return
    try:
        if exc_type is None:
            exc_type, exc, tb = sys.exc_info()
        target = path or log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > MAX_BYTES:
            target.replace(target.with_name(target.name + ".1"))
        text = "".join(traceback.format_exception(exc_type, exc, tb)) if exc_type else "(no exception)\n"
        stamp = datetime.now().isoformat(timespec="seconds")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {context}\n{text}\n")
    except Exception:
        pass


def install() -> None:
    """Record uncaught errors from the GUI thread (incl. Qt slots) and workers."""
    global _enabled
    _enabled = True
    previous_hook = sys.excepthook

    def excepthook(exc_type, exc, tb):
        record("unhandled", exc_type, exc, tb)
        if sys.stderr is not None:
            previous_hook(exc_type, exc, tb)

    previous_thread_hook = threading.excepthook

    def thread_hook(args):
        name = getattr(args.thread, "name", "?")
        record(f"thread {name}", args.exc_type, args.exc_value, args.exc_traceback)
        if sys.stderr is not None:
            previous_thread_hook(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook

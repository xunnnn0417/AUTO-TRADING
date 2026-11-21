"""Bounded local request evidence; never store news bodies or private settings."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading

_LOCK = threading.Lock()
MAX_LOG_BYTES = 2*1024*1024


class _ProbeHandler(RotatingFileHandler):
    def handleError(self, record):
        raise OSError('news probe write failed')


def append_probe(path: Path, row: dict) -> bool:
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = _ProbeHandler(path, maxBytes=MAX_LOG_BYTES, backupCount=4,
                                    encoding='utf-8', delay=True)
            try:
                handler.handle(logging.LogRecord('news-poll', logging.INFO, '', 0,
                    json.dumps(row, ensure_ascii=True, allow_nan=False), (), None))
            finally:
                handler.close()
        return True
    except (OSError, ValueError):
        return False

"""Structured JSON-lines logging: one log file per source, plus console echo."""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SourceLogger:
    """Writes JSON-lines events to a per-source log file and echoes to stderr."""

    def __init__(self, log_path: Path, source_id: str, on_event=None):
        self.source_id = source_id
        self._on_event = on_event  # optional callable(record) for live progress (GUI)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(log_path, "a", encoding="utf-8")

    def log(self, event: str, level: str = "info", **fields: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "source_id": self.source_id,
            "event": event,
            **fields,
        }
        self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()
        if self._on_event is not None:
            try:
                self._on_event(record)
            except Exception:
                pass  # progress listeners must never break the pipeline
        summary = " ".join(f"{k}={v}" for k, v in fields.items() if k != "traceback")
        print(f"[{level}] {event} {summary}".strip(), file=sys.stderr)

    def error(self, event: str, **fields: Any) -> None:
        self.log(event, level="error", **fields)

    @contextmanager
    def stage(self, name: str, **fields: Any):
        """Log stage start/end with elapsed seconds; re-raises on failure."""
        self.log(f"{name}.start", **fields)
        t0 = time.monotonic()
        try:
            yield
        except Exception as exc:
            self.error(f"{name}.failed", elapsed_s=round(time.monotonic() - t0, 2), error=str(exc))
            raise
        self.log(f"{name}.done", elapsed_s=round(time.monotonic() - t0, 2))

    def close(self) -> None:
        self._fh.close()

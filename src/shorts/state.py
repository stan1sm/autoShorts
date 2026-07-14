"""SQLite-backed dedup + processing state (idempotency and resumability)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_hash  TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    source_path  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
    processed_at TEXT
);
"""


class StateStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def is_done(self, source_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM sources WHERE source_hash = ?", (source_hash,)
        ).fetchone()
        return row is not None and row[0] == "done"

    def register(self, source_hash: str, source_id: str, source_path: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sources (source_hash, source_id, source_path) VALUES (?, ?, ?)",
            (source_hash, source_id, source_path),
        )
        self._conn.commit()

    def mark(self, source_hash: str, status: str) -> None:
        self._conn.execute(
            "UPDATE sources SET status = ?, processed_at = ? WHERE source_hash = ?",
            (status, datetime.now(timezone.utc).isoformat(), source_hash),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

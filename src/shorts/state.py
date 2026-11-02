"""SQLite-backed dedup + processing state (idempotency and resumability)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_hash  TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    source_path  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS hosted_media (
    clip_file  TEXT PRIMARY KEY,   -- output-relative path, e.g. "srcid/clips/x.mp4"
    hosted_url TEXT NOT NULL,
    hosted_at  TEXT NOT NULL,
    expires_at TEXT,               -- NULL for public_bucket mode
    file_hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id         TEXT NOT NULL,
    clip_file         TEXT NOT NULL,
    platform          TEXT NOT NULL,
    buffer_post_id    TEXT,
    buffer_channel_id TEXT NOT NULL,
    status            TEXT NOT NULL,  -- pending | scheduled | sent | failed
    scheduled_for     TEXT,
    created_at        TEXT NOT NULL,
    last_error        TEXT,
    attempt_count     INTEGER DEFAULT 0,
    UNIQUE(clip_file, platform)
);

CREATE TABLE IF NOT EXISTS buffer_channels (
    platform     TEXT PRIMARY KEY,
    channel_id   TEXT NOT NULL,
    channel_name TEXT,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class HostedMedia:
    clip_file: str
    hosted_url: str
    hosted_at: str
    expires_at: str | None
    file_hash: str


@dataclass
class PostRecord:
    id: int
    source_id: str
    clip_file: str
    platform: str
    buffer_post_id: str | None
    buffer_channel_id: str
    status: str
    scheduled_for: str | None
    created_at: str
    last_error: str | None
    attempt_count: int


class StateStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # --- sources (existing pipeline) ---

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
            (status, _utcnow(), source_hash),
        )
        self._conn.commit()

    # --- hosted media ---

    def get_hosted(self, clip_file: str) -> HostedMedia | None:
        row = self._conn.execute(
            "SELECT clip_file, hosted_url, hosted_at, expires_at, file_hash "
            "FROM hosted_media WHERE clip_file = ?",
            (clip_file,),
        ).fetchone()
        return HostedMedia(*row) if row else None

    def upsert_hosted(
        self, clip_file: str, hosted_url: str, expires_at: str | None, file_hash: str
    ) -> None:
        self._conn.execute(
            "INSERT INTO hosted_media (clip_file, hosted_url, hosted_at, expires_at, file_hash) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(clip_file) DO UPDATE SET "
            "hosted_url = excluded.hosted_url, hosted_at = excluded.hosted_at, "
            "expires_at = excluded.expires_at, file_hash = excluded.file_hash",
            (clip_file, hosted_url, _utcnow(), expires_at, file_hash),
        )
        self._conn.commit()

    def delete_hosted(self, clip_file: str) -> None:
        self._conn.execute("DELETE FROM hosted_media WHERE clip_file = ?", (clip_file,))
        self._conn.commit()

    def list_hosted(self) -> list[HostedMedia]:
        rows = self._conn.execute(
            "SELECT clip_file, hosted_url, hosted_at, expires_at, file_hash FROM hosted_media"
        ).fetchall()
        return [HostedMedia(*r) for r in rows]

    # --- posts ---

    _POST_COLS = (
        "id, source_id, clip_file, platform, buffer_post_id, buffer_channel_id, "
        "status, scheduled_for, created_at, last_error, attempt_count"
    )

    def get_post(self, clip_file: str, platform: str) -> PostRecord | None:
        row = self._conn.execute(
            f"SELECT {self._POST_COLS} FROM posts WHERE clip_file = ? AND platform = ?",
            (clip_file, platform),
        ).fetchone()
        return PostRecord(*row) if row else None

    def create_post_attempt(
        self, source_id: str, clip_file: str, platform: str, channel_id: str
    ) -> PostRecord:
        """Insert a 'pending' row (or return the existing one) for this clip+platform."""
        self._conn.execute(
            "INSERT OR IGNORE INTO posts "
            "(source_id, clip_file, platform, buffer_channel_id, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (source_id, clip_file, platform, channel_id, _utcnow()),
        )
        self._conn.commit()
        record = self.get_post(clip_file, platform)
        assert record is not None
        return record

    def mark_post_scheduled(
        self, clip_file: str, platform: str, buffer_post_id: str,
        status: str, scheduled_for: str | None,
    ) -> None:
        self._conn.execute(
            "UPDATE posts SET buffer_post_id = ?, status = ?, scheduled_for = ?, "
            "last_error = NULL, attempt_count = attempt_count + 1 "
            "WHERE clip_file = ? AND platform = ?",
            (buffer_post_id, status, scheduled_for, clip_file, platform),
        )
        self._conn.commit()

    def mark_post_failed(self, clip_file: str, platform: str, error: str) -> None:
        self._conn.execute(
            "UPDATE posts SET status = 'failed', last_error = ?, "
            "attempt_count = attempt_count + 1 WHERE clip_file = ? AND platform = ?",
            (error[:2000], clip_file, platform),
        )
        self._conn.commit()

    def list_posts(
        self, source_id: str | None = None, status: str | None = None
    ) -> list[PostRecord]:
        clauses, params = [], []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT {self._POST_COLS} FROM posts {where} ORDER BY id", params
        ).fetchall()
        return [PostRecord(*r) for r in rows]

    # --- buffer channels ---

    def get_channels(self) -> dict[str, str]:
        """platform -> channel_id from the cache (empty if never refreshed)."""
        rows = self._conn.execute("SELECT platform, channel_id FROM buffer_channels").fetchall()
        return {platform: channel_id for platform, channel_id in rows}

    def list_channels(self) -> list[tuple[str, str, str | None, str]]:
        return self._conn.execute(
            "SELECT platform, channel_id, channel_name, refreshed_at FROM buffer_channels"
        ).fetchall()

    def replace_channels(self, channels: dict[str, tuple[str, str | None]]) -> None:
        """channels: platform -> (channel_id, channel_name). Replaces the whole cache."""
        now = _utcnow()
        self._conn.execute("DELETE FROM buffer_channels")
        self._conn.executemany(
            "INSERT INTO buffer_channels (platform, channel_id, channel_name, refreshed_at) "
            "VALUES (?, ?, ?, ?)",
            [(p, cid, name, now) for p, (cid, name) in channels.items()],
        )
        self._conn.commit()

    # --- kv (small cached values, e.g. Buffer organization id) ---

    def get_value(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_value(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

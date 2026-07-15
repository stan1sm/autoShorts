"""HOST stage: upload manifest clips to object storage, write URLs back.

Idempotent: unchanged files are not re-transferred (hash compare against the
stored object), but signed URLs are re-issued on every run so a re-run always
leaves the manifest with a fresh, valid URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import AppConfig
from ..hosting import HostingError, get_backend
from ..manifest import load_manifest_dict, save_manifest_dict
from ..state import StateStore
from ..util import file_sha256


@dataclass
class HostResult:
    source_id: str
    uploaded: int = 0
    skipped: int = 0  # already hosted with identical content
    failed: list[str] = field(default_factory=list)


def clip_key(source_id: str, clip_file: str) -> str:
    """Canonical identifier for a clip in the state DB and object storage:
    '{source_id}/clips/<name>.mp4' (manifest paths are already source-relative)."""
    return f"{source_id}/{clip_file}"


def object_key(source_id: str, clip_file: str) -> str:
    """Deterministic storage key per spec: {source_id}/{clip_filename}."""
    return f"{source_id}/{Path(clip_file).name}"


def host_source(source_id: str, cfg: AppConfig, dry_run: bool = False) -> HostResult:
    out_dir = cfg.output.root_dir / source_id
    manifest = load_manifest_dict(out_dir)
    result = HostResult(source_id=source_id)
    state = StateStore(cfg.output.root_dir / ".state.db")
    backend = None if dry_run else get_backend(cfg.hosting)

    try:
        for clip in manifest.get("clips", []):
            local = out_dir / clip["file"]
            if not local.exists():
                result.failed.append(f"{clip['file']}: file missing on disk")
                continue
            key = clip_key(source_id, clip["file"])
            file_hash = file_sha256(local)
            cached = state.get_hosted(key)
            unchanged = cached is not None and cached.file_hash == file_hash

            if dry_run:
                result.skipped += 1 if unchanged else 0
                result.uploaded += 0 if unchanged else 1
                continue

            try:
                hosted = backend.upload(local, object_key(source_id, clip["file"]), file_hash)
            except HostingError as exc:
                result.failed.append(f"{clip['file']}: {exc}")
                continue

            state.upsert_hosted(key, hosted.url, hosted.expires_at, file_hash)
            clip["hosted_url"] = hosted.url
            clip["hosted_at"] = datetime.now(timezone.utc).isoformat()
            if hosted.expires_at:
                clip["hosted_expires_at"] = hosted.expires_at
            if hosted.uploaded:
                result.uploaded += 1
            else:
                result.skipped += 1

        if not dry_run:
            save_manifest_dict(manifest, out_dir)
    finally:
        state.close()
    return result


def cleanup_hosted(cfg: AppConfig, dry_run: bool = False) -> list[str]:
    """Delete hosted objects older than hosting.retention_days, unless a post
    for that clip is still pending. Returns the clip keys removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.hosting.retention_days)
    state = StateStore(cfg.output.root_dir / ".state.db")
    backend = None if dry_run else get_backend(cfg.hosting)
    removed: list[str] = []
    try:
        pending = {p.clip_file for p in state.list_posts(status="pending")}
        for media in state.list_hosted():
            hosted_at = datetime.fromisoformat(media.hosted_at)
            if hosted_at > cutoff or media.clip_file in pending:
                continue
            if not dry_run:
                source_id, _, clip_file = media.clip_file.partition("/")
                backend.delete(object_key(source_id, clip_file))
                state.delete_hosted(media.clip_file)
            removed.append(media.clip_file)
    finally:
        state.close()
    return removed

"""POST stage: create one Buffer post per clip per configured platform.

Idempotency: the state DB is checked before every mutation — a (clip,
platform) pair with a Buffer post ID is never posted again. Failed and
pending rows ARE retried on re-run, which is also how `posts retry-failed`
works. Transient API errors are retried inside BufferClient; MutationErrors
are permanent and mark the row failed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import AppConfig
from ..buffer.channels import resolve_channels
from ..buffer.client import BufferAPIError, BufferClient, BufferMutationError
from ..buffer.posting import build_post_input, immediate_times, spread_times
from ..manifest import load_manifest_dict, save_manifest_dict
from ..state import StateStore
from .host import clip_key


_SUPPORTED_PLATFORMS = ("youtube", "instagram", "tiktok")


@dataclass
class PostResult:
    source_id: str
    attempted: int = 0
    succeeded: int = 0
    skipped_duplicates: int = 0
    skipped_unhosted: int = 0
    skipped_deselected: int = 0  # clips excluded via per-clip platform choice
    failed: list[str] = field(default_factory=list)  # "clip/platform: error"
    dry_run_inputs: list[dict] = field(default_factory=list)


def _make_client(cfg: AppConfig) -> BufferClient:
    return BufferClient(
        max_requests_per_15min=cfg.posting.rate_limit.max_requests_per_15min,
        max_attempts=cfg.posting.retries.max_attempts,
        initial_backoff_seconds=cfg.posting.retries.initial_backoff_seconds,
    )


def _parse_schedule(schedule: dict[str, str] | None, now: datetime) -> dict[str, datetime]:
    """Parse {clip_file: "YYYY-MM-DDTHH:MM"} from the GUI. Naive times are the
    operator's local time (server and browser run on the same machine)."""
    parsed: dict[str, datetime] = {}
    for clip_file, raw in (schedule or {}).items():
        if not raw:
            continue
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()  # attach system-local timezone
        if dt <= now:
            raise RuntimeError(f"scheduled time for {clip_file} is in the past: {raw}")
        parsed[clip_file] = dt
    return parsed


def post_source(
    source_id: str,
    cfg: AppConfig,
    dry_run: bool = False,
    client: BufferClient | None = None,
    now: datetime | None = None,
    schedule: dict[str, str] | None = None,
    platforms: dict[str, list[str]] | None = None,
    platforms_exclusive: bool = False,
) -> PostResult:
    """platforms: per-clip platform choice {clip_file: [platform, ...]} from the
    GUI. A missing clip falls back to posting.platforms (or is skipped entirely
    when platforms_exclusive is set — used by retry-failed to touch only the
    exact (clip, platform) pairs that failed); an empty list skips the clip."""
    posting = cfg.posting
    if not posting.enabled:
        raise RuntimeError("posting.enabled is false in config")
    if posting.schedule_mode == "immediate" and posting.draft_only:
        raise RuntimeError(
            "schedule_mode=immediate makes no sense with draft_only=true — "
            "drafts are never auto-published; pick one"
        )
    overrides = platforms or {}
    for clip_file, plist in overrides.items():
        bad = [p for p in plist if p not in _SUPPORTED_PLATFORMS]
        if bad:
            raise RuntimeError(f"unsupported platform(s) for {clip_file}: {', '.join(bad)}")
    now = now or datetime.now(timezone.utc)
    chosen_times = _parse_schedule(schedule, now)

    def clip_platforms(clip: dict) -> list[str]:
        default = [] if platforms_exclusive else posting.platforms
        return overrides.get(clip["file"], default)

    out_dir = cfg.output.root_dir / source_id
    manifest = load_manifest_dict(out_dir)
    result = PostResult(source_id=source_id)
    state = StateStore(cfg.output.root_dir / ".state.db")
    owns_client = client is None

    try:
        clips = [c for c in manifest.get("clips", [])]
        postable = []
        for clip in clips:
            if not clip.get("hosted_url"):
                result.skipped_unhosted += 1
            elif not clip_platforms(clip):
                result.skipped_deselected += 1
            else:
                postable.append(clip)

        if not postable:
            return result

        # Only resolve channels for platforms actually used in this run.
        needed = [
            p for p in _SUPPORTED_PLATFORMS
            if any(p in clip_platforms(c) for c in postable)
        ]
        if dry_run:
            channels = {p: f"<{p}-channel>" for p in needed}
        else:
            if client is None:
                client = _make_client(cfg)
            channels = resolve_channels(state, lambda: client, needed, refresh=False)

        # Per-platform dueAt lists (None means Buffer's queue decides), sized to
        # the clips that actually target each platform and consumed in order.
        due_by_platform: dict[str, list[datetime | None]] = {}
        next_slot: dict[str, int] = {}
        for platform in needed:
            count = sum(1 for c in postable if platform in clip_platforms(c))
            if posting.schedule_mode == "spread":
                due_by_platform[platform] = list(spread_times(count, posting, now))
            elif posting.schedule_mode == "immediate":
                due_by_platform[platform] = list(immediate_times(count, now))
            else:
                due_by_platform[platform] = [None] * count
            next_slot[platform] = 0

        for clip in postable:
            key = clip_key(source_id, clip["file"])
            buffer_posts = clip.setdefault("buffer_posts", {})
            for platform in clip_platforms(clip):
                existing = state.get_post(key, platform)
                if existing and existing.buffer_post_id:
                    result.skipped_duplicates += 1
                    continue

                # Operator-picked time wins over the schedule_mode default.
                slot = next_slot[platform]
                next_slot[platform] += 1
                due_at = chosen_times.get(clip["file"]) or due_by_platform[platform][slot]
                post_input = build_post_input(
                    clip, platform, channels[platform], clip["hosted_url"], posting, due_at
                )
                result.attempted += 1

                if dry_run:
                    result.dry_run_inputs.append(
                        {"clip": clip["file"], "platform": platform,
                         "input": post_input.to_variables()["input"]}
                    )
                    continue

                state.create_post_attempt(source_id, key, platform, channels[platform])
                try:
                    post = client.create_post(post_input)
                except (BufferMutationError, BufferAPIError) as exc:
                    state.mark_post_failed(key, platform, str(exc))
                    result.failed.append(f"{clip['file']}/{platform}: {exc}")
                    continue

                status = "scheduled"
                state.mark_post_scheduled(key, platform, post.id, status, post.dueAt)
                buffer_posts[platform] = {
                    "post_id": post.id,
                    "status": "draft" if posting.draft_only else status,
                    "due_at": post.dueAt,
                }
                result.succeeded += 1

        if not dry_run:
            save_manifest_dict(manifest, out_dir)
    finally:
        state.close()
        if owns_client and client is not None:
            client.close()
    return result


def retry_failed(
    cfg: AppConfig, dry_run: bool = False, client: BufferClient | None = None
) -> list[PostResult]:
    """Retry exactly the (clip, platform) pairs that failed — nothing else, so
    platforms deselected at publish time are never resurrected by a retry."""
    state = StateStore(cfg.output.root_dir / ".state.db")
    try:
        failed = state.list_posts(status="failed")
    finally:
        state.close()
    by_source: dict[str, dict[str, list[str]]] = {}
    for p in failed:
        # State keys are "{source_id}/clips/x.mp4"; manifests use "clips/x.mp4".
        rel = p.clip_file.partition("/")[2]
        by_source.setdefault(p.source_id, {}).setdefault(rel, []).append(p.platform)
    return [
        post_source(sid, cfg, dry_run=dry_run, client=client,
                    platforms=by_source[sid], platforms_exclusive=True)
        for sid in sorted(by_source)
    ]


def format_dry_run(result: PostResult) -> str:
    lines = [f"DRY RUN — {result.attempted} post(s) would be created:"]
    for entry in result.dry_run_inputs:
        lines.append(f"\n--- {entry['clip']} -> {entry['platform']} ---")
        lines.append(json.dumps(entry["input"], indent=2, ensure_ascii=False))
    return "\n".join(lines)

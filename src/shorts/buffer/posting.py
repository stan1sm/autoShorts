"""Post composition (per-platform text + metadata) and schedule spreading.

Everything here is pure: no network, no clock reads — timestamps come in as
arguments — so it is unit-testable and deterministic.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import PostingConfig
from .schemas import (
    AssetInput,
    CreatePostInput,
    InstagramPostMetadataInput,
    PostInputMetaData,
    TikTokPostMetadataInput,
    VideoAssetInput,
    VideoMetadataInput,
    YoutubePostMetadataInput,
)

_TIKTOK_CAPTION_LIMIT = 2200


def _tags(clip: dict, platform: str) -> list[str]:
    return [str(t) for t in (clip.get("hashtags") or {}).get(platform, [])]


def compose_text(clip: dict, platform: str, cfg: PostingConfig) -> tuple[str, str | None]:
    """Return (post text, first_comment or None) for one clip on one platform.
    `clip` is a manifest clip entry (dict with title/description/hashtags)."""
    title = (clip.get("title") or "").strip()
    description = (clip.get("description") or "").strip()
    tags = _tags(clip, platform)

    if platform == "youtube":
        if cfg.youtube.ensure_shorts_tag and "#shorts" not in [t.lower() for t in tags]:
            tags.insert(0, "#shorts")
        parts = [p for p in (title, description, " ".join(tags)) if p]
        return "\n\n".join(parts), None

    if platform == "instagram":
        caption_parts = [p for p in (title, description) if p]
        tag_line = " ".join(tags)
        if cfg.instagram.hashtags_in_first_comment and tag_line:
            return "\n\n".join(caption_parts), tag_line
        if tag_line:
            caption_parts.append(tag_line)
        return "\n\n".join(caption_parts), None

    if platform == "tiktok":
        text = " ".join(p for p in (title, " ".join(tags)) if p)
        return text[:_TIKTOK_CAPTION_LIMIT], None

    raise ValueError(f"unsupported platform: {platform}")


def build_post_input(
    clip: dict,
    platform: str,
    channel_id: str,
    hosted_url: str,
    cfg: PostingConfig,
    due_at: datetime | None = None,
) -> CreatePostInput:
    """Assemble the full CreatePostInput for one clip on one platform."""
    text, first_comment = compose_text(clip, platform, cfg)

    video_meta = None
    if platform == "tiktok" and cfg.tiktok.thumbnail_offset_seconds is not None:
        video_meta = VideoMetadataInput(
            thumbnailOffset=int(cfg.tiktok.thumbnail_offset_seconds)
        )
    assets = [AssetInput(video=VideoAssetInput(url=hosted_url, metadata=video_meta))]

    metadata = None
    if platform == "instagram":
        metadata = PostInputMetaData(
            instagram=InstagramPostMetadataInput(
                type=cfg.instagram.post_type, firstComment=first_comment
            )
        )
    elif platform == "youtube":
        metadata = PostInputMetaData(
            youtube=YoutubePostMetadataInput(
                title=(clip.get("title") or "Short")[:100],
                categoryId=cfg.youtube.category_id,
                privacy=cfg.youtube.privacy,
                madeForKids=cfg.youtube.made_for_kids,
                notifySubscribers=cfg.youtube.notify_subscribers,
            )
        )
    elif platform == "tiktok":
        metadata = PostInputMetaData(tiktok=TikTokPostMetadataInput())

    return CreatePostInput(
        channelId=channel_id,
        text=text,
        assets=assets,
        mode="customScheduled" if due_at is not None else "addToQueue",
        dueAt=_iso_utc(due_at) if due_at is not None else None,
        saveToDraft=cfg.draft_only,
        metadata=metadata,
    )


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- spread scheduling ---

def _round_up_15(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    remainder = dt.minute % 15
    return dt if remainder == 0 else dt + timedelta(minutes=15 - remainder)


def _in_quiet_hours(dt: datetime, quiet: tuple[int, int]) -> bool:
    start, end = quiet
    if start == end:
        return False
    if start < end:
        return start <= dt.hour < end
    return dt.hour >= start or dt.hour < end  # wraps midnight


def _next_allowed(dt: datetime, quiet: tuple[int, int]) -> datetime:
    if not _in_quiet_hours(dt, quiet):
        return dt
    start, end = quiet
    exit_time = dt.replace(hour=end, minute=0, second=0, microsecond=0)
    if exit_time <= dt:  # quiet window wraps past midnight into the next day
        exit_time += timedelta(days=1)
    return exit_time


def spread_times(n: int, cfg: PostingConfig, now: datetime) -> list[datetime]:
    """Deterministic dueAt times for `n` clips of ONE source on ONE platform.

    All clips in a run share a source, so the effective gap between
    consecutive posts is max(min_gap_hours, same_source_gap_hours). Times are
    computed in the configured timezone (quiet hours are local), rounded to
    15 minutes, capped per local day, and returned as aware datetimes.
    """
    spread = cfg.spread
    tz = ZoneInfo(spread.timezone)
    gap = timedelta(hours=max(spread.min_gap_hours, spread.same_source_gap_hours))
    quiet = spread.quiet_hours

    cursor = _round_up_15(now.astimezone(tz) + timedelta(minutes=30))
    per_day: dict = {}
    times: list[datetime] = []
    while len(times) < n:
        cursor = _round_up_15(_next_allowed(cursor, quiet))
        day = cursor.date()
        if per_day.get(day, 0) >= spread.posts_per_day_per_platform:
            cursor = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
            continue
        times.append(cursor)
        per_day[day] = per_day.get(day, 0) + 1
        cursor += gap

    window_end = now.astimezone(tz) + timedelta(days=spread.window_days)
    if times and times[-1] > window_end:
        raise ValueError(
            f"cannot fit {n} posts in {spread.window_days} days with "
            f"{spread.posts_per_day_per_platform}/day and {gap} gaps — "
            "widen posting.spread.window_days or raise posts_per_day_per_platform"
        )
    return times


def immediate_times(n: int, now: datetime) -> list[datetime]:
    """All posts within the next 15 minutes, staggered by 2 minutes."""
    base = now.astimezone(timezone.utc) + timedelta(minutes=5)
    return [base + timedelta(minutes=2 * i) for i in range(n)]

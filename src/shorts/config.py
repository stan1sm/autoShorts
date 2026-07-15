"""Validated app configuration: YAML file + CLI overrides -> pydantic models."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


def load_env_file(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines into os.environ (already-set vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


class InputConfig(BaseModel):
    inbox_dir: Path = Path("./inbox")
    supported_formats: list[str] = ["mp4", "mov", "mkv", "webm"]
    min_source_duration_seconds: float = 180.0


class TranscriptionConfig(BaseModel):
    engine: Literal["faster-whisper", "openai", "groq"] = "faster-whisper"
    model: str = "large-v3"
    language: str = "auto"
    cache: bool = True


class ClipSelectionConfig(BaseModel):
    strategy: Literal["llm", "heuristic"] = "llm"
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    clips_per_source: int = Field(default=5, ge=1, le=20)
    min_clip_seconds: float = 20.0
    max_clip_seconds: float = 50.0
    min_gap_between_clips_seconds: float = 30.0
    pre_roll_seconds: float = 0.3
    post_roll_seconds: float = 0.5
    keywords: list[str] = []

    @field_validator("max_clip_seconds")
    @classmethod
    def _max_gte_min(cls, v: float, info) -> float:
        if "min_clip_seconds" in info.data and v < info.data["min_clip_seconds"]:
            raise ValueError("max_clip_seconds must be >= min_clip_seconds")
        return v


class CaptionsConfig(BaseModel):
    enabled: bool = True
    style: Literal["karaoke"] = "karaoke"
    font: str = "Inter-Bold"
    font_size: int = 72
    position: Literal["bottom_third", "middle", "top_third"] = "bottom_third"
    words_per_caption: int = Field(default=2, ge=1, le=4)
    stroke_width: int = 6
    highlight_color: str = "#FFE500"
    base_color: str = "#FFFFFF"
    animation: Literal["none", "pop"] = "pop"  # pop: caption scales in on appearance


class ZoomEffectConfig(BaseModel):
    # continuous: slow zoom across the whole clip; punch_in: hard cuts between
    # 1.0x and `intensity` at sentence boundaries.
    mode: Literal["none", "continuous", "punch_in"] = "none"
    intensity: float = Field(default=1.12, ge=1.01, le=1.5)


class EffectsConfig(BaseModel):
    zoom: ZoomEffectConfig = ZoomEffectConfig()


class AudioConfig(BaseModel):
    normalize_lufs: float = -14.0


class EncodingConfig(BaseModel):
    codec: Literal["h264"] = "h264"
    bitrate: str = "8M"
    fps: int = 30


class VideoConfig(BaseModel):
    output_resolution: tuple[int, int] = (1080, 1920)
    reframe_mode: Literal["center_crop_blur", "subject_tracking"] = "center_crop_blur"
    captions: CaptionsConfig = CaptionsConfig()
    effects: EffectsConfig = EffectsConfig()
    audio: AudioConfig = AudioConfig()
    encoding: EncodingConfig = EncodingConfig()


class MetadataConfig(BaseModel):
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    cta: str = ""


class OutputConfig(BaseModel):
    root_dir: Path = Path("./output")


class HostingConfig(BaseModel):
    backend: Literal["r2", "s3", "minio"] = "r2"
    bucket: str = "shorts-media"
    region: str = "auto"
    public_mode: Literal["signed_url", "public_bucket"] = "signed_url"
    # SigV4 presigned URLs (S3 and R2 alike) cap at 7 days — values above are rejected
    # so a post never silently outlives its URL. Use public_bucket for longer windows.
    signed_url_ttl_days: int = Field(default=7, ge=1, le=7)
    retention_days: int = 90
    endpoint_url: str | None = None  # explicit endpoint (minio); R2 derives from R2_ACCOUNT_ID
    public_base_url: str | None = None  # public_bucket mode: custom domain or r2.dev URL


class SpreadConfig(BaseModel):
    window_days: int = 7
    posts_per_day_per_platform: int = Field(default=2, ge=1)
    min_gap_hours: float = 4.0
    same_source_gap_hours: float = 12.0
    quiet_hours: tuple[int, int] = (0, 7)  # local [start, end) hour, no scheduling inside
    timezone: str = "Europe/Oslo"


class InstagramPostingConfig(BaseModel):
    post_type: Literal["reel", "post", "story"] = "reel"
    hashtags_in_first_comment: bool = False


class YouTubePostingConfig(BaseModel):
    ensure_shorts_tag: bool = True
    category_id: str = "24"  # YouTube category: 24 = Entertainment
    privacy: Literal["public", "unlisted", "private"] = "public"
    made_for_kids: bool = False
    notify_subscribers: bool = True


class TikTokPostingConfig(BaseModel):
    thumbnail_offset_seconds: float | None = None


class RetriesConfig(BaseModel):
    max_attempts: int = Field(default=5, ge=1)
    initial_backoff_seconds: float = 2.0


class RateLimitConfig(BaseModel):
    max_requests_per_15min: int = Field(default=30, ge=1)


class PostingConfig(BaseModel):
    enabled: bool = False
    draft_only: bool = True  # safety default: posts land in Buffer as drafts
    platforms: list[Literal["youtube", "instagram", "tiktok"]] = [
        "youtube", "instagram", "tiktok",
    ]
    schedule_mode: Literal["queue", "spread", "immediate"] = "queue"
    spread: SpreadConfig = SpreadConfig()
    instagram: InstagramPostingConfig = InstagramPostingConfig()
    youtube: YouTubePostingConfig = YouTubePostingConfig()
    tiktok: TikTokPostingConfig = TikTokPostingConfig()
    retries: RetriesConfig = RetriesConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()


class AppConfig(BaseModel):
    input: InputConfig = InputConfig()
    transcription: TranscriptionConfig = TranscriptionConfig()
    clip_selection: ClipSelectionConfig = ClipSelectionConfig()
    video: VideoConfig = VideoConfig()
    metadata: MetadataConfig = MetadataConfig()
    output: OutputConfig = OutputConfig()
    hosting: HostingConfig = HostingConfig()
    posting: PostingConfig = PostingConfig()


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> AppConfig:
    """Load config.yaml (if present) and apply dotted-key CLI overrides.

    Overrides use dotted paths, e.g. {"clip_selection.clips_per_source": 3}.
    Also loads .env from the working directory so credentials in it are
    visible to every stage (existing environment variables take precedence).
    """
    load_env_file()
    data: dict[str, Any] = {}
    if path is not None and path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        node = data
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return AppConfig.model_validate(data)

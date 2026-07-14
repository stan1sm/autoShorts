"""Validated app configuration: YAML file + CLI overrides -> pydantic models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


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
    audio: AudioConfig = AudioConfig()
    encoding: EncodingConfig = EncodingConfig()


class MetadataConfig(BaseModel):
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    cta: str = ""


class OutputConfig(BaseModel):
    root_dir: Path = Path("./output")


class AppConfig(BaseModel):
    input: InputConfig = InputConfig()
    transcription: TranscriptionConfig = TranscriptionConfig()
    clip_selection: ClipSelectionConfig = ClipSelectionConfig()
    video: VideoConfig = VideoConfig()
    metadata: MetadataConfig = MetadataConfig()
    output: OutputConfig = OutputConfig()


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> AppConfig:
    """Load config.yaml (if present) and apply dotted-key CLI overrides.

    Overrides use dotted paths, e.g. {"clip_selection.clips_per_source": 3}.
    """
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

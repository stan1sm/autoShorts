from pathlib import Path

import pytest
from pydantic import ValidationError

from shorts.config import AppConfig, load_config


def test_defaults_without_file(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.clip_selection.clips_per_source == 5
    assert cfg.video.output_resolution == (1080, 1920)
    assert cfg.transcription.engine == "faster-whisper"


def test_yaml_and_overrides(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text("clip_selection:\n  clips_per_source: 3\n", encoding="utf-8")
    cfg = load_config(p, {"clip_selection.strategy": "heuristic", "video.encoding.fps": 24})
    assert cfg.clip_selection.clips_per_source == 3
    assert cfg.clip_selection.strategy == "heuristic"
    assert cfg.video.encoding.fps == 24


def test_none_overrides_ignored(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.yaml", {"clip_selection.clips_per_source": None})
    assert cfg.clip_selection.clips_per_source == 5


def test_clips_per_source_capped():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"clip_selection": {"clips_per_source": 21}})


def test_max_clip_must_exceed_min():
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"clip_selection": {"min_clip_seconds": 30, "max_clip_seconds": 10}}
        )

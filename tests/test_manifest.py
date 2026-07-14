import json
from pathlib import Path

from shorts.ingest import SourceVideo
from shorts.manifest import make_clip_entry, write_manifest, write_source_info
from shorts.metadata import ClipMetadata
from shorts.select import ClipCandidate


def _source(tmp_path: Path) -> SourceVideo:
    return SourceVideo(
        path=tmp_path / "video.mp4",
        source_id="abc123def456",
        source_hash="abc123def456" + "0" * 52,
        duration_seconds=3600.0,
        original_input="./inbox/video.mp4",
    )


def test_manifest_schema(tmp_path: Path):
    cand = ClipCandidate(start=142.3, end=178.9, hook="hook", reason="why", score=0.87)
    meta = ClipMetadata(
        title="A title",
        description="A description.",
        hashtags={"tiktok": ["#a"], "instagram": ["#b"], "youtube": ["#shorts"]},
    )
    entry = make_clip_entry("clips/abc123def456_01_a-title.mp4", cand, meta)
    path = write_manifest(_source(tmp_path), [entry], tmp_path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source_id"] == "abc123def456"
    assert data["source_file"] == "./inbox/video.mp4"
    clip = data["clips"][0]
    assert clip["file"].startswith("clips/")
    assert clip["start_seconds"] == 142.3
    assert clip["duration"] == 36.6
    assert clip["hashtags"]["youtube"] == ["#shorts"]
    assert clip["selection_reason"] == "why"
    assert clip["score"] == 0.87


def test_source_info(tmp_path: Path):
    path = write_source_info(_source(tmp_path), tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source_id"] == "abc123def456"
    assert data["duration_seconds"] == 3600.0

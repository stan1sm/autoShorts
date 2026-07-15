"""manifest.json and source_info.json writers — the contract Buffer reads from."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .ingest import SourceVideo
from .metadata import ClipMetadata
from .select import ClipCandidate


@dataclass
class ClipEntry:
    file: str  # relative to the source's output dir, e.g. "clips/abc_01_slug.mp4"
    start_seconds: float
    end_seconds: float
    duration: float
    title: str
    description: str
    hashtags: dict[str, list[str]]
    selection_reason: str
    score: float


@dataclass
class Manifest:
    source_id: str
    source_file: str
    processed_at: str
    clips: list[ClipEntry] = field(default_factory=list)


def make_clip_entry(
    relative_file: str, candidate: ClipCandidate, metadata: ClipMetadata
) -> ClipEntry:
    return ClipEntry(
        file=relative_file,
        start_seconds=round(candidate.start, 3),
        end_seconds=round(candidate.end, 3),
        duration=round(candidate.duration, 3),
        title=metadata.title,
        description=metadata.description,
        hashtags=metadata.hashtags,
        selection_reason=candidate.reason,
        score=round(candidate.score, 3),
    )


def write_manifest(source: SourceVideo, clips: list[ClipEntry], out_dir: Path) -> Path:
    manifest = Manifest(
        source_id=source.source_id,
        source_file=source.original_input,
        processed_at=datetime.now(timezone.utc).isoformat(),
        clips=clips,
    )
    path = out_dir / "manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)
    return path


def load_manifest_dict(out_dir: Path) -> dict:
    """Read manifest.json as a plain dict (the HOST/POST stages annotate it
    with fields the ClipEntry dataclass doesn't know about)."""
    path = out_dir / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"no manifest.json in {out_dir} — run the pipeline first")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_manifest_dict(data: dict, out_dir: Path) -> Path:
    path = out_dir / "manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_source_info(source: SourceVideo, out_dir: Path) -> Path:
    info = {
        "source_id": source.source_id,
        "source_hash": source.source_hash,
        "source_file": str(source.path),
        "original_input": source.original_input,
        "duration_seconds": round(source.duration_seconds, 3),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    path = out_dir / "source_info.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return path

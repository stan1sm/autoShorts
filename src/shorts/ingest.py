"""Input resolution and validation: local files, folders, and URLs via yt-dlp."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import InputConfig
from .util import CommandError, ffprobe_info, file_sha256


class IngestError(ValueError):
    pass


@dataclass
class SourceVideo:
    path: Path
    source_id: str      # first 12 hex chars of the content hash
    source_hash: str    # full sha256
    duration_seconds: float
    original_input: str  # what the user passed (path or URL)


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def download_url(url: str, dest_dir: Path, progress_cb=None) -> Path:
    """Download a URL (YouTube, Twitch VOD, direct MP4) with yt-dlp; return the file path.

    progress_cb, if given, is called with a 0-100 percent as the download advances.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    template = str(dest_dir / "%(id)s.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", template,
        "--newline", "--progress",
        "--progress-template", "download:SHORTS_DL %(progress._percent_str)s",
        url,
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        m = re.search(r"SHORTS_DL\s+([\d.]+)\s*%", line)
        if m and progress_cb is not None:
            progress_cb(float(m.group(1)))
        else:
            tail.append(line.rstrip())
            del tail[:-20]
    proc.wait(timeout=3600)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, "\n".join(tail))

    candidates = sorted(dest_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise IngestError(f"yt-dlp reported success but no mp4 found in {dest_dir}")
    return candidates[0]


def validate_and_identify(
    path: Path, cfg: InputConfig, original_input: str, notify=None
) -> SourceVideo:
    """Check the file is a usable video and compute its content identity.

    notify, if given, is called as notify(event_name, percent_or_None) for progress.
    """
    if not path.exists():
        raise IngestError(f"file not found: {path}")
    if path.suffix.lstrip(".").lower() not in cfg.supported_formats:
        raise IngestError(f"unsupported format '{path.suffix}': expected one of {cfg.supported_formats}")

    info = ffprobe_info(path)
    streams = info.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise IngestError(f"no video stream in {path}")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise IngestError(f"no audio track in {path} (required for transcription)")

    duration = float(info.get("format", {}).get("duration", 0.0))
    if duration < cfg.min_source_duration_seconds:
        raise IngestError(
            f"source is {duration:.0f}s, below minimum useful duration "
            f"of {cfg.min_source_duration_seconds:.0f}s"
        )

    if notify is not None:
        notify("ingest.hashing", None)
    source_hash = file_sha256(path)
    return SourceVideo(
        path=path,
        source_id=source_hash[:12],
        source_hash=source_hash,
        duration_seconds=duration,
        original_input=original_input,
    )


def resolve_input(raw: str, cfg: InputConfig, notify=None) -> SourceVideo:
    """Resolve a CLI argument (local path or URL) into a validated SourceVideo.

    notify, if given, is called as notify(event_name, percent_or_None) for progress.
    """
    if _is_url(raw):
        if notify is not None:
            notify("ingest.downloading", 0.0)
        path = download_url(
            raw, cfg.inbox_dir / "_downloads",
            progress_cb=(lambda pct: notify("ingest.downloading", pct)) if notify else None,
        )
    else:
        path = Path(raw)
    if notify is not None:
        notify("ingest.validating", None)
    return validate_and_identify(path, cfg, original_input=raw, notify=notify)


def scan_folder(folder: Path, cfg: InputConfig) -> list[Path]:
    """List candidate video files in a folder (non-recursive), skipping downloads dir."""
    if not folder.is_dir():
        raise IngestError(f"not a directory: {folder}")
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lstrip(".").lower() in cfg.supported_formats
    )

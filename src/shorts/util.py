"""Small shared helpers: subprocess wrapper, ffprobe, hashing, slugs."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


class CommandError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"command failed ({returncode}): {' '.join(cmd[:4])}...\n{stderr[-2000:]}"
        )


def run_command(cmd: list[str], timeout: float | None = None) -> str:
    """Run a subprocess, return stdout, raise CommandError on failure."""
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr or "")
    return proc.stdout


def ffprobe_info(path: Path) -> dict:
    """Return ffprobe format+streams JSON for a media file."""
    out = run_command(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
    )
    return json.loads(out)


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def slugify(text: str, max_length: int = 40) -> str:
    """Filesystem-safe kebab-case slug from arbitrary text."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0] or slug[:max_length]
    return slug or "clip"

"""HOST stage with an in-memory backend: write-back, idempotency, cleanup."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shorts.config import AppConfig
from shorts.hosting.base import HostedObject, HostingBackend
from shorts.stages import host as host_stage
from shorts.stages.host import cleanup_hosted, host_source
from shorts.state import StateStore

SOURCE_ID = "src1"


class FakeBackend(HostingBackend):
    def __init__(self):
        self.objects: dict[str, str] = {}  # key -> hash
        self.uploads = 0

    def upload(self, local_path: Path, key: str, file_hash: str) -> HostedObject:
        uploaded = self.objects.get(key) != file_hash
        if uploaded:
            self.objects[key] = file_hash
            self.uploads += 1
        url, expires_at = self.url_for(key)
        return HostedObject(key=key, url=url, expires_at=expires_at,
                            file_hash=file_hash, uploaded=uploaded)

    def url_for(self, key: str):
        return f"https://fake.example/{key}", None

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def cfg(tmp_path) -> AppConfig:
    config = AppConfig.model_validate({"output": {"root_dir": str(tmp_path)}})
    out_dir = tmp_path / SOURCE_ID / "clips"
    out_dir.mkdir(parents=True)
    clips = []
    for i in (1, 2):
        name = f"clips/{SOURCE_ID}_{i:02d}_x.mp4"
        (tmp_path / SOURCE_ID / name).write_bytes(b"video-bytes-%d" % i)
        clips.append({"file": name, "title": f"Clip {i}", "description": "",
                      "hashtags": {}})
    manifest = {"source_id": SOURCE_ID, "source_file": "in.mp4",
                "processed_at": "2026-07-15T00:00:00+00:00", "clips": clips}
    (tmp_path / SOURCE_ID / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return config


@pytest.fixture
def backend(monkeypatch) -> FakeBackend:
    fake = FakeBackend()
    monkeypatch.setattr(host_stage, "get_backend", lambda _cfg: fake)
    return fake


def test_host_uploads_and_writes_back(cfg, backend):
    result = host_source(SOURCE_ID, cfg)
    assert result.uploaded == 2 and result.failed == []

    manifest = json.loads((cfg.output.root_dir / SOURCE_ID / "manifest.json").read_text())
    for clip in manifest["clips"]:
        assert clip["hosted_url"].startswith("https://fake.example/")
        assert clip["hosted_at"]


def test_host_rerun_skips_unchanged_files(cfg, backend):
    host_source(SOURCE_ID, cfg)
    result = host_source(SOURCE_ID, cfg)
    assert result.uploaded == 0 and result.skipped == 2
    assert backend.uploads == 2  # nothing re-transferred


def test_host_reuploads_changed_file(cfg, backend):
    host_source(SOURCE_ID, cfg)
    clip_path = cfg.output.root_dir / SOURCE_ID / f"clips/{SOURCE_ID}_01_x.mp4"
    clip_path.write_bytes(b"different-bytes")
    result = host_source(SOURCE_ID, cfg)
    assert result.uploaded == 1 and result.skipped == 1


def test_missing_clip_file_is_reported(cfg, backend):
    (cfg.output.root_dir / SOURCE_ID / f"clips/{SOURCE_ID}_01_x.mp4").unlink()
    result = host_source(SOURCE_ID, cfg)
    assert result.uploaded == 1
    assert len(result.failed) == 1 and "missing" in result.failed[0]


def test_cleanup_removes_only_old_clips_without_pending_posts(cfg, backend):
    host_source(SOURCE_ID, cfg)

    # Age one clip past retention; give the other a pending post.
    state = StateStore(cfg.output.root_dir / ".state.db")
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    key1 = f"{SOURCE_ID}/clips/{SOURCE_ID}_01_x.mp4"
    key2 = f"{SOURCE_ID}/clips/{SOURCE_ID}_02_x.mp4"
    state._conn.execute("UPDATE hosted_media SET hosted_at = ?", (old,))
    state._conn.commit()
    state.create_post_attempt(SOURCE_ID, key2, "youtube", "ch_yt")
    state.close()

    removed = cleanup_hosted(cfg)
    assert removed == [key1]
    assert f"{SOURCE_ID}/{SOURCE_ID}_01_x.mp4" not in backend.objects
    assert f"{SOURCE_ID}/{SOURCE_ID}_02_x.mp4" in backend.objects

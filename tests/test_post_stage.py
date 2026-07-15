"""POST stage end-to-end against a mocked Buffer GraphQL endpoint."""

import json

import pytest

from shorts.config import AppConfig
from shorts.buffer.client import BufferClient
from shorts.stages.post import post_source, retry_failed

SOURCE_ID = "src1"


class FakeResponse:
    def __init__(self, data: dict, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.headers: dict = {}
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeBufferHttp:
    """Routes GraphQL operations by query text; records createPost inputs."""

    def __init__(self, fail_platforms: set[str] | None = None):
        self.create_post_inputs: list[dict] = []
        self.fail_platforms = fail_platforms or set()
        self._post_counter = 0

    def post(self, url, json=None, headers=None):  # noqa: A002 - httpx signature
        query = json["query"]
        if "organizations" in query:
            return FakeResponse({"data": {"account": {
                "organizations": [{"id": "org_1", "name": "Me"}],
            }}})
        if "channels(" in query:
            return FakeResponse({"data": {"channels": [
                {"id": "ch_yt", "service": "youtube", "name": "yt", "displayName": "YT"},
                {"id": "ch_ig", "service": "instagram", "name": "ig", "displayName": "IG"},
                {"id": "ch_tt", "service": "tiktok", "name": "tt", "displayName": "TT"},
            ]}})
        if "createPost" in query:
            post_input = json["variables"]["input"]
            self.create_post_inputs.append(post_input)
            platform = {"ch_yt": "youtube", "ch_ig": "instagram", "ch_tt": "tiktok"}[
                post_input["channelId"]
            ]
            if platform in self.fail_platforms:
                return FakeResponse({"data": {"createPost": {
                    "message": "validation failed: bad caption", "code": "VALIDATION",
                }}})
            self._post_counter += 1
            return FakeResponse({"data": {"createPost": {"post": {
                "id": f"post_{self._post_counter}", "status": "draft", "dueAt": None,
            }}}})
        raise AssertionError(f"unexpected query: {query[:80]}")

    def close(self):
        pass


@pytest.fixture
def cfg(tmp_path) -> AppConfig:
    config = AppConfig.model_validate({
        "output": {"root_dir": str(tmp_path)},
        "posting": {"enabled": True},
    })
    out_dir = tmp_path / SOURCE_ID
    out_dir.mkdir()
    manifest = {
        "source_id": SOURCE_ID,
        "source_file": "in.mp4",
        "processed_at": "2026-07-15T00:00:00+00:00",
        "clips": [
            {
                "file": f"clips/{SOURCE_ID}_{i:02d}_x.mp4",
                "title": f"Clip {i}",
                "description": "Desc.",
                "hashtags": {"youtube": ["#shorts"], "instagram": ["#reels"], "tiktok": ["#fyp"]},
                "hosted_url": f"https://media.example/{SOURCE_ID}_{i:02d}.mp4",
            }
            for i in (1, 2)
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return config


def _client(fake_http: FakeBufferHttp) -> BufferClient:
    client = BufferClient(api_key="test-key", http_client=fake_http, initial_backoff_seconds=0)
    client._sleep = lambda _s: None
    return client


def test_post_stage_end_to_end(cfg):
    fake = FakeBufferHttp()
    result = post_source(SOURCE_ID, cfg, client=_client(fake))

    assert result.succeeded == 6  # 2 clips x 3 platforms
    assert result.failed == []
    assert len(fake.create_post_inputs) == 6
    assert all(i["saveToDraft"] is True for i in fake.create_post_inputs)
    assert all(i["mode"] == "addToQueue" for i in fake.create_post_inputs)

    manifest = json.loads((cfg.output.root_dir / SOURCE_ID / "manifest.json").read_text())
    for clip in manifest["clips"]:
        assert set(clip["buffer_posts"]) == {"youtube", "instagram", "tiktok"}
        assert all(p["post_id"] for p in clip["buffer_posts"].values())


def test_post_stage_is_idempotent(cfg):
    fake = FakeBufferHttp()
    post_source(SOURCE_ID, cfg, client=_client(fake))
    calls_after_first = len(fake.create_post_inputs)

    second = post_source(SOURCE_ID, cfg, client=_client(fake))
    assert len(fake.create_post_inputs) == calls_after_first  # no new mutations
    assert second.succeeded == 0
    assert second.skipped_duplicates == 6


def test_mutation_error_marks_failed_and_retry_recovers(cfg):
    fake = FakeBufferHttp(fail_platforms={"tiktok"})
    first = post_source(SOURCE_ID, cfg, client=_client(fake))
    assert first.succeeded == 4
    assert len(first.failed) == 2
    assert all("tiktok" in f for f in first.failed)

    fake.fail_platforms = set()
    calls_before_retry = len(fake.create_post_inputs)
    results = retry_failed(cfg, client=_client(fake))
    assert len(results) == 1
    assert results[0].succeeded == 2  # only the two failed tiktok posts retried
    assert results[0].skipped_duplicates == 4
    assert len(fake.create_post_inputs) == calls_before_retry + 2


def test_unhosted_clips_are_skipped(cfg):
    manifest_path = cfg.output.root_dir / SOURCE_ID / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["clips"][0]["hosted_url"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fake = FakeBufferHttp()
    result = post_source(SOURCE_ID, cfg, client=_client(fake))
    assert result.skipped_unhosted == 1
    assert result.succeeded == 3  # one clip x 3 platforms


def test_dry_run_makes_no_api_calls(cfg):
    result = post_source(SOURCE_ID, cfg, dry_run=True)
    assert result.attempted == 6
    assert len(result.dry_run_inputs) == 6
    assert result.succeeded == 0


def test_immediate_plus_draft_only_is_rejected(cfg):
    cfg.posting.schedule_mode = "immediate"
    with pytest.raises(RuntimeError, match="draft_only"):
        post_source(SOURCE_ID, cfg, dry_run=True)


def test_operator_schedule_overrides_queue_mode(cfg):
    from datetime import datetime, timezone

    clip_file = f"clips/{SOURCE_ID}_01_x.mp4"
    picked = "2030-08-01T14:00"  # naive local time, as the GUI sends it
    fake = FakeBufferHttp()
    post_source(SOURCE_ID, cfg, client=_client(fake), schedule={clip_file: picked})

    expected = (datetime.fromisoformat(picked).astimezone()
                .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    by_clip = {}
    for i in fake.create_post_inputs:
        by_clip.setdefault(i["assets"][0]["video"]["url"], []).append(i)
    scheduled = [i for i in fake.create_post_inputs if i.get("dueAt")]
    queued = [i for i in fake.create_post_inputs if not i.get("dueAt")]
    assert len(scheduled) == 3  # clip 1 on all three platforms
    assert all(i["mode"] == "customScheduled" and i["dueAt"] == expected for i in scheduled)
    assert len(queued) == 3 and all(i["mode"] == "addToQueue" for i in queued)


def test_schedule_in_the_past_is_rejected(cfg):
    with pytest.raises(RuntimeError, match="in the past"):
        post_source(SOURCE_ID, cfg, dry_run=True,
                    schedule={f"clips/{SOURCE_ID}_01_x.mp4": "2020-01-01T10:00"})

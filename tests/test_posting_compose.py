"""Per-platform post composition — pure functions, no network."""

from datetime import UTC, datetime

from shorts.buffer.posting import build_post_input, compose_text
from shorts.config import PostingConfig


def _clip(**overrides) -> dict:
    clip = {
        "file": "clips/src_01_test.mp4",
        "title": "Why the sky is blue",
        "description": "A quick explainer. Follow for more.",
        "hashtags": {
            "youtube": ["#science", "#space"],
            "instagram": ["#reels", "#science", "#space"],
            "tiktok": ["#fyp", "#science", "#space", "#learn"],
        },
    }
    clip.update(overrides)
    return clip


def test_youtube_text_adds_missing_shorts_tag():
    text, first_comment = compose_text(_clip(), "youtube", PostingConfig())
    assert text == (
        "Why the sky is blue\n\nA quick explainer. Follow for more.\n\n"
        "#shorts #science #space"
    )
    assert first_comment is None


def test_youtube_text_keeps_existing_shorts_tag():
    clip = _clip(hashtags={"youtube": ["#Shorts", "#science"]})
    text, _ = compose_text(clip, "youtube", PostingConfig())
    assert text.count("#shorts") + text.count("#Shorts") == 1


def test_instagram_hashtags_in_caption_by_default():
    text, first_comment = compose_text(_clip(), "instagram", PostingConfig())
    assert "#reels #science #space" in text
    assert first_comment is None


def test_instagram_first_comment_mode():
    cfg = PostingConfig.model_validate(
        {"instagram": {"hashtags_in_first_comment": True}}
    )
    text, first_comment = compose_text(_clip(), "instagram", cfg)
    assert "#reels" not in text
    assert first_comment == "#reels #science #space"


def test_tiktok_text_is_title_plus_tags_and_capped():
    text, _ = compose_text(_clip(), "tiktok", PostingConfig())
    assert text == "Why the sky is blue #fyp #science #space #learn"
    long_clip = _clip(title="x" * 3000)
    text, _ = compose_text(long_clip, "tiktok", PostingConfig())
    assert len(text) <= 2200


def test_build_post_input_queue_mode_draft():
    cfg = PostingConfig()  # draft_only defaults to True
    post_input = build_post_input(_clip(), "instagram", "ch_ig", "https://x/v.mp4", cfg)
    variables = post_input.to_variables()["input"]
    assert variables["channelId"] == "ch_ig"
    assert variables["mode"] == "addToQueue"
    assert "dueAt" not in variables
    assert variables["saveToDraft"] is True
    assert variables["assets"] == [{"video": {"url": "https://x/v.mp4"}}]
    assert variables["metadata"]["instagram"]["type"] == "reel"


def test_build_post_input_custom_scheduled_and_youtube_metadata():
    cfg = PostingConfig.model_validate({"draft_only": False})
    due = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)
    post_input = build_post_input(_clip(), "youtube", "ch_yt", "https://x/v.mp4", cfg, due)
    variables = post_input.to_variables()["input"]
    assert variables["mode"] == "customScheduled"
    assert variables["dueAt"] == "2026-08-01T12:30:00.000Z"
    assert variables["saveToDraft"] is False
    assert variables["metadata"]["youtube"]["title"] == "Why the sky is blue"


def test_build_post_input_tiktok_thumbnail_offset():
    cfg = PostingConfig.model_validate({"tiktok": {"thumbnail_offset_seconds": 1.5}})
    post_input = build_post_input(_clip(), "tiktok", "ch_tt", "https://x/v.mp4", cfg)
    variables = post_input.to_variables()["input"]
    assert variables["assets"][0]["video"]["metadata"]["thumbnailOffset"] == 1

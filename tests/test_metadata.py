from shorts.config import MetadataConfig
from shorts.llm import LLMResponse
from shorts.metadata import generate_metadata
from shorts.select import ClipCandidate

CAND = ClipCandidate(start=10, end=30, hook="Big reveal", reason="r", score=0.9)


class FakeProvider:
    def __init__(self, text):
        self.text = text

    def complete(self, system, user, max_tokens=1024):
        return LLMResponse(self.text, 1, 1, "m", "fake")


def test_fallback_without_provider(transcript):
    meta, resp = generate_metadata(CAND, transcript, MetadataConfig(cta="Follow."), None)
    assert resp is None
    assert meta.title == "Big reveal" and meta.description.endswith("Follow.")
    assert "#shorts" in meta.hashtags["youtube"]


def test_llm_metadata_forces_shorts_tag_and_truncates_title(transcript):
    text = '{"title": "%s", "description": "d", "hashtags": {"youtube": ["#x"], "tiktok": ["#t"]}}' % ("T" * 100)
    meta, resp = generate_metadata(CAND, transcript, MetadataConfig(), FakeProvider(text))
    assert resp is not None
    assert len(meta.title) == 60
    assert meta.hashtags["youtube"] == ["#shorts", "#x"]
    assert meta.hashtags["instagram"] == []

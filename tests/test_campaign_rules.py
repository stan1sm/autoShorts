"""Campaign rules must reach both LLM prompts verbatim (and only when set)."""

from shorts.config import ClipSelectionConfig, MetadataConfig
from shorts.metadata import generate_metadata
from shorts.select import ClipCandidate, llm_select

RULES = (
    "Lunghezza minima del video: 15 secondi.\n"
    'Inserire come CTA: "Guarda l\'episodio completo di 75.25 Lab su Youtube"\n'
    "HASHTAG OBBLIGATORI: #7525lab #hyblue\n"
    "TAG Instagram: @75.25_lab_podcast — TikTok: @hyblue.longevity"
)


class CaptureProvider:
    """Stub LLM: records the prompts, returns a canned valid response."""

    def __init__(self, text: str):
        self.text = text
        self.system = None
        self.prompt = None

    def complete(self, system: str, prompt: str, max_tokens: int = 1024):
        self.system, self.prompt = system, prompt

        class R:
            text = self.text
            provider = "stub"
            model = "stub"
            input_tokens = 0
            output_tokens = 0

        return R()


def test_select_prompt_includes_rules(transcript):
    provider = CaptureProvider('[{"start": 10, "end": 40, "score": 0.9}]')
    llm_select(transcript, ClipSelectionConfig(), provider, campaign_rules=RULES)
    assert "CAMPAIGN RULES" in provider.prompt
    assert "Lunghezza minima del video: 15 secondi." in provider.prompt
    assert "#7525lab" in provider.prompt


def test_select_prompt_omits_block_without_rules(transcript):
    provider = CaptureProvider('[{"start": 10, "end": 40}]')
    llm_select(transcript, ClipSelectionConfig(), provider)
    assert "CAMPAIGN RULES" not in provider.prompt

    # Whitespace-only rules are treated as unset.
    llm_select(transcript, ClipSelectionConfig(), provider, campaign_rules="  \n ")
    assert "CAMPAIGN RULES" not in provider.prompt


def test_metadata_prompt_includes_rules(transcript):
    provider = CaptureProvider(
        '{"title": "T", "description": "D", "hashtags": {"youtube": ["#shorts"]}}'
    )
    cand = ClipCandidate(start=10.0, end=40.0, hook="h", reason="r", score=0.9)
    generate_metadata(cand, transcript, MetadataConfig(), provider, campaign_rules=RULES)
    assert "CAMPAIGN RULES" in provider.prompt
    assert "@hyblue.longevity" in provider.prompt
    # Mentions survive the hashtag sanitizer downstream of the prompt contract.
    assert "@" in provider.prompt


def test_metadata_prompt_omits_block_without_rules(transcript):
    provider = CaptureProvider(
        '{"title": "T", "description": "D", "hashtags": {"youtube": ["#shorts"]}}'
    )
    cand = ClipCandidate(start=10.0, end=40.0, hook="h", reason="r", score=0.9)
    generate_metadata(cand, transcript, MetadataConfig(), provider)
    assert "CAMPAIGN RULES" not in provider.prompt


def test_metadata_mentions_pass_through(transcript):
    """@mentions returned by the LLM land in the per-platform hashtag lists."""
    provider = CaptureProvider(
        '{"title": "T", "description": "D", "hashtags": {'
        '"instagram": ["#7525lab", "@75.25_lab_podcast"],'
        '"tiktok": ["#7525lab", "@hyblue.longevity"],'
        '"youtube": ["#shorts"]}}'
    )
    cand = ClipCandidate(start=10.0, end=40.0, hook="h", reason="r", score=0.9)
    meta, _ = generate_metadata(cand, transcript, MetadataConfig(), provider,
                                campaign_rules=RULES)
    assert "@75.25_lab_podcast" in meta.hashtags["instagram"]
    assert "@hyblue.longevity" in meta.hashtags["tiktok"]

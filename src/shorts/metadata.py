"""Per-clip metadata (title, description, per-platform hashtags) via LLM,
with a deterministic fallback when no provider is available."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import MetadataConfig
from .llm import LLMProvider, LLMResponse, extract_json
from .select import ClipCandidate
from .transcribe import Transcript

_SYSTEM_PROMPT = """You write titles, descriptions, and hashtags for short-form video clips.
Rules:
- Title: <=60 chars, hook-forward, specific, no clickbait fluff, no emoji spam.
- Description: 1-2 sentences of real context.
- Hashtags: mix broad and niche. TikTok 8-10, Instagram 3-5, YouTube 2-3 plus #shorts.
Respond ONLY with a JSON object, no prose."""

_USER_PROMPT = """Write metadata for this clip.

Clip hook: {hook}
Why it was selected: {reason}

Clip transcript:
{text}

{cta_line}

Return a JSON object with exactly these keys:
- "title": string (<=60 chars)
- "description": string (1-2 sentences{cta_note})
- "hashtags": object with keys "tiktok", "instagram", "youtube", each a JSON array
  of hashtag strings starting with "#". The youtube list must include "#shorts"."""


@dataclass
class ClipMetadata:
    title: str
    description: str
    hashtags: dict[str, list[str]] = field(default_factory=dict)


def _fallback_metadata(candidate: ClipCandidate, cta: str) -> ClipMetadata:
    title = (candidate.hook or "Clip")[:60]
    description = candidate.hook or ""
    if cta:
        description = f"{description} {cta}".strip()
    return ClipMetadata(
        title=title,
        description=description,
        hashtags={
            "tiktok": ["#fyp", "#viral", "#clips"],
            "instagram": ["#reels", "#clips"],
            "youtube": ["#shorts"],
        },
    )


def generate_metadata(
    candidate: ClipCandidate,
    transcript: Transcript,
    cfg: MetadataConfig,
    provider: LLMProvider | None,
) -> tuple[ClipMetadata, LLMResponse | None]:
    """Returns (metadata, LLMResponse or None) — the response is for cost logging."""
    if provider is None:
        return _fallback_metadata(candidate, cfg.cta), None

    words = transcript.words_between(candidate.start, candidate.end)
    text = " ".join(w.word for w in words) or candidate.hook
    prompt = _USER_PROMPT.format(
        hook=candidate.hook or "(none)",
        reason=candidate.reason or "(none)",
        text=text[:4000],
        cta_line=f'End the description with this call to action: "{cfg.cta}"' if cfg.cta else "",
        cta_note=", ending with the given call to action" if cfg.cta else "",
    )
    response = provider.complete(_SYSTEM_PROMPT, prompt, max_tokens=1024)
    data = extract_json(response.text)
    if not isinstance(data, dict):
        raise ValueError("metadata LLM response was not a JSON object")

    hashtags = data.get("hashtags") or {}
    yt = [str(t) for t in hashtags.get("youtube", [])]
    if "#shorts" not in [t.lower() for t in yt]:
        yt.insert(0, "#shorts")
    meta = ClipMetadata(
        title=str(data.get("title", ""))[:60] or _fallback_metadata(candidate, cfg.cta).title,
        description=str(data.get("description", "")),
        hashtags={
            "tiktok": [str(t) for t in hashtags.get("tiktok", [])],
            "instagram": [str(t) for t in hashtags.get("instagram", [])],
            "youtube": yt,
        },
    )
    return meta, response

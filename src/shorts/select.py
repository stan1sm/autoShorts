"""Clip selection ("highlight detection").

Strategy A (default): LLM reads the timestamped transcript and returns candidates.
Strategy B (fallback): heuristic scoring — audio energy + keyword density + emphasis.

Both feed through the same post-processing: word-boundary snapping, duration
bounds, overlap dedupe, minimum gap, and pre/post-roll padding.
"""

from __future__ import annotations

import array
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import ClipSelectionConfig
from .llm import LLMProvider, extract_json
from .transcribe import Transcript

_SYSTEM_PROMPT = """You select the best short-form clips from a long-form video transcript.
You optimize for clips that perform on TikTok, Reels, and YouTube Shorts:
- a strong hook in the first 3 seconds,
- self-contained context (no unresolved references like "as I said earlier"),
- a clear payoff, punchline, or takeaway by the end.
Respond ONLY with a JSON array, no prose."""

_RULES_BLOCK = """CAMPAIGN RULES — the client's brief for this campaign. It may be written in
any language; follow it regardless. Only select clips that can comply (e.g.
required topic/focus, minimum length, what the clip must push the viewer to
do). If a rule conflicts with any other instruction here, the campaign rule
wins.

{rules}

"""

_USER_PROMPT = """Below is a transcript with segment timestamps (seconds).

{rules_block}Select up to {n} non-overlapping clips, each between {min_s:.0f} and {max_s:.0f} seconds long,
with at least {gap:.0f} seconds between selected clips.
The {min_s:.0f}-{max_s:.0f}s duration is a hard requirement, not a suggestion — a clip outside that
range is unusable and will be discarded, so trim start/end to fit even if it cuts off part of a thought.

Return a JSON array of objects with exactly these keys:
- "start": number (seconds)
- "end": number (seconds)
- "hook": string (the opening line / why viewers stop scrolling, <=80 chars)
- "reason": string (why this clip was selected)
- "score": number 0-1 (your confidence this clip performs well)

Order by score, best first.

TRANSCRIPT:
{transcript}"""


@dataclass
class ClipCandidate:
    start: float
    end: float
    hook: str
    reason: str
    score: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _format_transcript(transcript: Transcript, max_chars: int = 150_000) -> str:
    lines = [f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in transcript.segments]
    text = "\n".join(lines)
    return text[:max_chars]


def llm_select(
    transcript: Transcript, cfg: ClipSelectionConfig, provider: LLMProvider,
    campaign_rules: str = "",
) -> tuple[list[ClipCandidate], object]:
    """Ask the LLM for candidates. Returns (candidates, LLMResponse for cost logging).

    Requests more candidates than `clips_per_source` — the LLM doesn't reliably
    respect the duration/gap bounds, and finalize_candidates() hard-rejects
    anything outside them, so asking for exactly N tends to under-deliver.
    """
    rules = campaign_rules.strip()
    prompt = _USER_PROMPT.format(
        rules_block=_RULES_BLOCK.format(rules=rules) if rules else "",
        n=cfg.clips_per_source + 4,
        min_s=cfg.min_clip_seconds,
        max_s=cfg.max_clip_seconds,
        gap=cfg.min_gap_between_clips_seconds,
        transcript=_format_transcript(transcript),
    )
    response = provider.complete(_SYSTEM_PROMPT, prompt, max_tokens=4096)
    raw = extract_json(response.text)
    if not isinstance(raw, list):
        raise ValueError(f"LLM returned {type(raw).__name__}, expected a JSON array")
    candidates = [
        ClipCandidate(
            start=float(item["start"]),
            end=float(item["end"]),
            hook=str(item.get("hook", "")),
            reason=str(item.get("reason", "")),
            score=float(item.get("score", 0.5)),
        )
        for item in raw
        if isinstance(item, dict) and "start" in item and "end" in item
    ]
    return candidates, response


# --- Strategy B: heuristic --------------------------------------------------

def _audio_energy_per_second(source: Path, duration: float) -> list[float]:
    """RMS energy per second of audio, decoded to 8kHz mono s16 PCM via ffmpeg."""
    proc = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(source),
            "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
        ],
        capture_output=True,
    )
    samples = array.array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    per_second: list[float] = []
    rate = 8000
    for i in range(0, int(duration)):
        window = samples[i * rate : (i + 1) * rate]
        if not window:
            per_second.append(0.0)
            continue
        rms = (sum(s * s for s in window) / len(window)) ** 0.5
        per_second.append(rms / 32768.0)
    return per_second


def heuristic_select(
    transcript: Transcript, cfg: ClipSelectionConfig, source: Path
) -> list[ClipCandidate]:
    """Score sliding windows of segments by energy, keyword density, and emphasis."""
    energy = _audio_energy_per_second(source, transcript.duration)
    mean_energy = (sum(energy) / len(energy)) if energy else 0.0
    keywords = [k.lower() for k in cfg.keywords]

    candidates: list[ClipCandidate] = []
    segments = transcript.segments
    target = (cfg.min_clip_seconds + cfg.max_clip_seconds) / 2
    for i in range(len(segments)):
        # Grow a window of consecutive segments toward the target duration.
        j = i
        while j + 1 < len(segments) and segments[j].end - segments[i].start < target:
            j += 1
        start, end = segments[i].start, segments[j].end
        if not (cfg.min_clip_seconds <= end - start <= cfg.max_clip_seconds * 1.2):
            continue
        text = " ".join(s.text for s in segments[i : j + 1]).lower()
        window_energy = energy[int(start) : max(int(end), int(start) + 1)]
        e_score = (sum(window_energy) / len(window_energy) / mean_energy) if (window_energy and mean_energy) else 1.0
        kw_score = sum(text.count(k) for k in keywords) / max(len(text.split()), 1) * 50 if keywords else 0.0
        emphasis = (text.count("!") + text.count("?")) / max(len(text.split()), 1) * 10
        score = min(1.0, 0.4 * min(e_score, 2.0) / 2.0 + 0.4 * min(kw_score, 1.0) + 0.2 * min(emphasis, 1.0) + 0.2)
        candidates.append(
            ClipCandidate(
                start=start,
                end=end,
                hook=segments[i].text[:80],
                reason="heuristic: energy/keyword/emphasis score",
                score=round(score, 3),
            )
        )
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


# --- Common post-processing --------------------------------------------------

def snap_to_words(candidate: ClipCandidate, transcript: Transcript) -> ClipCandidate | None:
    """Snap start/end outward to the nearest word boundaries so we never cut mid-word."""
    if not transcript.words:
        return candidate
    start_word = next((w for w in transcript.words if w.end > candidate.start), None)
    end_word = next((w for w in reversed(transcript.words) if w.start < candidate.end), None)
    if start_word is None or end_word is None or start_word.start >= end_word.end:
        return None
    return ClipCandidate(
        start=start_word.start,
        end=end_word.end,
        hook=candidate.hook,
        reason=candidate.reason,
        score=candidate.score,
    )


def finalize_candidates(
    candidates: list[ClipCandidate],
    transcript: Transcript,
    cfg: ClipSelectionConfig,
    source_duration: float,
) -> list[ClipCandidate]:
    """Snap, filter by duration, dedupe/gap-enforce (best-score-first), pad, cap at N."""
    snapped = [c for c in (snap_to_words(c, transcript) for c in candidates) if c is not None]
    valid = [
        c for c in snapped
        if cfg.min_clip_seconds <= c.duration <= cfg.max_clip_seconds
    ]
    valid.sort(key=lambda c: c.score, reverse=True)

    chosen: list[ClipCandidate] = []
    for cand in valid:
        conflict = any(
            not (cand.end + cfg.min_gap_between_clips_seconds <= c.start
                 or cand.start >= c.end + cfg.min_gap_between_clips_seconds)
            for c in chosen
        )
        if not conflict:
            chosen.append(cand)
        if len(chosen) >= cfg.clips_per_source:
            break

    padded = [
        ClipCandidate(
            start=max(0.0, c.start - cfg.pre_roll_seconds),
            end=min(source_duration, c.end + cfg.post_roll_seconds),
            hook=c.hook,
            reason=c.reason,
            score=c.score,
        )
        for c in chosen
    ]
    padded.sort(key=lambda c: c.start)
    return padded


def save_candidates(candidates: list[ClipCandidate], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in candidates], f, ensure_ascii=False, indent=1)


def load_candidates(path: Path) -> list[ClipCandidate]:
    with open(path, encoding="utf-8") as f:
        return [ClipCandidate(**c) for c in json.load(f)]

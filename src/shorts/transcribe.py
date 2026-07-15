"""Word-level transcription. Default: faster-whisper (local, CPU or GPU).
Optional: OpenAI Whisper API, or Groq's Whisper endpoint (OpenAI-compatible)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import TranscriptionConfig


@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    duration: float
    words: list[Word] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, path: Path) -> "Transcript":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            language=data["language"],
            duration=data["duration"],
            words=[Word(**w) for w in data["words"]],
            segments=[Segment(**s) for s in data["segments"]],
        )

    def words_between(self, start: float, end: float) -> list[Word]:
        return [w for w in self.words if w.start >= start and w.end <= end]


def _register_cuda_dll_dirs() -> None:
    """Make the CUDA runtime DLLs from the `nvidia-*-cu12` pip wheels loadable.

    On Windows, CTranslate2 resolves cublas64_12.dll / cudnn DLLs via the OS
    search path, which does not include site-packages/nvidia/*/bin — so a
    GPU-capable install still dies with "Library cublas64_12.dll is not found"
    unless we register those directories first.
    """
    if os.name != "nt":
        return
    import importlib.util

    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return
    for root in spec.submodule_search_locations:
        for bin_dir in Path(root).glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _run_whisper(model, path: Path, cfg: TranscriptionConfig, notify=None) -> Transcript:
    language = None if cfg.language == "auto" else cfg.language
    seg_iter, info = model.transcribe(str(path), language=language, word_timestamps=True)

    words: list[Word] = []
    segments: list[Segment] = []
    if notify is not None:
        notify("transcribing", 0.0)
    for seg in seg_iter:
        segments.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip()))
        for w in seg.words or []:
            words.append(Word(word=w.word.strip(), start=w.start, end=w.end))
        if notify is not None and info.duration:
            notify("transcribing", min(99.0, round(seg.end / info.duration * 100, 1)))
    return Transcript(
        language=info.language, duration=info.duration, words=words, segments=segments
    )


def _transcribe_faster_whisper(path: Path, cfg: TranscriptionConfig, notify=None) -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "`pip install faster-whisper` required for the faster-whisper engine"
        ) from exc

    _register_cuda_dll_dirs()
    if notify is not None:
        notify("loading_model", None)  # first run downloads the model — can take a while
    # cuda if available, else int8 on CPU (best speed/quality tradeoff there).
    # The CUDA libraries load lazily at first inference, so the whole run —
    # not just model construction — must be inside the fallback.
    model = None
    try:
        model = WhisperModel(cfg.model, device="cuda", compute_type="float16")
        return _run_whisper(model, path, cfg, notify=notify)
    except Exception:
        del model  # release any half-initialized GPU state before CPU retry
        model = WhisperModel(cfg.model, device="cpu", compute_type="int8")
        return _run_whisper(model, path, cfg, notify=notify)


def _transcribe_openai_compatible(
    path: Path, cfg: TranscriptionConfig, base_url: str | None, api_key_env: str, model: str
) -> Transcript:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("`pip install openai` required for API transcription") from exc

    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"{api_key_env} not set")
    client = OpenAI(api_key=api_key, base_url=base_url)

    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model=model,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            language=None if cfg.language == "auto" else cfg.language,
        )

    words = [Word(word=w.word, start=w.start, end=w.end) for w in (resp.words or [])]
    segments = [
        Segment(start=s.start, end=s.end, text=s.text.strip()) for s in (resp.segments or [])
    ]
    duration = getattr(resp, "duration", None) or (segments[-1].end if segments else 0.0)
    return Transcript(
        language=getattr(resp, "language", "unknown") or "unknown",
        duration=float(duration),
        words=words,
        segments=segments,
    )


def transcribe(
    path: Path, cfg: TranscriptionConfig, cache_path: Path | None = None, notify=None
) -> Transcript:
    """Transcribe with the configured engine; reuse the cached JSON when allowed.

    notify, if given, is called as notify(event_suffix, percent_or_None) for progress
    (local engine only — the API engines are single blocking calls).
    """
    if cache_path and cfg.cache and cache_path.exists():
        return Transcript.from_json(cache_path)

    if cfg.engine == "faster-whisper":
        transcript = _transcribe_faster_whisper(path, cfg, notify=notify)
    elif cfg.engine == "openai":
        transcript = _transcribe_openai_compatible(
            path, cfg, base_url=None, api_key_env="OPENAI_API_KEY", model="whisper-1"
        )
    elif cfg.engine == "groq":
        transcript = _transcribe_openai_compatible(
            path, cfg,
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY",
            model="whisper-large-v3",
        )
    else:  # pragma: no cover - config validation prevents this
        raise ValueError(f"unknown transcription engine: {cfg.engine}")

    if cache_path:
        transcript.to_json(cache_path)
    return transcript

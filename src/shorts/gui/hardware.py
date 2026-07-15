"""Hardware detection and config recommendations for the Settings page."""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass


@dataclass
class HardwareSpecs:
    cpu_cores: int
    ram_gb: float
    gpu_name: str | None
    gpu_vram_gb: float | None
    ffmpeg_version: str | None
    has_anthropic_key: bool
    has_openai_key: bool
    has_groq_key: bool
    has_buffer_key: bool = False
    has_r2_creds: bool = False


def detect_specs() -> HardwareSpecs:
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / (1 << 30), 1)
    except ImportError:
        ram_gb = 0.0

    gpu_name: str | None = None
    gpu_vram_gb: float | None = None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            name, vram_mb = out.stdout.strip().splitlines()[0].rsplit(",", 1)
            gpu_name = name.strip()
            gpu_vram_gb = round(float(vram_mb.strip()) / 1024, 1)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass

    ffmpeg_version: str | None = None
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            ffmpeg_version = out.stdout.splitlines()[0].split()[2]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        pass

    return HardwareSpecs(
        cpu_cores=os.cpu_count() or 1,
        ram_gb=ram_gb,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram_gb,
        ffmpeg_version=ffmpeg_version,
        has_anthropic_key=bool(os.environ.get("ANTHROPIC_API_KEY")),
        has_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
        has_groq_key=bool(os.environ.get("GROQ_API_KEY")),
        has_buffer_key=bool(os.environ.get("BUFFER_API_KEY")),
        has_r2_creds=all(
            os.environ.get(v)
            for v in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID")
        ),
    )


def recommend(specs: HardwareSpecs) -> dict:
    """Recommendations as {notes: [{setting, value, reason, override?}], warnings: [str]}.

    Notes with an "override" key can be applied directly to the config form
    (override is {dotted.path: value}).
    """
    notes: list[dict] = []
    warnings: list[str] = []

    # --- transcription ---
    if specs.gpu_name and (specs.gpu_vram_gb or 0) >= 8:
        notes.append({
            "setting": "Whisper model", "value": "large-v3",
            "reason": f"{specs.gpu_name} ({specs.gpu_vram_gb} GB VRAM) handles large-v3 comfortably.",
            "override": {"transcription.engine": "faster-whisper", "transcription.model": "large-v3"},
        })
    elif specs.gpu_name:
        notes.append({
            "setting": "Whisper model", "value": "medium",
            "reason": f"{specs.gpu_name} has {specs.gpu_vram_gb} GB VRAM — medium fits; large-v3 may not.",
            "override": {"transcription.engine": "faster-whisper", "transcription.model": "medium"},
        })
    elif specs.has_groq_key:
        notes.append({
            "setting": "Transcription engine", "value": "groq",
            "reason": "No GPU detected but GROQ_API_KEY is set — Groq's Whisper API is far faster than CPU transcription.",
            "override": {"transcription.engine": "groq"},
        })
    else:
        # 16 GB physical RAM reports as ~15.7 GiB, so threshold below that.
        model = "medium" if (specs.ram_gb >= 15 and specs.cpu_cores >= 8) else "base"
        notes.append({
            "setting": "Whisper model", "value": model,
            "reason": (
                f"No GPU detected ({specs.cpu_cores} cores, {specs.ram_gb} GB RAM). "
                f"CPU transcription with '{model}' keeps runs tolerable; large-v3 on CPU can take "
                "longer than the video itself. Setting GROQ_API_KEY unlocks a much faster option."
            ),
            "override": {"transcription.engine": "faster-whisper", "transcription.model": model},
        })

    # --- LLM for selection + metadata ---
    if specs.has_anthropic_key:
        notes.append({
            "setting": "LLM provider", "value": "anthropic / claude-sonnet-4-6",
            "reason": "ANTHROPIC_API_KEY detected — best quality for clip selection.",
            "override": {
                "clip_selection.strategy": "llm",
                "clip_selection.llm_provider": "anthropic",
                "metadata.llm_provider": "anthropic",
            },
        })
    elif specs.has_openai_key:
        notes.append({
            "setting": "LLM provider", "value": "openai",
            "reason": "No Anthropic key, but OPENAI_API_KEY is set.",
            "override": {
                "clip_selection.strategy": "llm",
                "clip_selection.llm_provider": "openai",
                "metadata.llm_provider": "openai",
            },
        })
    else:
        notes.append({
            "setting": "Selection strategy", "value": "heuristic",
            "reason": "No LLM API key detected — only the heuristic strategy will work. "
                      "Set ANTHROPIC_API_KEY for much better clip selection and metadata.",
            "override": {"clip_selection.strategy": "heuristic"},
        })
        warnings.append("No LLM API key set: titles/hashtags fall back to generic templates.")

    if not specs.ffmpeg_version:
        warnings.append("ffmpeg not found on PATH — rendering will fail.")
    if specs.ram_gb and specs.ram_gb < 8:
        warnings.append(f"Only {specs.ram_gb} GB RAM — close other apps while rendering.")

    return {"notes": notes, "warnings": warnings}


def hardware_report() -> dict:
    specs = detect_specs()
    return {"specs": asdict(specs), "recommendations": recommend(specs)}

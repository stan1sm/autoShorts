"""Video rendering: cut + reframe to 9:16 + burned-in karaoke captions + loudness
normalization + encode — one ffmpeg pass per clip.

Reframe modes:
- center_crop_blur (v1): blurred stretched copy as background, fitted source on top.
- subject_tracking (Phase 2 scaffold): raises until a detector is wired in.
"""

from __future__ import annotations

from pathlib import Path

from .config import VideoConfig
from .select import ClipCandidate
from .transcribe import Transcript, Word
from .util import run_command

_ASS_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{font},{font_size},{highlight},{base},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{stroke},2,{alignment},60,60,{margin_v},1
Style: Watermark,{font},{wm_font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,0,0,7,24,24,24,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}"""

# Watermark font size as a fraction of caption font size — small "channel bug"
# badge, not competing with the karaoke captions for attention.
_WATERMARK_FONT_RATIO = 0.4

# ASS alignment (numpad layout) + vertical margin per configured position.
_POSITIONS = {
    "bottom_third": (2, 480),
    "middle": (5, 0),
    "top_third": (8, 480),
}


def _hex_to_ass_color(hex_color: str) -> str:
    """'#RRGGBB' -> ASS '&H00BBGGRR' (alpha 00 = opaque)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(
    words: list[Word],
    clip_start: float,
    cfg: VideoConfig,
    clip_duration: float = 0.0,
    watermark_text: str = "",
) -> str:
    """Karaoke (+ optional watermark) ASS for one clip. Word times are
    source-absolute; the output is clip-relative (the render seeks to
    clip_start first)."""
    cap = cfg.captions
    alignment, margin_v = _POSITIONS[cap.position]
    events: list[str] = []

    if watermark_text:
        text = watermark_text.replace("{", "(").replace("}", ")")
        events.append(
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(clip_duration)},Watermark,,0,0,0,,{text}"
        )

    # pop: scale in with a slight overshoot (80% -> 110% -> 100% over 150ms).
    pop = (
        "{\\fscx80\\fscy80\\t(0,90,\\fscx110\\fscy110)\\t(90,150,\\fscx100\\fscy100)}"
        if cap.animation == "pop"
        else ""
    )

    chunks = [
        words[i : i + cap.words_per_caption]
        for i in range(0, len(words), cap.words_per_caption)
    ]
    for chunk in chunks:
        start = chunk[0].start - clip_start
        end = chunk[-1].end - clip_start
        parts = []
        for k, word in enumerate(chunk):
            # \k duration is centiseconds; extend each word to the next word's
            # start so the highlight never stalls mid-chunk.
            until = chunk[k + 1].start if k + 1 < len(chunk) else word.end
            dur_cs = max(1, round((until - word.start) * 100))
            parts.append(f"{{\\k{dur_cs}}}{word.word}")
        text = " ".join(parts)
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Karaoke,,0,0,0,,{pop}{text}"
        )

    return _ASS_TEMPLATE.format(
        width=cfg.output_resolution[0],
        height=cfg.output_resolution[1],
        font=cap.font,
        font_size=cap.font_size,
        wm_font_size=max(12, round(cap.font_size * _WATERMARK_FONT_RATIO)),
        highlight=_hex_to_ass_color(cap.highlight_color),
        base=_hex_to_ass_color(cap.base_color),
        stroke=cap.stroke_width,
        alignment=alignment,
        margin_v=margin_v,
        events="\n".join(events),
    )


def punch_in_cuts(
    transcript: Transcript, clip_start: float, clip_duration: float
) -> list[float]:
    """Clip-relative punch-in cut points: sentence (segment) starts inside the
    clip, at least 1.5s apart and clear of the clip's edges, capped so the
    zoompan expression stays a sane length."""
    cuts: list[float] = []
    for seg in transcript.segments:
        t = seg.start - clip_start
        if t < 0.5 or t > clip_duration - 0.5:
            continue
        if cuts and t - cuts[-1] < 1.5:
            continue
        cuts.append(round(t, 2))
        if len(cuts) >= 40:
            break
    return cuts


def _escape_filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument (Windows-safe)."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def _zoom_filter(
    cfg: VideoConfig, clip_duration: float, cut_times: list[float] | None
) -> str:
    """zoompan stage for the configured zoom effect ('' when disabled).

    The frame is upscaled by `intensity` first so the crop window never drops
    below output resolution (no softness at max zoom). The input is already at
    the target fps, so d=1 keeps frame count and A/V sync intact.
    """
    zoom = cfg.effects.zoom
    w, h = cfg.output_resolution
    if zoom.mode == "continuous":
        if clip_duration <= 0:
            return ""
        rate = (zoom.intensity - 1.0) / clip_duration
        zexpr = f"min(1+{rate:.6f}*in_time\\,{zoom.intensity})"
    elif zoom.mode == "punch_in":
        if not cut_times:
            return ""
        # Alternate 1.0x / intensity: count boundaries passed, take parity.
        passed = "+".join(f"gte(in_time\\,{t:.2f})" for t in cut_times)
        zexpr = f"1+{zoom.intensity - 1.0:.4f}*mod({passed}\\,2)"
    else:
        return ""

    up_w = -(-int(w * zoom.intensity) // 2) * 2  # even ceil
    up_h = -(-int(h * zoom.intensity) // 2) * 2
    return (
        f",scale={up_w}:{up_h},zoompan=z='{zexpr}'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={w}x{h}:fps={cfg.encoding.fps}"
    )


def _build_filter(
    cfg: VideoConfig,
    ass_path: Path | None,
    clip_duration: float = 0.0,
    cut_times: list[float] | None = None,
) -> str:
    w, h = cfg.output_resolution
    if cfg.reframe_mode == "subject_tracking":
        raise NotImplementedError(
            "subject_tracking reframe is Phase 2 — use center_crop_blur"
        )
    chain = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},gblur=sigma=30[bgb];"
        f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,fps={cfg.encoding.fps}"
    )
    chain += _zoom_filter(cfg, clip_duration, cut_times)
    if ass_path is not None:
        chain += f",subtitles=filename='{_escape_filter_path(ass_path)}'"
    chain += ",format=yuv420p[v];"
    chain += f"[0:a]loudnorm=I={cfg.audio.normalize_lufs}:TP=-1.5:LRA=11[a]"
    return chain


def render_clip(
    source: Path,
    candidate: ClipCandidate,
    transcript: Transcript,
    cfg: VideoConfig,
    out_path: Path,
    work_dir: Path,
    watermark_text: str = "",
) -> Path:
    """Render one finished vertical clip; returns out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    words: list[Word] = []
    if cfg.captions.enabled:
        words = transcript.words_between(candidate.start, candidate.end)

    ass_path: Path | None = None
    if words or watermark_text:
        ass_path = work_dir / (out_path.stem + ".ass")
        ass_path.write_text(
            build_ass(words, candidate.start, cfg, candidate.duration, watermark_text),
            encoding="utf-8",
        )

    cut_times: list[float] | None = None
    if cfg.effects.zoom.mode == "punch_in":
        cut_times = punch_in_cuts(transcript, candidate.start, candidate.duration)

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{candidate.start:.3f}",
        "-t", f"{candidate.duration:.3f}",
        "-i", str(source),
        "-filter_complex", _build_filter(cfg, ass_path, candidate.duration, cut_times),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-profile:v", "high",
        "-b:v", cfg.encoding.bitrate,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    run_command(cmd, timeout=1800)
    return out_path

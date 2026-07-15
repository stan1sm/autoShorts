from pathlib import Path

from shorts.config import VideoConfig
from shorts.render import (
    _build_filter,
    _escape_filter_path,
    _hex_to_ass_color,
    build_ass,
    punch_in_cuts,
)
from shorts.transcribe import Segment, Transcript, Word


def test_hex_to_ass_color():
    assert _hex_to_ass_color("#FFE500") == "&H0000E5FF"
    assert _hex_to_ass_color("#FFFFFF") == "&H00FFFFFF"


def test_escape_filter_path_windows():
    escaped = _escape_filter_path(Path(r"C:\out\captions.ass"))
    assert escaped == "C\\:/out/captions.ass"


def test_build_ass_karaoke_chunks():
    cfg = VideoConfig()
    words = [
        Word(word="hello", start=100.0, end=100.4),
        Word(word="world", start=100.5, end=101.0),
        Word(word="again", start=101.2, end=101.8),
    ]
    ass = build_ass(words, clip_start=100.0, cfg=cfg)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    # Two chunks at words_per_caption=2: [hello world], [again]
    assert ass.count("Dialogue:") == 2
    # Karaoke tags present, clip-relative timing starts at 0
    assert "{\\k" in ass
    assert "Dialogue: 0,0:00:00.00," in ass


def test_build_filter_contains_stages():
    cfg = VideoConfig()
    filt = _build_filter(cfg, ass_path=None)
    assert "scale=1080:1920" in filt
    assert "gblur" in filt
    assert "loudnorm=I=-14.0" in filt
    assert "fps=30" in filt
    assert "subtitles" not in filt


def test_build_filter_with_captions(tmp_path):
    cfg = VideoConfig()
    filt = _build_filter(cfg, ass_path=tmp_path / "c.ass")
    assert "subtitles=filename=" in filt


def test_caption_pop_animation():
    words = [Word(word="hi", start=10.0, end=10.4)]
    cfg = VideoConfig()
    cfg.captions.animation = "pop"
    ass = build_ass(words, clip_start=10.0, cfg=cfg)
    assert "\\fscx80" in ass and "\\t(0,90," in ass

    cfg.captions.animation = "none"
    ass = build_ass(words, clip_start=10.0, cfg=cfg)
    assert "\\fscx" not in ass


def test_zoom_none_by_default():
    filt = _build_filter(VideoConfig(), ass_path=None, clip_duration=30.0)
    assert "zoompan" not in filt


def test_zoom_continuous():
    cfg = VideoConfig()
    cfg.effects.zoom.mode = "continuous"
    cfg.effects.zoom.intensity = 1.12
    filt = _build_filter(cfg, ass_path=None, clip_duration=30.0)
    # 0.12 / 30s = 0.004/s ramp, capped at intensity, back to 1080x1920.
    assert "zoompan=z='min(1+0.004000*in_time\\,1.12)'" in filt
    assert "s=1080x1920" in filt
    # Upscale headroom >= intensity so max zoom never softens.
    assert ",scale=1210:2150," in filt
    # No duration (e.g. unit tests, degenerate clip) -> no zoom stage.
    assert "zoompan" not in _build_filter(cfg, ass_path=None, clip_duration=0.0)


def test_zoom_punch_in():
    cfg = VideoConfig()
    cfg.effects.zoom.mode = "punch_in"
    cfg.effects.zoom.intensity = 1.08
    filt = _build_filter(cfg, ass_path=None, clip_duration=30.0, cut_times=[4.0, 11.5])
    assert "gte(in_time\\,4.00)+gte(in_time\\,11.50)" in filt
    assert "mod(" in filt and "0.0800" in filt
    # No cut points -> no zoom stage rather than a constant no-op zoom.
    assert "zoompan" not in _build_filter(cfg, ass_path=None, clip_duration=30.0)


def test_punch_in_cuts_from_segments():
    transcript = Transcript(
        language="en", duration=200.0, words=[],
        segments=[
            Segment(start=100.0, end=104.0, text="a"),   # at clip start -> skipped
            Segment(start=104.0, end=105.0, text="b"),
            Segment(start=105.2, end=110.0, text="c"),   # <1.5s after previous -> skipped
            Segment(start=112.0, end=119.8, text="d"),
            Segment(start=119.8, end=125.0, text="e"),   # within 0.5s of clip end -> skipped
        ],
    )
    cuts = punch_in_cuts(transcript, clip_start=100.0, clip_duration=20.0)
    assert cuts == [4.0, 12.0]

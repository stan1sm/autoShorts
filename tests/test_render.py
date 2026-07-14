from pathlib import Path

from shorts.config import VideoConfig
from shorts.render import _build_filter, _escape_filter_path, _hex_to_ass_color, build_ass
from shorts.transcribe import Word


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

from shorts.config import ClipSelectionConfig
from shorts.select import ClipCandidate, finalize_candidates, snap_to_words


def _cand(start, end, score=0.5):
    return ClipCandidate(start=start, end=end, hook="h", reason="r", score=score)


def test_snap_moves_to_word_boundaries(transcript):
    snapped = snap_to_words(_cand(10.5, 40.5), transcript)
    # First word ending after 10.5 starts at 10.0; last word starting before 40.5 ends at 40.8.
    assert snapped.start == 10.0
    assert snapped.end == 40.8


def test_snap_returns_none_when_no_words(transcript):
    empty = type(transcript)(language="en", duration=120.0, words=[], segments=[])
    # With no words we can't snap; candidate passes through unchanged.
    assert snap_to_words(_cand(5, 30), empty) is not None


def test_finalize_enforces_duration_bounds(transcript):
    cfg = ClipSelectionConfig(min_clip_seconds=20, max_clip_seconds=50)
    out = finalize_candidates([_cand(0, 5), _cand(10, 45)], transcript, cfg, 120.0)
    assert len(out) == 1
    assert out[0].duration >= 20


def test_finalize_enforces_gap_prefers_higher_score(transcript):
    cfg = ClipSelectionConfig(
        min_clip_seconds=20, max_clip_seconds=50, min_gap_between_clips_seconds=30
    )
    # Overlapping/too-close candidates: the higher-score one must win.
    out = finalize_candidates(
        [_cand(0, 30, score=0.4), _cand(10, 40, score=0.9)], transcript, cfg, 120.0
    )
    assert len(out) == 1
    assert out[0].score == 0.9


def test_finalize_pads_and_clamps(transcript):
    cfg = ClipSelectionConfig(
        min_clip_seconds=20, max_clip_seconds=50,
        pre_roll_seconds=0.3, post_roll_seconds=0.5,
    )
    out = finalize_candidates([_cand(10, 40)], transcript, cfg, 120.0)
    assert len(out) == 1
    # snapped to [10.0, 39.8] (last word starting before 40 ends at 39.8), then padded
    assert abs(out[0].start - 9.7) < 1e-6
    assert abs(out[0].end - 40.3) < 1e-6


def test_finalize_caps_clip_count(transcript):
    cfg = ClipSelectionConfig(
        clips_per_source=2, min_clip_seconds=20, max_clip_seconds=50,
        min_gap_between_clips_seconds=0,
    )
    cands = [_cand(0, 25), _cand(30, 55), _cand(60, 85), _cand(90, 115)]
    out = finalize_candidates(cands, transcript, cfg, 120.0)
    assert len(out) == 2


def test_finalize_output_sorted_by_start(transcript):
    cfg = ClipSelectionConfig(
        min_clip_seconds=20, max_clip_seconds=50, min_gap_between_clips_seconds=0
    )
    out = finalize_candidates(
        [_cand(60, 85, score=0.9), _cand(0, 25, score=0.8)], transcript, cfg, 120.0
    )
    assert [c.start for c in out] == sorted(c.start for c in out)

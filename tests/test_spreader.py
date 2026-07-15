"""Schedule spreader — deterministic given a fixed 'now'."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from shorts.buffer.posting import immediate_times, spread_times
from shorts.config import PostingConfig

OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 10, 3, tzinfo=timezone.utc)  # 12:03 Oslo (CEST)


def _cfg(**spread_overrides) -> PostingConfig:
    spread = {
        "window_days": 7,
        "posts_per_day_per_platform": 2,
        "min_gap_hours": 4,
        "same_source_gap_hours": 12,
        "quiet_hours": [0, 7],
        "timezone": "Europe/Oslo",
    }
    spread.update(spread_overrides)
    return PostingConfig.model_validate({"spread": spread})


def test_deterministic():
    assert spread_times(5, _cfg(), NOW) == spread_times(5, _cfg(), NOW)


def test_rounded_to_15_minutes_and_in_future():
    times = spread_times(5, _cfg(), NOW)
    for t in times:
        assert t.minute % 15 == 0 and t.second == 0
        assert t > NOW


def test_min_gap_is_same_source_gap():
    times = spread_times(4, _cfg(), NOW)
    for a, b in zip(times, times[1:]):
        assert (b - a).total_seconds() >= 12 * 3600


def test_respects_quiet_hours():
    late_now = datetime(2026, 7, 15, 20, 30, tzinfo=timezone.utc)  # 22:30 Oslo
    times = spread_times(6, _cfg(), late_now)
    for t in times:
        assert not (0 <= t.astimezone(OSLO).hour < 7)


def test_per_day_cap():
    times = spread_times(6, _cfg(same_source_gap_hours=4, min_gap_hours=4), NOW)
    per_day: dict = {}
    for t in times:
        day = t.astimezone(OSLO).date()
        per_day[day] = per_day.get(day, 0) + 1
    assert max(per_day.values()) <= 2


def test_overflowing_window_raises():
    with pytest.raises(ValueError, match="cannot fit"):
        spread_times(20, _cfg(window_days=3), NOW)


def test_immediate_times_within_15_minutes():
    times = immediate_times(3, NOW)
    assert all((t - NOW).total_seconds() < 15 * 60 for t in times)
    assert times == sorted(times)

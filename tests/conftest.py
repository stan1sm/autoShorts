import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shorts.transcribe import Segment, Transcript, Word  # noqa: E402


@pytest.fixture
def transcript() -> Transcript:
    """A fake 120s transcript: one word per second, sentence segments every 10s."""
    words = [Word(word=f"word{i}", start=float(i), end=float(i) + 0.8) for i in range(120)]
    segments = [
        Segment(start=float(i), end=float(i + 10), text=" ".join(f"word{j}" for j in range(i, i + 10)))
        for i in range(0, 120, 10)
    ]
    return Transcript(language="en", duration=120.0, words=words, segments=segments)

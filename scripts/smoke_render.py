"""Manual smoke test: renders a real captioned clip from a synthetic source.
Needs ffmpeg on PATH. Run: python tests/smoke_render.py <source> <outdir>"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shorts.config import VideoConfig
from shorts.render import render_clip
from shorts.select import ClipCandidate
from shorts.transcribe import Segment, Transcript, Word
from shorts.util import ffprobe_info


def main() -> None:
    source = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    words = [
        Word(word=f"word{i}", start=10.0 + i * 0.5, end=10.0 + i * 0.5 + 0.4)
        for i in range(40)
    ]
    transcript = Transcript(
        language="en", duration=60.0, words=words,
        segments=[Segment(start=10.0, end=30.0, text="synthetic")],
    )
    cand = ClipCandidate(start=10.0, end=30.0, hook="smoke", reason="smoke", score=1.0)
    out = render_clip(source, cand, transcript, VideoConfig(), out_dir / "smoke.mp4", out_dir / "work")

    info = ffprobe_info(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    print(json.dumps({
        "file": str(out),
        "resolution": f'{v["width"]}x{v["height"]}',
        "video_codec": v["codec_name"],
        "audio_codec": a["codec_name"],
        "duration": float(info["format"]["duration"]),
    }, indent=2))
    assert (v["width"], v["height"]) == (1080, 1920), "wrong resolution"
    assert v["codec_name"] == "h264" and a["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 20.0) < 1.0, "wrong duration"
    print("SMOKE OK")


if __name__ == "__main__":
    main()

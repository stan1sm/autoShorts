# shorts-generator

Turn long-form video into platform-ready vertical shorts: 1080×1920, burned-in
karaoke captions, loudness-normalized, with per-platform titles/descriptions/hashtags
in a `manifest.json` ready for Buffer to pick up.

**Scope:** clip generation only. Posting/scheduling is downstream (Buffer).

## Quickstart

Prerequisites: **Python 3.11+** and **ffmpeg** on your PATH
([ffmpeg builds for Windows](https://www.gyan.dev/ffmpeg/builds/)).

```powershell
# 1. Clone and install
git clone https://github.com/stan1sm/autoShorts.git
cd autoShorts
python -m venv .venv
.venv\Scripts\Activate.ps1        # cmd: .venv\Scripts\activate.bat
pip install -e ".[all,dev]"

# 2. Set your Anthropic API key (used for clip selection + titles/hashtags)
#    Get one at https://console.anthropic.com — $5 of credits covers ~30-50 videos.
setx ANTHROPIC_API_KEY "sk-ant-..."
#    (setx only affects NEW terminal windows — open a fresh one before step 3)

# 3. Launch the GUI
shorts gui
```

Your browser opens at `http://127.0.0.1:8501`. First stop: the **Settings** tab —
the hardware panel detects your CPU/GPU and recommends the right Whisper model
(one-click Apply). Then go to **Run**, paste a YouTube URL or pick a video file,
and hit Start. Finished clips land in `output\<source_id>\clips\` with a
`manifest.json` of titles and per-platform hashtags, and are previewable in the
**Clips** tab.

Notes for the first run:
- The Whisper model downloads once (~1.5 GB for `medium`) before transcription starts.
- No GPU? Transcription is the slow stage (~⅓–½ of the video's length on CPU).
  A free [Groq](https://console.groq.com) key + Engine `groq` in Settings makes it
  near-instant.
- Sources must be ≥3 minutes long (configurable in Settings).

## Requirements

- Python 3.11+
- `ffmpeg` + `ffprobe` on PATH
- API keys via environment (only for what you use):
  - `ANTHROPIC_API_KEY` — LLM clip selection + metadata (default provider)
  - `OPENAI_API_KEY` / `GROQ_API_KEY` — optional transcription/LLM alternatives

Install extras: `[all]` pulls in `faster-whisper`, `anthropic`, `openai`, and the
GUI. Install a subset (`[local-whisper]`, `[anthropic]`, `[openai]`, `[gui]`) if
you don't need everything.

## GUI

```powershell
shorts gui
```

Opens `http://127.0.0.1:8501` with three pages:

- **Run** — submit a path/URL or upload a file into the inbox; live per-stage
  job progress (one job renders at a time, the rest queue).
- **Clips** — preview every finished clip in the browser with its title,
  description, and per-platform hashtags.
- **Settings** — edit everything in `config.yaml` from a form, plus a hardware
  panel (CPU/RAM/GPU/ffmpeg/API-key detection) with one-click "Apply"
  recommendations for the right Whisper model and LLM provider. Saving rewrites
  `config.yaml` (comments are not preserved); changes apply to the next job.

## CLI usage

```powershell
# Single file
shorts run .\inbox\episode42.mp4

# URL (YouTube / Twitch VOD / direct mp4, via yt-dlp)
shorts run https://www.youtube.com/watch?v=...

# Whole folder (defaults to inbox_dir from config.yaml)
shorts batch

# Common overrides
shorts run video.mp4 --clips 3 --strategy heuristic --engine groq --force
```

All knobs live in `config.yaml`; CLI flags override it. Re-running the same
source with the same config is a no-op (content-hash dedup in `output/.state.db`);
use `--force` to reprocess.

### Hardware notes

- **NVIDIA GPU (≥8 GB VRAM):** use `transcription.model: large-v3` — best accuracy,
  transcribes a 60-min video in a few minutes. GPU use requires the CUDA runtime
  libraries in the venv (`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`);
  without them the app silently falls back to CPU.
- **CPU only:** `large-v3` can take longer than the video itself — use
  `transcription.model: medium` (or `base`), or `engine: groq` (fast, free tier).
- The GUI's Settings tab detects your hardware and applies the right choice for you.

## Output

```
output/{source_id}/
  source_info.json    # original file metadata + processing timestamp
  transcript.json     # cached word-level transcript (re-runs skip transcription)
  selection.json      # cached clip selection
  manifest.json       # the contract Buffer reads: clips + per-platform metadata
  log.jsonl           # structured per-stage log with timings
  clips/{source_id}_{NN}_{slug}.mp4
```

API usage (tokens per LLM call) is appended to `output/costs.jsonl`.

## Pipeline

ingest → transcribe (word timestamps) → select (LLM default, heuristic fallback)
→ render (cut, 9:16 center-crop-blur reframe, ASS karaoke captions, −14 LUFS,
H.264 8Mbps 30fps) → metadata → manifest.

Each stage caches to disk, so a crash mid-run resumes where it left off. A single
failed clip doesn't stop the others; failures are summarized at exit (exit code 2).

## Tests

```powershell
pytest
```

## Phase 2 (not implemented)

Subject-tracking reframe (mode is scaffolded in config, raises for now), speaker
diarization, thumbnails, review UI, direct Buffer push.

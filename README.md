# shorts-generator

[![CI](https://github.com/stan1sm/autoShorts/actions/workflows/ci.yml/badge.svg)](https://github.com/stan1sm/autoShorts/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Code style: ruff](https://img.shields.io/badge/lint-ruff-261230)

Turn long-form video into platform-ready vertical shorts: 1080x1920, burned-in karaoke captions, loudness-normalized, with per-platform titles, descriptions and hashtags. Optionally host the clips and schedule them to YouTube, Instagram and TikTok through Buffer.

## Features

- **Smart clip selection:** an LLM picks the best moments (heuristic fallback), guided by an optional campaign brief.
- **Vertical render:** 9:16 center-crop over a blurred background, karaoke captions with pop animation, zoom effects (continuous or punch-in), optional watermark, -14 LUFS audio.
- **Metadata:** title, description and hashtags per platform, written to `manifest.json`.
- **Publishing (opt-in):** upload to R2/S3/MinIO, then create Buffer drafts or scheduled posts. Idempotent, with retries.
- **Resumable:** every stage is cached on disk; re-running a source is a no-op unless `--force`.
- **Three ways to run it:** web GUI, CLI, or an Electron desktop shell.

## Quickstart

Prerequisites: **Python 3.11+** and **ffmpeg** on your `PATH` ([Windows builds](https://www.gyan.dev/ffmpeg/builds/)).

```powershell
git clone https://github.com/stan1sm/autoShorts.git
cd autoShorts
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[all,dev]"

copy .env.example .env        # add your ANTHROPIC_API_KEY
shorts gui                    # opens http://127.0.0.1:8501
```

In the GUI: **Settings** (the hardware panel recommends a Whisper model) -> **Run** (paste a URL or pick a file) -> **Clips** (preview, host, schedule).
Finished clips land in `output/<source_id>/clips/`.

Or from the CLI:

```powershell
shorts run .\inbox\episode.mp4
shorts run https://www.youtube.com/watch?v=...
shorts batch                                   # everything in inbox/
shorts run video.mp4 --clips 3 --strategy heuristic --engine groq --force
```

Desktop app: `npm install && npm start` (spawns the same backend from `.venv`).

Configuration lives in `config.yaml` (git-ignored). Start from [`config.example.yaml`](config.example.yaml) or let the GUI create it.

## Documentation

| | |
|---|---|
| [Getting Started](docs/Getting-Started.md) | Install, keys, first run |
| [Configuration](docs/Configuration.md) | Every setting |
| [Pipeline](docs/Pipeline.md) | Stages, caching, campaign rules, output layout |
| [Publishing](docs/Publishing.md) | Hosting + Buffer scheduling |
| [Architecture](docs/Architecture.md) | Module map |
| [Development](docs/Development.md) | Tests, lint, CI |
| [Troubleshooting](docs/Troubleshooting.md) | Common problems |

## Output

```
output/<source_id>/
  manifest.json       # clips + per-platform metadata (the publish contract)
  transcript.json  selection.json  source_info.json  log.jsonl
  clips/<source_id>_<NN>_<slug>.mp4
```

## Project layout

```
src/shorts/   application (pipeline, render, llm, buffer, hosting, gui)
tests/        pytest suite
docs/         wiki-style documentation
electron/     desktop shell
scripts/      launcher and manual smoke scripts
```

## Development

```powershell
pytest
ruff check .
```

## Roadmap

Subject-tracking reframe (scaffolded, not implemented), speaker diarization, custom thumbnails, an in-GUI review/approve gate before publishing, and pulling Buffer analytics back into clip selection.

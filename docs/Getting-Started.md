# Getting Started

## Prerequisites
- Python 3.11+
- `ffmpeg` and `ffprobe` on `PATH` ([Windows builds](https://www.gyan.dev/ffmpeg/builds/))
- An [Anthropic API key](https://console.anthropic.com) (clip selection + metadata). Roughly $5 covers 30-50 videos.

## Install
```powershell
git clone https://github.com/stan1sm/autoShorts.git
cd autoShorts
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[all,dev]"
copy .env.example .env      # then fill in ANTHROPIC_API_KEY
```
`.env` in the working directory is loaded automatically; real environment variables win.

Install subsets with extras: `local-whisper`, `anthropic`, `openai`, `gui`, `posting`.

## Run it
**GUI** (recommended): `shorts gui` opens <http://127.0.0.1:8501>. Visit Settings first (the hardware panel recommends a Whisper model), then Run. On Windows you can also double-click `scripts/start-gui.bat`.

**CLI**:
```powershell
shorts run .\inbox\episode.mp4          # file
shorts run https://youtu.be/...         # URL via yt-dlp
shorts batch                            # whole inbox
shorts run video.mp4 --clips 3 --strategy heuristic --engine groq --force
```

**Desktop app** (Electron shell around the same GUI):
```powershell
npm install
npm start
```
It spawns the Python backend from `.venv`, so the Python install above is still required.

## Config
Copy `config.example.yaml` to `config.yaml` (or just save from the GUI). All keys are optional; see [Configuration](Configuration.md).

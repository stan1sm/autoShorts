# Troubleshooting

- **`ffmpeg not found`:** install ffmpeg and reopen the terminal so `PATH` refreshes.
- **API key not seen after `setx`:** `setx` only affects new terminals. Or put the keys in `.env`.
- **Transcription very slow:** CPU with `large-v3`. Use `medium`/`base` or `engine: groq`.
- **GPU ignored:** install `nvidia-cublas-cu12 nvidia-cudnn-cu12` in the venv; otherwise it silently uses CPU.
- **Clips unchanged after editing campaign rules:** selection is cached; re-run with `--force`.
- **Buffer rejects the media URL:** it must be publicly readable; check `hosting.public_base_url`.
- **Port 8501 busy:** `shorts gui --port 8600` (or `SHORTS_GUI_PORT` for the Electron app).

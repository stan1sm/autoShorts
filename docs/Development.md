# Development

```powershell
pip install -e ".[all,dev]" ruff
pytest              # unit tests, no network or ffmpeg needed
ruff check .        # lint (config in pyproject.toml)
```
CI (`.github/workflows/ci.yml`) runs both on every push and PR.

Manual checks: `python scripts/smoke_render.py <source> <outdir>` (needs ffmpeg) and `scripts/smoke_buffer_post.py` (needs Buffer credentials).

Conventions: tests live in `tests/test_<module>.py`. New config keys go in `config.py`; regenerate `config.example.yaml` from `AppConfig().model_dump(mode="json")`.

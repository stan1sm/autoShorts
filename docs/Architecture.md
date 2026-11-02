# Architecture

```
src/shorts/
  cli.py            Typer entry point (`shorts ...`)
  config.py         Pydantic models for config.yaml + .env loading
  pipeline.py       Orchestrates the generation stages, caching, cost log
  ingest.py transcribe.py select.py render.py metadata.py manifest.py
  llm.py            Provider abstraction + JSON extraction
  state.py          SQLite: sources, hosted media, posts, Buffer channels, kv
  stages/           host.py, post.py: publish stages driven by manifest + state
  hosting/          Object-storage backends (S3-compatible)
  buffer/           Buffer GraphQL client, schemas, channel cache, post composition
  gui/              FastAPI server, job queues, hardware probe, static SPA
electron/           Desktop shell that spawns the backend and loads the GUI
scripts/            Launcher + manual smoke scripts
tests/              pytest suite (no network, no ffmpeg required)
```

**Data flow:** the manifest (`output/<id>/manifest.json`) is the contract. Generation writes it, `host` adds URLs, and `post` reads it and records results in `state.db`.

**GUI jobs:** `JobManager` runs one render at a time (others queue); `PublishManager` does the same for host + post. The SPA polls `/api/jobs`, `/api/results` and `/api/posts`.

**Design choices:** every stage is disk-cached; side effects (posting) are guarded by DB rows so retries are safe; LLM and storage calls sit behind small interfaces so tests use fakes.

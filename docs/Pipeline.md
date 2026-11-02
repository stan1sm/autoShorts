# Pipeline

```
ingest -> transcribe -> select -> render -> metadata -> manifest  [-> host -> post]
```

| Stage | Module | Notes |
|---|---|---|
| ingest | `ingest.py` | Path, URL (yt-dlp) or folder; validates with ffprobe, content-hashes the file |
| transcribe | `transcribe.py` | Word-level timestamps; faster-whisper, OpenAI, or Groq |
| select | `select.py` | LLM picks clips (heuristic fallback); enforces length, gaps, count |
| render | `render.py` | Cut, 9:16 center-crop + blurred background, ASS karaoke captions, -14 LUFS, H.264 |
| metadata | `metadata.py` | Title, description, per-platform hashtags (LLM or fallback) |
| manifest | `manifest.py` | `manifest.json`, the contract the publish stages read |

## Caching and resumability
Each stage writes to `output/<source_id>/` and is skipped on re-run, so a crash resumes where it stopped. One failed clip doesn't stop the rest; failures are summarized at exit (code 2). Re-running the same source with the same config is a no-op (hash dedup in `output/.state.db`); use `--force` to redo it.

## Output layout
```
output/<source_id>/
  source_info.json  transcript.json  selection.json  manifest.json  log.jsonl
  clips/<source_id>_<NN>_<slug>.mp4
output/costs.jsonl     # tokens per LLM call
output/.state.db       # dedup + hosting + post state (SQLite)
```

## Campaign rules
Paste a brand brief (any language) into `campaign.rules`: required focus, mandatory hashtags, per-platform @mentions, an exact CTA. It is injected into both LLM prompts. Selection is cached, so after changing the rules re-run with `--force`.

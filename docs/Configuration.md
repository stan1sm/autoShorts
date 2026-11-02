# Configuration

`config.example.yaml` lists every key with its default. `config.yaml` is git-ignored (it often holds a brand brief and bucket URL). CLI flags override the file. The GUI Settings tab rewrites `config.yaml` (comments are not preserved).

## `input`
| Key | Meaning |
|---|---|
| `inbox_dir` | Folder `shorts batch` scans (non-recursive) |
| `supported_formats` | Accepted extensions |
| `min_source_duration_seconds` | Shorter sources are rejected (default 180) |

## `transcription`
`engine`: `faster-whisper` (local), `openai`, or `groq`. `model`: e.g. `large-v3` (NVIDIA, 8 GB+ VRAM), `medium`/`base` (CPU). `language`: `auto` or an ISO code. `cache`: reuse `transcript.json`.

## `clip_selection`
`strategy`: `llm` (default) or `heuristic`. Also `clips_per_source`, `min/max_clip_seconds`, `min_gap_between_clips_seconds`, `pre/post_roll_seconds`, `keywords` (heuristic boost), `llm_provider`/`llm_model`.

## `video`
- `output_resolution` (1080x1920) and `reframe_mode` (`center_crop_blur`; subject tracking is not implemented).
- `captions`: `enabled`, `style: karaoke`, `font`, `font_size`, `position`, `words_per_caption`, `stroke_width`, `highlight_color`, `base_color`, `animation` (`pop` or none).
- `effects.zoom`: `mode` is `none`, `continuous` (slow push) or `punch_in` (hard cuts at sentence boundaries); `intensity` e.g. 1.12.
- `audio.normalize_lufs` (-14) and `encoding` (h264, 8M, 30 fps).

## `metadata`
`llm_provider`, `llm_model`, `cta` (appended to descriptions; a CTA in campaign rules overrides it).

## `campaign`
`rules`: free-text brand brief injected into selection and metadata prompts. `watermark_text`: small tag burned into the video. See [Pipeline](Pipeline.md#campaign-rules).

## `hosting`
`backend` (`r2`, `s3`, `minio`), `bucket`, `region`, `endpoint_url`, `public_base_url` (needed for public URLs), `retention_days`. See [Publishing](Publishing.md).

## `posting`
`enabled` (off by default), `draft_only` (default true), `platforms`, `schedule_mode` (`queue`/`spread`/`immediate`), `spread.*`, per-platform blocks, `retries`, `rate_limit`.

## Environment variables
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `BUFFER_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID`. See `.env.example`.

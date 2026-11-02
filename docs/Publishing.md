# Publishing

Opt-in: set `posting.enabled: true`. Two stages run after the manifest is written.

## host
Uploads each clip to object storage and writes the public URL into the manifest. Buffer HEAD-probes media URLs and only accepts publicly readable ones, so use a public bucket (Cloudflare R2 `r2.dev` URL or a custom domain) and set `hosting.public_base_url`. Presigned URLs are rejected. Backends: `r2` (default), `s3`, `minio`. `shorts hosting cleanup` deletes clips older than `retention_days`.

## post
Creates one Buffer post per clip per platform (`youtube`, `instagram`, `tiktok`).
- **Idempotent:** a `(clip, platform)` pair that has a Buffer post ID is never posted twice.
- `draft_only: true` (default) creates Buffer drafts you approve manually. **Set it to false only when you want posts to go live.**
- `schedule_mode`: `queue` (Buffer's queue), `spread` (deterministic times over `window_days`, honoring quiet hours, daily caps, min gaps, timezone) or `immediate`.
- Retries with backoff; rate limited by `rate_limit.max_requests_per_15min`.

## Commands
```powershell
shorts buffer channels refresh
shorts publish <source_id> [--dry-run]
shorts host <source_id>
shorts post <source_id>
shorts posts status <source_id>
shorts posts retry-failed
shorts run video.mp4 --publish
```
In the GUI these live on the Clips tab, including per-clip platform checkboxes and retry of failed pairs only.

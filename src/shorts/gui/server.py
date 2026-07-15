"""FastAPI app for the local GUI. Start with `shorts gui`."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml

from ..config import AppConfig, load_config
from ..state import StateStore
from .hardware import hardware_report
from .jobs import JobManager, PublishManager


def create_app(config_path: Path):
    try:
        from fastapi import FastAPI, HTTPException, UploadFile
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError('GUI dependencies missing — run: pip install -e ".[gui]"') from exc

    app = FastAPI(title="shorts-generator")

    @app.middleware("http")
    async def revalidate_static(request, call_next):
        # The GUI ships as plain static files; without this, browsers keep
        # stale app.js across app updates and the UI silently misbehaves.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    load_config(config_path)  # validate config early and load .env into the environment
    publish_jobs = PublishManager(config_path)
    jobs = JobManager(config_path, publish_manager=publish_jobs)
    static_dir = Path(__file__).parent / "static"

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/hardware")
    def hardware() -> dict:
        return hardware_report()

    @app.get("/api/config")
    def get_config() -> dict:
        return load_config(config_path).model_dump(mode="json")

    @app.put("/api/config")
    def put_config(body: dict) -> dict:
        try:
            cfg = AppConfig.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg.model_dump(mode="json"), f, sort_keys=False, allow_unicode=True)
        return {"ok": True}

    @app.post("/api/jobs")
    def create_job(body: dict) -> dict:
        source = (body.get("source") or "").strip()
        if not source:
            raise HTTPException(status_code=422, detail="source (path or URL) required")
        return jobs.submit(
            source, force=bool(body.get("force")), publish=bool(body.get("publish"))
        )

    # --- publishing (HOST + POST via Buffer) ---

    @app.post("/api/publish")
    def create_publish(body: dict) -> dict:
        source_id = (body.get("source_id") or "").strip()
        if not source_id:
            raise HTTPException(status_code=422, detail="source_id required")
        cfg = load_config(config_path)
        if not cfg.posting.enabled:
            raise HTTPException(status_code=422, detail="posting.enabled is off in Settings")
        if not (cfg.output.root_dir / source_id / "manifest.json").exists():
            raise HTTPException(status_code=404, detail=f"no manifest for {source_id}")

        schedule = body.get("schedule") or None
        if schedule is not None and not isinstance(schedule, dict):
            raise HTTPException(status_code=422, detail="schedule must be an object")
        platforms = body.get("platforms") or None
        if platforms is not None and not (
            isinstance(platforms, dict)
            and all(isinstance(v, list) for v in platforms.values())
        ):
            raise HTTPException(status_code=422, detail="platforms must map clip -> list")

        if body.get("dry_run"):
            from ..stages.host import host_source
            from ..stages.post import post_source

            try:
                host_result = host_source(source_id, cfg, dry_run=True)
                post_result = post_source(
                    source_id, cfg, dry_run=True, schedule=schedule, platforms=platforms
                )
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            return {"dry_run": True, "host": asdict(host_result), "post": asdict(post_result)}
        return publish_jobs.submit(source_id, schedule=schedule, platforms=platforms)

    @app.get("/api/publish")
    def list_publish_jobs() -> list[dict]:
        return publish_jobs.list_jobs()

    @app.get("/api/posts")
    def posts_status() -> dict:
        cfg = load_config(config_path)
        state = StateStore(cfg.output.root_dir / ".state.db")
        try:
            return {
                "posts": [asdict(p) for p in state.list_posts()],
                "hosted": [asdict(h) for h in state.list_hosted()],
            }
        finally:
            state.close()

    @app.post("/api/posts/retry-failed")
    def retry_failed_posts() -> dict:
        cfg = load_config(config_path)
        state = StateStore(cfg.output.root_dir / ".state.db")
        try:
            failed = state.list_posts(status="failed")
        finally:
            state.close()
        if not failed:
            return {"queued": False, "detail": "nothing to retry"}
        return {"queued": True, **publish_jobs.submit(None, retry=True)}

    @app.get("/api/buffer/channels")
    def buffer_channels() -> list[dict]:
        cfg = load_config(config_path)
        state = StateStore(cfg.output.root_dir / ".state.db")
        try:
            rows = state.list_channels()
        finally:
            state.close()
        return [
            {"platform": p, "channel_id": cid, "name": name, "refreshed_at": at}
            for p, cid, name, at in rows
        ]

    @app.post("/api/buffer/channels/refresh")
    def buffer_channels_refresh() -> list[dict]:
        from ..buffer.channels import refresh_channels
        from ..buffer.client import BufferAPIError
        from ..stages.post import _make_client

        cfg = load_config(config_path)
        state = StateStore(cfg.output.root_dir / ".state.db")
        client = None
        try:
            client = _make_client(cfg)
            refresh_channels(state, client)
        except BufferAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        finally:
            state.close()
            if client is not None:
                client.close()
        return buffer_channels()

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return jobs.list_jobs()

    @app.post("/api/upload")
    async def upload(file: UploadFile) -> dict:
        cfg = load_config(config_path)
        inbox = cfg.input.inbox_dir
        inbox.mkdir(parents=True, exist_ok=True)
        name = Path(file.filename or "upload.mp4").name  # strip any client path
        dest = inbox / name
        with open(dest, "wb") as f:
            while chunk := await file.read(1 << 20):
                f.write(chunk)
        return {"path": str(dest)}

    @app.get("/api/results")
    def results() -> list[dict]:
        cfg = load_config(config_path)
        out: list[dict] = []
        root = cfg.output.root_dir
        if root.is_dir():
            for manifest in sorted(root.glob("*/manifest.json")):
                try:
                    out.append(json.loads(manifest.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        out.sort(key=lambda m: m.get("processed_at", ""), reverse=True)
        return out

    @app.get("/media/{source_id}/{filename}")
    def media(source_id: str, filename: str) -> FileResponse:
        cfg = load_config(config_path)
        root = cfg.output.root_dir.resolve()
        path = (root / source_id / "clips" / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(status_code=404, detail="clip not found")
        return FileResponse(path, media_type="video/mp4")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


def serve(config_path: Path, host: str = "127.0.0.1", port: int = 8501, open_browser: bool = True) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError('GUI dependencies missing — run: pip install -e ".[gui]"') from exc

    import logging

    class _DropConnectionReset(logging.Filter):
        """Browsers abort video-preview connections constantly; on Windows the
        proactor loop logs each one as a scary traceback. Pure noise — drop."""

        def filter(self, record: logging.LogRecord) -> bool:
            exc = record.exc_info[1] if record.exc_info else None
            return not isinstance(exc, ConnectionResetError)

    logging.getLogger("asyncio").addFilter(_DropConnectionReset())

    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(create_app(config_path), host=host, port=port, log_level="warning")

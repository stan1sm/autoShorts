"""FastAPI app for the local GUI. Start with `shorts gui`."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..config import AppConfig, load_config
from .hardware import hardware_report
from .jobs import JobManager


def create_app(config_path: Path):
    try:
        from fastapi import FastAPI, HTTPException, UploadFile
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError('GUI dependencies missing — run: pip install -e ".[gui]"') from exc

    app = FastAPI(title="shorts-generator")
    jobs = JobManager(config_path)
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
        return jobs.submit(source, force=bool(body.get("force")))

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

    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(create_app(config_path), host=host, port=port, log_level="warning")

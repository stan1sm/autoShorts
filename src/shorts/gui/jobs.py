"""In-memory job queues for the GUI: pipeline runs and Buffer publishes,
each one-at-a-time in its own worker thread."""

from __future__ import annotations

import itertools
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue

from ..config import load_config
from ..pipeline import run_source


class PublishManager:
    """FIFO queue of HOST+POST runs (and failed-post retries)."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._jobs: dict[int, dict] = {}
        self._queue: Queue[int] = Queue()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(
        self, source_id: str | None, retry: bool = False,
        schedule: dict | None = None,
    ) -> dict:
        job = {
            "id": next(self._ids),
            "source_id": source_id,   # None for retry-all jobs
            "retry": retry,
            "schedule": schedule,     # {clip_file: "YYYY-MM-DDTHH:MM"} from the GUI
            "status": "queued",       # queued | running | done | failed
            "stage": None,            # host | post
            "host": None,             # HostResult as dict
            "post": None,             # PostResult as dict (or list for retries)
            "error": None,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._jobs[job["id"]] = job
        self._queue.put(job["id"])
        return dict(job)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [dict(j) for j in sorted(self._jobs.values(), key=lambda j: -j["id"])]

    def _worker(self) -> None:
        from ..stages.host import host_source
        from ..stages.post import post_source, retry_failed

        while True:
            job_id = self._queue.get()
            with self._lock:
                job = self._jobs[job_id]
            job["status"] = "running"
            try:
                cfg = load_config(self.config_path)
                if job["retry"]:
                    job["stage"] = "post"
                    results = retry_failed(cfg)
                    job["post"] = [asdict(r) for r in results]
                    failed = any(r.failed for r in results)
                else:
                    job["stage"] = "host"
                    host_result = host_source(job["source_id"], cfg)
                    job["host"] = asdict(host_result)
                    job["stage"] = "post"
                    post_result = post_source(job["source_id"], cfg, schedule=job["schedule"])
                    job["post"] = asdict(post_result)
                    failed = bool(host_result.failed or post_result.failed)
                # Per-clip failure strings live in job["host"]/job["post"];
                # the UI renders them, so no summary string is needed here.
                job["status"] = "failed" if failed else "done"
            except Exception as exc:
                job["status"] = "failed"
                job["error"] = str(exc)


class JobManager:
    """FIFO queue of pipeline runs. Config is re-read per job so settings
    changes in the GUI apply to the next run without a restart."""

    def __init__(self, config_path: Path, publish_manager: PublishManager | None = None):
        self.config_path = config_path
        self.publish_manager = publish_manager
        self._jobs: dict[int, dict] = {}
        self._queue: Queue[int] = Queue()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, source: str, force: bool = False, publish: bool = False) -> dict:
        job = {
            "id": next(self._ids),
            "source": source,
            "force": force,
            "publish": publish,
            "status": "queued",   # queued | running | done | skipped | failed
            "stage": None,
            "progress": None,     # 0-100 within the current stage, when known
            "source_id": None,
            "clips": 0,
            "clips_total": None,
            "error": None,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._jobs[job["id"]] = job
        self._queue.put(job["id"])
        return dict(job)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [dict(j) for j in sorted(self._jobs.values(), key=lambda j: -j["id"])]

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            with self._lock:
                job = self._jobs[job_id]
            job["status"] = "running"

            def on_event(record: dict, job=job) -> None:
                event = record.get("event")
                if event:
                    job["stage"] = event
                job["progress"] = record.get("percent")
                job["source_id"] = record.get("source_id") or job["source_id"]
                if event == "select.final":
                    job["clips_total"] = record.get("count")

            try:
                cfg = load_config(self.config_path)
                result = run_source(job["source"], cfg, force=job["force"], on_event=on_event)
                job["source_id"] = result.source_id
                job["clips"] = result.clips_rendered
                job["status"] = "skipped" if result.skipped else "done"
                if result.clip_errors:
                    job["error"] = "; ".join(result.clip_errors)
                if job["publish"] and self.publish_manager is not None:
                    self.publish_manager.submit(result.source_id)
            except Exception as exc:
                job["status"] = "failed"
                job["error"] = str(exc)

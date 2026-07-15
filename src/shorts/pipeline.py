"""Pipeline orchestration: ingest -> transcribe -> select -> render -> metadata
-> manifest, with per-stage caching (resumability), per-clip error tolerance,
and API cost tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .ingest import SourceVideo, resolve_input
from .llm import LLMProvider, LLMResponse, get_provider
from .logging_setup import SourceLogger
from .manifest import ClipEntry, make_clip_entry, write_manifest, write_source_info
from .metadata import generate_metadata
from .render import render_clip
from .select import (
    finalize_candidates,
    heuristic_select,
    llm_select,
    load_candidates,
    save_candidates,
)
from .state import StateStore
from .transcribe import transcribe
from .util import slugify


@dataclass
class RunResult:
    source_id: str
    skipped: bool = False
    clips_rendered: int = 0
    clip_errors: list[str] = field(default_factory=list)
    manifest_path: Path | None = None


def _log_cost(costs_path: Path, source_id: str, stage: str, response: LLMResponse) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source_id": source_id,
        "stage": stage,
        "provider": response.provider,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
    }
    with open(costs_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _emit(on_event, event: str, percent: float | None = None, **fields) -> None:
    """Send a progress-only event to the GUI listener (not written to the log file)."""
    if on_event is None:
        return
    record = {"event": event, **fields}
    if percent is not None:
        record["percent"] = percent
    try:
        on_event(record)
    except Exception:
        pass


def _get_llm(provider_name: str, model: str, logger: SourceLogger) -> LLMProvider | None:
    try:
        return get_provider(provider_name, model)
    except Exception as exc:
        logger.error("llm.provider_unavailable", provider=provider_name, error=str(exc))
        return None


def run_source(raw_input: str, cfg: AppConfig, force: bool = False, on_event=None) -> RunResult:
    """Process one source (path or URL) end to end.

    on_event: optional callable(record: dict) invoked for every log event —
    used by the GUI for live progress; ignored by the CLI.
    """
    _emit(on_event, "ingest.start")
    source = resolve_input(
        raw_input, cfg.input,
        notify=lambda ev, pct=None: _emit(on_event, ev, percent=pct),
    )
    out_dir = cfg.output.root_dir / source.source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = SourceLogger(out_dir / "log.jsonl", source.source_id, on_event=on_event)
    state = StateStore(cfg.output.root_dir / ".state.db")
    costs_path = cfg.output.root_dir / "costs.jsonl"

    try:
        if state.is_done(source.source_hash) and not force:
            logger.log("skip.already_processed", path=str(source.path))
            return RunResult(source_id=source.source_id, skipped=True,
                             manifest_path=out_dir / "manifest.json")
        state.register(source.source_hash, source.source_id, str(source.path))
        write_source_info(source, out_dir)

        # --- Transcribe (cached to transcript.json) ---
        with logger.stage("transcribe", engine=cfg.transcription.engine):
            transcript = transcribe(
                source.path, cfg.transcription, cache_path=out_dir / "transcript.json",
                notify=lambda ev, pct=None: _emit(on_event, f"transcribe.{ev}", percent=pct),
            )

        # --- Select (cached to selection.json) ---
        selection_path = out_dir / "selection.json"
        if selection_path.exists() and not force:
            candidates = load_candidates(selection_path)
            logger.log("select.cache_hit", count=len(candidates))
        else:
            with logger.stage("select", strategy=cfg.clip_selection.strategy):
                if cfg.clip_selection.strategy == "llm":
                    provider = _get_llm(
                        cfg.clip_selection.llm_provider, cfg.clip_selection.llm_model, logger
                    )
                    if provider is None:
                        logger.log("select.fallback_heuristic")
                        raw_candidates = heuristic_select(transcript, cfg.clip_selection, source.path)
                    else:
                        raw_candidates, response = llm_select(
                            transcript, cfg.clip_selection, provider,
                            campaign_rules=cfg.campaign.rules,
                        )
                        _log_cost(costs_path, source.source_id, "select", response)
                else:
                    raw_candidates = heuristic_select(transcript, cfg.clip_selection, source.path)
                candidates = finalize_candidates(
                    raw_candidates, transcript, cfg.clip_selection, source.duration_seconds
                )
                save_candidates(candidates, selection_path)
        if not candidates:
            raise RuntimeError("no viable clip candidates after filtering")
        logger.log("select.final", count=len(candidates))

        # --- Render + metadata, clip by clip; one failure doesn't stop the rest ---
        meta_provider = _get_llm(cfg.metadata.llm_provider, cfg.metadata.llm_model, logger)
        clips_dir = out_dir / "clips"
        work_dir = out_dir / ".work"
        entries: list[ClipEntry] = []
        errors: list[str] = []

        for idx, cand in enumerate(candidates, start=1):
            clip_label = f"clip_{idx:02d}"
            try:
                with logger.stage(f"metadata.{clip_label}"):
                    meta, response = generate_metadata(
                        cand, transcript, cfg.metadata, meta_provider,
                        campaign_rules=cfg.campaign.rules,
                    )
                    if response is not None:
                        _log_cost(costs_path, source.source_id, f"metadata.{clip_label}", response)

                slug = slugify(meta.title or cand.hook)
                clip_file = clips_dir / f"{source.source_id}_{idx:02d}_{slug}.mp4"
                if clip_file.exists() and not force:
                    logger.log(f"render.{clip_label}.cache_hit", file=clip_file.name)
                else:
                    with logger.stage(f"render.{clip_label}", start=cand.start, end=cand.end):
                        render_clip(source.path, cand, transcript, cfg.video, clip_file, work_dir)

                entries.append(make_clip_entry(f"clips/{clip_file.name}", cand, meta))
            except Exception as exc:
                errors.append(f"{clip_label}: {exc}")
                logger.error(f"{clip_label}.failed", error=str(exc))

        if not entries:
            raise RuntimeError(f"all clips failed: {'; '.join(errors)}")

        manifest_path = write_manifest(source, entries, out_dir)
        state.mark(source.source_hash, "done")
        logger.log("pipeline.done", clips=len(entries), errors=len(errors))
        return RunResult(
            source_id=source.source_id,
            clips_rendered=len(entries),
            clip_errors=errors,
            manifest_path=manifest_path,
        )
    except Exception:
        state.mark(source.source_hash, "failed")
        raise
    finally:
        state.close()
        logger.close()

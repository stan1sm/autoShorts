"""CLI entrypoints: `shorts run <path-or-url>` and `shorts batch [folder]`."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .config import load_config
from .ingest import IngestError, scan_folder
from .pipeline import run_source

app = typer.Typer(help="Turn long-form video into platform-ready vertical shorts.")

_CONFIG_OPT = typer.Option(Path("config.yaml"), "--config", "-c", help="Path to config YAML.")
_FORCE_OPT = typer.Option(False, "--force", help="Reprocess even if already done.")


def _overrides(
    clips: Optional[int], strategy: Optional[str], reframe: Optional[str], engine: Optional[str]
) -> dict:
    return {
        "clip_selection.clips_per_source": clips,
        "clip_selection.strategy": strategy,
        "video.reframe_mode": reframe,
        "transcription.engine": engine,
    }


@app.command()
def run(
    source: str = typer.Argument(..., help="Video file path or URL (YouTube/Twitch/direct)."),
    config: Path = _CONFIG_OPT,
    force: bool = _FORCE_OPT,
    clips: Optional[int] = typer.Option(None, help="Override clips per source."),
    strategy: Optional[str] = typer.Option(None, help="Override selection strategy (llm|heuristic)."),
    reframe: Optional[str] = typer.Option(None, help="Override reframe mode."),
    engine: Optional[str] = typer.Option(None, help="Override transcription engine."),
) -> None:
    """Process a single source video end to end."""
    cfg = load_config(config, _overrides(clips, strategy, reframe, engine))
    try:
        result = run_source(source, cfg, force=force)
    except (IngestError, RuntimeError) as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if result.skipped:
        typer.secho(f"[{result.source_id}] already processed — no-op.", fg=typer.colors.YELLOW)
    else:
        typer.secho(
            f"[{result.source_id}] {result.clips_rendered} clips -> {result.manifest_path}",
            fg=typer.colors.GREEN,
        )
    for err in result.clip_errors:
        typer.secho(f"  clip error: {err}", fg=typer.colors.RED, err=True)
    if result.clip_errors:
        raise typer.Exit(code=2)


@app.command()
def batch(
    folder: Optional[Path] = typer.Argument(None, help="Folder to scan (default: inbox_dir from config)."),
    config: Path = _CONFIG_OPT,
    force: bool = _FORCE_OPT,
) -> None:
    """Process every supported video in a folder, one at a time. Failures don't
    stop the batch; a summary is printed (and exits non-zero) at the end."""
    cfg = load_config(config)
    target = folder or cfg.input.inbox_dir
    try:
        files = scan_folder(target, cfg.input)
    except IngestError as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if not files:
        typer.echo(f"No supported videos in {target}.")
        return

    failures: list[str] = []
    for path in files:
        typer.echo(f"--- {path.name} ---")
        try:
            result = run_source(str(path), cfg, force=force)
            status = "skipped (already done)" if result.skipped else f"{result.clips_rendered} clips"
            typer.secho(f"{path.name}: {status}", fg=typer.colors.GREEN)
            failures.extend(f"{path.name}: {e}" for e in result.clip_errors)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
            typer.secho(f"{path.name}: FAILED — {exc}", fg=typer.colors.RED, err=True)

    if failures:
        typer.secho(f"\n{len(failures)} failure(s):", fg=typer.colors.RED, err=True)
        for f in failures:
            typer.secho(f"  {f}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    typer.secho(f"\nBatch complete: {len(files)} source(s) processed.", fg=typer.colors.GREEN)


@app.command()
def gui(
    config: Path = _CONFIG_OPT,
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8501, help="Port."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open the browser."),
) -> None:
    """Launch the local web GUI (run jobs, browse clips, edit settings)."""
    from .gui.server import serve

    typer.secho(f"GUI running at http://{host}:{port}  (Ctrl+C to stop)", fg=typer.colors.GREEN)
    try:
        serve(config, host=host, port=port, open_browser=not no_browser)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

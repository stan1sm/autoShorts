"""CLI entrypoints: `shorts run <path-or-url>`, `shorts batch [folder]`, and the
publishing commands (`host`, `post`, `publish`, `buffer`, `posts`, `hosting`)."""

from __future__ import annotations

from pathlib import Path

import typer

from .config import load_config
from .ingest import IngestError, scan_folder
from .pipeline import run_source

app = typer.Typer(help="Turn long-form video into platform-ready vertical shorts.")

buffer_app = typer.Typer(help="Buffer API utilities.")
channels_app = typer.Typer(help="Connected-channel cache.")
buffer_app.add_typer(channels_app, name="channels")
app.add_typer(buffer_app, name="buffer")

posts_app = typer.Typer(help="Post status and retries.")
app.add_typer(posts_app, name="posts")

hosting_app = typer.Typer(help="Hosted-media maintenance.")
app.add_typer(hosting_app, name="hosting")

_CONFIG_OPT = typer.Option(Path("config.yaml"), "--config", "-c", help="Path to config YAML.")
_FORCE_OPT = typer.Option(False, "--force", help="Reprocess even if already done.")
_DRY_RUN_OPT = typer.Option(False, "--dry-run", help="Show what would happen; no uploads/posts.")


def _overrides(
    clips: int | None, strategy: str | None, reframe: str | None, engine: str | None
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
    clips: int | None = typer.Option(None, help="Override clips per source."),
    strategy: str | None = typer.Option(None, help="Override selection strategy (llm|heuristic)."),
    reframe: str | None = typer.Option(None, help="Override reframe mode."),
    engine: str | None = typer.Option(None, help="Override transcription engine."),
    publish_after: bool = typer.Option(
        False, "--publish", help="Run HOST + POST (Buffer) after clip generation."
    ),
) -> None:
    """Process a single source video end to end."""
    cfg = load_config(config, _overrides(clips, strategy, reframe, engine))
    try:
        result = run_source(source, cfg, force=force)
    except (IngestError, RuntimeError) as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    if result.skipped:
        typer.secho(f"[{result.source_id}] already processed — no-op.", fg=typer.colors.YELLOW)
    else:
        typer.secho(
            f"[{result.source_id}] {result.clips_rendered} clips -> {result.manifest_path}",
            fg=typer.colors.GREEN,
        )
    for err in result.clip_errors:
        typer.secho(f"  clip error: {err}", fg=typer.colors.RED, err=True)
    if publish_after:
        _publish(result.source_id, cfg, dry_run=False)
    if result.clip_errors:
        raise typer.Exit(code=2)


@app.command()
def batch(
    folder: Path | None = typer.Argument(None, help="Folder to scan (default: inbox_dir from config)."),
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
        raise typer.Exit(code=1) from None
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


# --- publishing (HOST + POST via Buffer) ---


def _host(source_id: str, cfg, dry_run: bool):
    from .stages.host import host_source

    result = host_source(source_id, cfg, dry_run=dry_run)
    prefix = "DRY RUN: " if dry_run else ""
    typer.secho(
        f"{prefix}[{source_id}] hosted: {result.uploaded} uploaded, "
        f"{result.skipped} unchanged, {len(result.failed)} failed",
        fg=typer.colors.RED if result.failed else typer.colors.GREEN,
    )
    for err in result.failed:
        typer.secho(f"  {err}", fg=typer.colors.RED, err=True)
    return result


def _post(source_id: str, cfg, dry_run: bool):
    from .stages.post import format_dry_run, post_source

    result = post_source(source_id, cfg, dry_run=dry_run)
    if dry_run:
        typer.echo(format_dry_run(result))
        return result
    typer.secho(
        f"[{source_id}] posts: {result.succeeded} created"
        f"{' (drafts)' if cfg.posting.draft_only else ''}, "
        f"{result.skipped_duplicates} duplicate-skipped, "
        f"{result.skipped_unhosted} unhosted-skipped, {len(result.failed)} failed",
        fg=typer.colors.RED if result.failed else typer.colors.GREEN,
    )
    for err in result.failed:
        typer.secho(f"  {err}", fg=typer.colors.RED, err=True)
    return result


def _publish(source_id: str, cfg, dry_run: bool) -> None:
    host_result = _host(source_id, cfg, dry_run)
    post_result = _post(source_id, cfg, dry_run)
    if host_result.failed or post_result.failed:
        raise typer.Exit(code=2)


@app.command()
def host(
    source_id: str = typer.Argument(..., help="Source ID (output folder name)."),
    config: Path = _CONFIG_OPT,
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Upload a source's clips to object storage (HOST stage only)."""
    result = _host(source_id, load_config(config), dry_run)
    if result.failed:
        raise typer.Exit(code=2)


@app.command()
def post(
    source_id: str = typer.Argument(..., help="Source ID (output folder name)."),
    config: Path = _CONFIG_OPT,
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Create Buffer posts for a source's hosted clips (POST stage only)."""
    result = _post(source_id, load_config(config), dry_run)
    if result.failed:
        raise typer.Exit(code=2)


@app.command()
def publish(
    source_id: str = typer.Argument(..., help="Source ID (output folder name)."),
    config: Path = _CONFIG_OPT,
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """HOST + POST end to end for one source."""
    _publish(source_id, load_config(config), dry_run)


@channels_app.command("refresh")
def channels_refresh(config: Path = _CONFIG_OPT) -> None:
    """Re-query Buffer for connected channels and rebuild the local cache."""
    from .buffer.channels import refresh_channels
    from .stages.post import _make_client
    from .state import StateStore

    cfg = load_config(config)
    state = StateStore(cfg.output.root_dir / ".state.db")
    client = _make_client(cfg)
    try:
        mapping = refresh_channels(state, client)
    finally:
        state.close()
        client.close()
    if not mapping:
        typer.secho("No YouTube/Instagram/TikTok channels connected in Buffer.",
                    fg=typer.colors.YELLOW)
        return
    for platform, channel_id in sorted(mapping.items()):
        typer.echo(f"{platform:<10} {channel_id}")


@channels_app.command("list")
def channels_list(config: Path = _CONFIG_OPT) -> None:
    """Print the cached platform -> channel mapping."""
    from .state import StateStore

    cfg = load_config(config)
    state = StateStore(cfg.output.root_dir / ".state.db")
    try:
        rows = state.list_channels()
    finally:
        state.close()
    if not rows:
        typer.echo("Channel cache is empty — run: shorts buffer channels refresh")
        return
    for platform, channel_id, name, refreshed_at in rows:
        typer.echo(f"{platform:<10} {channel_id}  {name or ''}  (refreshed {refreshed_at})")


@posts_app.command("status")
def posts_status(
    source_id: str = typer.Argument(..., help="Source ID (output folder name)."),
    config: Path = _CONFIG_OPT,
) -> None:
    """Show post status per clip per platform for one source."""
    from .state import StateStore

    cfg = load_config(config)
    state = StateStore(cfg.output.root_dir / ".state.db")
    try:
        records = state.list_posts(source_id=source_id)
    finally:
        state.close()
    if not records:
        typer.echo(f"No post attempts recorded for {source_id}.")
        return
    for r in records:
        clip_name = Path(r.clip_file).name
        line = f"{clip_name:<50} {r.platform:<10} {r.status:<10} {r.buffer_post_id or '-'}"
        if r.scheduled_for:
            line += f"  due {r.scheduled_for}"
        if r.last_error:
            line += f"  [{r.last_error[:80]}]"
        color = {"failed": typer.colors.RED, "pending": typer.colors.YELLOW}.get(r.status)
        typer.secho(line, fg=color)


@posts_app.command("retry-failed")
def posts_retry_failed(config: Path = _CONFIG_OPT, dry_run: bool = _DRY_RUN_OPT) -> None:
    """Retry every post currently in 'failed' status."""
    from .stages.post import format_dry_run, retry_failed

    cfg = load_config(config)
    results = retry_failed(cfg, dry_run=dry_run)
    if not results:
        typer.echo("Nothing to retry.")
        return
    failures = 0
    for result in results:
        if dry_run:
            typer.echo(format_dry_run(result))
            continue
        failures += len(result.failed)
        typer.echo(
            f"[{result.source_id}] retried: {result.succeeded} created, "
            f"{len(result.failed)} still failing"
        )
    if failures:
        raise typer.Exit(code=2)


@hosting_app.command("cleanup")
def hosting_cleanup(config: Path = _CONFIG_OPT, dry_run: bool = _DRY_RUN_OPT) -> None:
    """Delete hosted clips older than hosting.retention_days (skips clips with
    pending posts)."""
    from .stages.host import cleanup_hosted

    cfg = load_config(config)
    removed = cleanup_hosted(cfg, dry_run=dry_run)
    verb = "Would delete" if dry_run else "Deleted"
    typer.echo(f"{verb} {len(removed)} hosted clip(s).")
    for key in removed:
        typer.echo(f"  {key}")


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
        raise typer.Exit(code=1) from None


if __name__ == "__main__":
    app()

"""Watch mode for the sync command."""

from __future__ import annotations

import datetime

import click

from ..exceptions import StaleSnapshotError


def _import_watchfiles():
    """Lazy-import watchfiles, raising a friendly error if missing."""
    try:
        import watchfiles
        return watchfiles
    except ImportError:
        raise click.ClickException(
            "watchfiles is required for --watch mode.\n"
            "Install it with: pip install gitstore[watch]"
        )


def _format_summary(report) -> str:
    """One-line +N ~N -N summary from a CopyReport."""
    parts = []
    if report.add:
        parts.append(f"+{len(report.add)}")
    if report.update:
        parts.append(f"~{len(report.update)}")
    if report.delete:
        parts.append(f"-{len(report.delete)}")
    return " ".join(parts) if parts else "no changes"


def _run_sync_cycle(store, branch, local_path, repo_dest, *,
                    message, ignore_errors, checksum):
    """Run one sync-to-repo cycle with a fresh FS."""
    from ..copy import sync_to_repo

    fs = store.branches[branch]
    new_fs = sync_to_repo(
        fs, local_path, repo_dest,
        message=message, ignore_errors=ignore_errors,
        checksum=checksum,
    )
    report = new_fs.report
    now = datetime.datetime.now().strftime("%H:%M:%S")
    if report:
        summary = _format_summary(report)
        short_hash = new_fs.hash[:7] if new_fs.hash else ""
        click.echo(f"[{now}] Sync: {summary} (commit {short_hash})")
        for w in report.warnings:
            click.echo(f"WARNING: {w.path}: {w.error}", err=True)
        for e in report.errors:
            click.echo(f"ERROR: {e.path}: {e.error}", err=True)
    else:
        click.echo(f"[{now}] Sync: no changes")


def watch_and_sync(store, branch, local_path, repo_dest, *,
                   debounce, message, ignore_errors, checksum):
    """Watch *local_path* and sync to repo on every change batch."""
    watchfiles = _import_watchfiles()

    # Initial sync to catch up with any pending changes
    click.echo(f"Watching {local_path} -> :{repo_dest or '/'} (debounce {debounce}ms)")
    try:
        _run_sync_cycle(store, branch, local_path, repo_dest,
                        message=message, ignore_errors=ignore_errors,
                        checksum=checksum)
    except StaleSnapshotError:
        click.echo("WARNING: Stale snapshot on initial sync, will retry", err=True)
    except Exception as exc:
        click.echo(f"ERROR: Initial sync failed: {exc}", err=True)

    # Watch loop
    try:
        for _changes in watchfiles.watch(local_path, debounce=debounce):
            try:
                _run_sync_cycle(store, branch, local_path, repo_dest,
                                message=message, ignore_errors=ignore_errors,
                                checksum=checksum)
            except StaleSnapshotError:
                click.echo("WARNING: Stale snapshot, will retry on next change", err=True)
            except Exception as exc:
                click.echo(f"ERROR: Sync failed: {exc}", err=True)
    except KeyboardInterrupt:
        click.echo("\nStopped watching.")

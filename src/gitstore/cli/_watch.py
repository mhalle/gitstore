"""Watch mode for the sync command."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import click
import watchfiles

from ..exceptions import StaleSnapshotError

if TYPE_CHECKING:
    from .._exclude import ExcludeFilter


def _format_summary(changes) -> str:
    """One-line +N ~N -N summary from a ChangeReport."""
    parts = []
    if changes.add:
        parts.append(f"+{len(changes.add)}")
    if changes.update:
        parts.append(f"~{len(changes.update)}")
    if changes.delete:
        parts.append(f"-{len(changes.delete)}")
    return " ".join(parts) if parts else "no changes"


def _run_sync_cycle(store, branch, local_path, repo_dest, *,
                    message, ignore_errors, checksum,
                    exclude: ExcludeFilter | None = None):
    """Run one sync-to-repo cycle with a fresh FS."""
    from ..copy import sync_to_repo

    fs = store.branches[branch]
    new_fs = sync_to_repo(
        fs, local_path, repo_dest,
        message=message, ignore_errors=ignore_errors,
        checksum=checksum, exclude=exclude,
    )
    changes = new_fs.changes
    now = datetime.datetime.now().strftime("%H:%M:%S")
    if changes:
        summary = _format_summary(changes)
        short_hash = new_fs.commit_hash[:7] if new_fs.commit_hash else ""
        click.echo(f"[{now}] Sync: {summary} (commit {short_hash})")
        for w in changes.warnings:
            click.echo(f"WARNING: {w.path}: {w.error}", err=True)
        for e in changes.errors:
            click.echo(f"ERROR: {e.path}: {e.error}", err=True)
    else:
        click.echo(f"[{now}] Sync: no changes")


def watch_and_sync(store, branch, local_path, repo_dest, *,
                   debounce, message, ignore_errors, checksum,
                   exclude: ExcludeFilter | None = None):
    """Watch *local_path* and sync to repo on every change batch."""
    # Initial sync to catch up with any pending changes
    click.echo(f"Watching {local_path} -> :{repo_dest or '/'} (debounce {debounce}ms)")
    try:
        _run_sync_cycle(store, branch, local_path, repo_dest,
                        message=message, ignore_errors=ignore_errors,
                        checksum=checksum, exclude=exclude)
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
                                checksum=checksum, exclude=exclude)
            except StaleSnapshotError:
                click.echo("WARNING: Stale snapshot, will retry on next change", err=True)
            except Exception as exc:
                click.echo(f"ERROR: Sync failed: {exc}", err=True)
    except KeyboardInterrupt:
        click.echo("\nStopped watching.")

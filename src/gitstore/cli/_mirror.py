"""Backup and restore commands."""

from __future__ import annotations

import click

from ._helpers import (
    main,
    _repo_option,
    _dry_run_option,
    _no_create_option,
    _require_repo,
    _status,
    _open_store,
    _open_or_create_bare,
)


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

@main.command("backup")
@_repo_option
@click.argument("url")
@_dry_run_option
@click.pass_context
def backup_cmd(ctx, url, dry_run):
    """Push all refs to a remote URL, creating an exact mirror.

    Force-overwrites diverged refs and deletes remote-only refs.
    """
    from ..mirror import resolve_credentials, print_diff, progress_cb

    store = _open_store(_require_repo(ctx))
    auth_url = resolve_credentials(url)
    diff = store.backup(auth_url, dry_run=dry_run, progress=progress_cb(ctx))
    if dry_run:
        print_diff(diff, "push")
    else:
        _status(ctx, f"Backed up to {url}")


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

@main.command("restore")
@_repo_option
@click.argument("url")
@_dry_run_option
@_no_create_option
@click.pass_context
def restore_cmd(ctx, url, dry_run, no_create):
    """Fetch all refs from a remote URL, overwriting local state.

    Force-overwrites diverged refs and deletes local-only refs.
    """
    from ..mirror import resolve_credentials, print_diff, progress_cb

    repo_path = _require_repo(ctx)
    store = _open_store(repo_path) if no_create else _open_or_create_bare(repo_path)
    auth_url = resolve_credentials(url)
    diff = store.restore(auth_url, dry_run=dry_run, progress=progress_cb(ctx))
    if dry_run:
        print_diff(diff, "pull")
    else:
        _status(ctx, f"Restored from {url}")

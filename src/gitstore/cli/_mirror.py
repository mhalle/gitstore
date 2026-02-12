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
# Helpers
# ---------------------------------------------------------------------------

def _print_diff(diff, direction: str) -> None:
    """Pretty-print a MirrorDiff to stdout."""
    verb = "push" if direction == "push" else "pull"
    if diff.in_sync:
        click.echo(f"Nothing to {verb} — already in sync.")
        return
    for c in sorted(diff.create, key=lambda c: c.ref):
        click.echo(f"  create  {c.ref}  {c.src_sha[:7]}")
    for c in sorted(diff.update, key=lambda c: c.ref):
        click.echo(f"  update  {c.ref}  {c.dest_sha[:7]} -> {c.src_sha[:7]}")
    for c in sorted(diff.delete, key=lambda c: c.ref):
        click.echo(f"  delete  {c.ref}  {c.dest_sha[:7]}")
    click.echo(f"{diff.total} ref(s) would be changed.")


def _progress_cb(ctx):
    """Return a progress callback if verbose mode is on, else None."""
    if not ctx.obj.get("verbose"):
        return None
    def _on_progress(msg):
        text = msg.decode()
        text = text.replace("\r", "\r\033[K")
        click.echo(text, nl=False, err=True)
    return _on_progress


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
    from ..mirror import resolve_credentials

    store = _open_store(_require_repo(ctx))
    auth_url = resolve_credentials(url)
    diff = store.backup(auth_url, dry_run=dry_run, progress=_progress_cb(ctx))
    if dry_run:
        _print_diff(diff, "push")
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
    from ..mirror import resolve_credentials

    repo_path = _require_repo(ctx)
    store = _open_store(repo_path) if no_create else _open_or_create_bare(repo_path)
    auth_url = resolve_credentials(url)
    diff = store.restore(auth_url, dry_run=dry_run, progress=_progress_cb(ctx))
    if dry_run:
        _print_diff(diff, "pull")
    else:
        _status(ctx, f"Restored from {url}")

"""Basic commands: init, destroy, ls, cat, rm, log."""

from __future__ import annotations

import json
import os
import sys

import click

from ..exceptions import StaleSnapshotError
from ..repo import GitStore
from ..tree import _normalize_path
from ._helpers import (
    main,
    _repo_option,
    _require_repo,
    _status,
    _strip_colon,
    _normalize_repo_path,
    _open_store,
    _get_branch_fs,
    _get_fs,
    _normalize_at_path,
    _parse_before,
    _resolve_snapshot,
    _log_entry_dict,
)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.option("--branch", "-b", default="main", help="Initial branch name (default: main).")
@click.option("-f", "--force", is_flag=True, help="Destroy existing repo and recreate.")
@click.pass_context
def init(ctx, branch, force):
    """Create a new bare git repository."""
    repo_path = _require_repo(ctx)
    if force and os.path.exists(repo_path):
        import shutil
        shutil.rmtree(repo_path)
    try:
        GitStore.open(repo_path, create=True, branch=branch)
    except FileExistsError as exc:
        raise click.ClickException(str(exc))
    _status(ctx, f"Initialized {repo_path}")


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.option("-f", "--force", is_flag=True, help="Required to destroy a non-empty repo.")
@click.pass_context
def destroy(ctx, force):
    """Remove a bare git repository.

    Requires -f if the repo contains any branches or tags.
    """
    repo_path = _require_repo(ctx)
    try:
        store = GitStore.open(repo_path)
    except FileNotFoundError:
        raise click.ClickException(f"Repository not found: {repo_path}")

    if not force:
        has_data = len(store.tags) > 0 or any(
            fs.ls() for fs in store.branches.values()
        )
        if has_data:
            raise click.ClickException(
                "Repository is not empty. Use -f to destroy."
            )

    import shutil
    shutil.rmtree(repo_path)
    _status(ctx, f"Destroyed {repo_path}")


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("path", required=False, default=None)
@click.option("--branch", "-b", default="main", help="Branch to list.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to read from.")
@click.option("--path", "at_path", default=None, help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None, help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None, help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def ls(ctx, path, branch, ref, at_path, match_pattern, before):
    """List files/directories at PATH (or root)."""
    store = _open_store(_require_repo(ctx))
    before = _parse_before(before)
    fs = _resolve_snapshot(_get_fs(store, branch, ref), at_path, match_pattern, before)

    repo_path = None
    if path is not None:
        repo_path = _strip_colon(path)
        if repo_path:
            repo_path = _normalize_repo_path(repo_path)

    try:
        entries = fs.ls(repo_path if repo_path else None)
    except FileNotFoundError:
        raise click.ClickException(f"Path not found: {repo_path}")
    except NotADirectoryError:
        raise click.ClickException(f"Not a directory: {repo_path}")

    for entry in sorted(entries):
        click.echo(entry)


# ---------------------------------------------------------------------------
# cat
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("path")
@click.option("--branch", "-b", default="main", help="Branch to read from.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to read from.")
@click.option("--path", "at_path", default=None, help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None, help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None, help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def cat(ctx, path, branch, ref, at_path, match_pattern, before):
    """Print file contents to stdout."""
    repo_path = _normalize_repo_path(_strip_colon(path))

    store = _open_store(_require_repo(ctx))
    before = _parse_before(before)
    fs = _resolve_snapshot(_get_fs(store, branch, ref), at_path, match_pattern, before)

    try:
        data = fs.read(repo_path)
    except FileNotFoundError:
        raise click.ClickException(f"File not found: {repo_path}")
    except IsADirectoryError:
        raise click.ClickException(f"{repo_path} is a directory, not a file")

    sys.stdout.buffer.write(data)


# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("path")
@click.option("--branch", "-b", default="main", help="Branch to remove from.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.pass_context
def rm(ctx, path, branch, message):
    """Remove a file from the repo."""
    store = _open_store(_require_repo(ctx))
    fs = _get_branch_fs(store, branch)

    repo_path = _normalize_repo_path(_strip_colon(path))

    try:
        fs.remove(repo_path, message=message)
    except FileNotFoundError:
        raise click.ClickException(f"File not found: {repo_path}")
    except IsADirectoryError:
        raise click.ClickException(f"{repo_path} is a directory, not a file")
    except StaleSnapshotError:
        raise click.ClickException(
            "Branch modified concurrently — retry"
        )
    _status(ctx, f"Removed :{repo_path}")


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.option("--path", "at_path", default=None, help="Show only commits that changed this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Show only commits matching this message pattern (* and ?).")
@click.option("--before", "before", default=None, help="Show only commits on or before this date (ISO 8601).")
@click.option("--branch", "-b", default="main", help="Branch to show log for.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to start from.")
@click.option("--format", "fmt", default="text",
              type=click.Choice(["text", "json", "jsonl"]),
              help="Output format.")
@click.pass_context
def log(ctx, at_path, deprecated_at, match_pattern, before, branch, ref, fmt):
    """Show commit log, optionally filtered by path and/or message pattern."""
    at_path = at_path or deprecated_at
    store = _open_store(_require_repo(ctx))
    fs = _get_fs(store, branch, ref)

    before = _parse_before(before)
    at_path = _normalize_at_path(at_path)
    entries = list(fs.log(path=at_path, match=match_pattern, before=before))

    if fmt == "json":
        click.echo(json.dumps([_log_entry_dict(e) for e in entries], indent=2))
    elif fmt == "jsonl":
        for entry in entries:
            click.echo(json.dumps(_log_entry_dict(entry)))
    else:
        for entry in entries:
            click.echo(f"{entry.hash[:7]}  {entry.time.isoformat()}  {entry.message}")

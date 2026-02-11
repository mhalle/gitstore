"""Shared helpers, option decorators, and the main CLI group."""

from __future__ import annotations

import json
import os
import sys

import click
from gitstore import _compat as pygit2

from ..exceptions import StaleSnapshotError
from ..repo import GitStore
from ..tree import (
    GIT_FILEMODE_BLOB,
    GIT_FILEMODE_BLOB_EXECUTABLE,
    GIT_FILEMODE_LINK,
    GIT_FILEMODE_TREE,
    _entry_at_path,
    _normalize_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_colon(raw: str) -> str:
    """Strip an optional leading ':' from a repo-side path."""
    return raw[1:] if raw.startswith(":") else raw


def _normalize_repo_path(path: str) -> str:
    """Normalize and validate a repo-side path via the library's _normalize_path."""
    if not path:
        raise click.ClickException("Repo path must not be empty")
    try:
        return _normalize_path(path)
    except ValueError as exc:
        raise click.ClickException(f"Invalid repo path: {exc}")


def _clean_archive_path(raw: str) -> str:
    """Clean an archive entry path for repo import.

    Strips leading './' components that standard tools like ``tar -cf`` add,
    then delegates to ``_normalize_repo_path``.
    """
    # Collapse leading "./" (e.g. "./dir/file.txt" → "dir/file.txt")
    while raw.startswith("./"):
        raw = raw[2:]
    return _normalize_repo_path(raw)


def _status(ctx, msg):
    """Emit a status message to stderr when verbose mode (-v) is on."""
    if ctx.obj.get("verbose"):
        click.echo(msg, err=True)


def _store_repo(ctx, param, value):
    """Click callback: store --repo value in the context."""
    ctx.ensure_object(dict)
    if value is not None:
        ctx.obj["repo_path"] = value
    return value


def _repo_option(f):
    """Shared --repo/-r option decorator for all commands."""
    return click.option(
        "--repo", "-r", type=click.Path(), envvar="GITSTORE_REPO",
        help="Path to bare git repository (or set GITSTORE_REPO).",
        expose_value=False, callback=_store_repo, is_eager=True,
    )(f)


def _require_repo(ctx) -> str:
    """Get the repo path from context, raising a clear error if missing."""
    repo = ctx.obj.get("repo_path")
    if not repo:
        raise click.ClickException(
            "No repository specified. Use --repo or set GITSTORE_REPO."
        )
    return repo


def _default_branch(store: GitStore) -> str:
    """Return the repo's HEAD branch, falling back to 'main'."""
    return store._repo.get_head_branch() or "main"


def _open_store(repo_path: str) -> GitStore:
    try:
        return GitStore.open(repo_path, create=False)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))


def _open_or_create_store(repo_path: str, branch: str = "main") -> GitStore:
    """Open a store, creating it with *branch* if the repo doesn't exist."""
    return GitStore.open(repo_path, branch=branch)


def _open_or_create_bare(repo_path: str) -> GitStore:
    """Open a store, creating a bare repo (no branch) if it doesn't exist."""
    return GitStore.open(repo_path, branch=None)


def _no_create_option(f):
    """Shared --no-create flag for write commands."""
    return click.option(
        "--no-create", "no_create", is_flag=True, default=False,
        help="Do not auto-create the repository if it doesn't exist.",
    )(f)


def _tag_option(f):
    """Shared --tag / --force-tag options for write commands."""
    f = click.option("--force-tag", is_flag=True, default=False,
                     help="Overwrite tag if it already exists.")(f)
    f = click.option("--tag", default=None,
                     help="Create a tag at the resulting commit.")(f)
    return f


def _apply_tag(store: GitStore, new_fs, tag: str, force_tag: bool):
    """Create a tag pointing at *new_fs*, with optional force-overwrite."""
    if force_tag and tag in store.tags:
        del store.tags[tag]
    try:
        store.tags[tag] = new_fs
    except KeyError:
        raise click.ClickException(f"Tag already exists: {tag} (use --force-tag to overwrite)")


def _get_branch_fs(store: GitStore, branch: str):
    try:
        return store.branches[branch]
    except KeyError:
        raise click.ClickException(f"Branch not found: {branch}")


def _get_fs(store: GitStore, branch: str, ref: str | None):
    """Resolve an FS from --ref (any ref) or --branch."""
    if ref:
        return _resolve_ref(store, ref)
    return _get_branch_fs(store, branch)


def _normalize_at_path(at_path: str | None) -> str | None:
    """Normalize a --path filter value, returning None if unset."""
    if at_path is None:
        return None
    return _normalize_repo_path(_strip_colon(at_path))


def _parse_before(value: str | None):
    """Parse a --before value into a timezone-aware datetime, or None."""
    if value is None:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise click.ClickException(
            f"Invalid date: {value} (use ISO 8601, e.g. 2024-01-15 or 2024-01-15T14:30:00)"
        )
    if "T" not in value and "t" not in value:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_snapshot(fs, at_path: str | None, match_pattern: str | None, before=None):
    """Narrow *fs* to the first commit matching --path / --match / --before filters."""
    at_path = _normalize_at_path(at_path)
    if at_path is not None or match_pattern is not None or before is not None:
        for entry in fs.log(path=at_path, match=match_pattern, before=before):
            return entry
        raise click.ClickException("No matching commits found")
    return fs


def _resolve_fs(store, branch, ref=None, *,
                at_path=None, match_pattern=None, before=None, back=0):
    """Resolve an FS from branch/ref + snapshot filters + --back."""
    fs = _get_fs(store, branch, ref)
    before = _parse_before(before)
    fs = _resolve_snapshot(fs, at_path, match_pattern, before)
    if back:
        try:
            fs = fs.back(back)
        except ValueError as e:
            raise click.ClickException(str(e))
    return fs


def _detect_archive_format(filename: str) -> str:
    """Detect archive format from filename extension. Returns 'zip' or 'tar'."""
    lower = filename.lower()
    if lower.endswith(".zip"):
        return "zip"
    if any(lower.endswith(ext) for ext in (
        ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
    )):
        return "tar"
    raise click.ClickException(
        f"Cannot detect archive format from extension: {filename}\n"
        f"Use --format zip or --format tar"
    )


def _resolve_ref(store: GitStore, ref_str: str):
    """Try branches, then tags, then commit hash."""
    if ref_str in store.branches:
        return store.branches[ref_str]
    if ref_str in store.tags:
        return store.tags[ref_str]
    # Try as commit hash
    try:
        repo = store._repo
        obj = repo.get(ref_str)
        if obj is not None:
            if obj.type != pygit2.GIT_OBJECT_COMMIT:
                raise click.ClickException(
                    f"Object {ref_str} is not a commit"
                )
            from ..fs import FS
            return FS(store, obj.id, branch=None)
    except click.ClickException:
        raise
    except (ValueError, KeyError):
        pass
    raise click.ClickException(f"Unknown ref: {ref_str}")


def _log_entry_dict(entry) -> dict:
    return {
        "hash": entry.hash,
        "message": entry.message,
        "time": entry.time.isoformat(),
        "author_name": entry.author_name,
        "author_email": entry.author_email,
        "branch": entry.branch,
    }


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--repo", "-r", type=click.Path(), envvar="GITSTORE_REPO",
              help="Path to bare git repository (or set GITSTORE_REPO).",
              expose_value=False, callback=_store_repo, is_eager=True)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output on stderr.")
@click.pass_context
def main(ctx, verbose):
    """gitstore — a git-backed file store.

    Store and retrieve files in bare git repositories with automatic
    versioning, branching, and tagging. No working tree required.

    \b
    Quick start:
      gitstore init -r data.git
      gitstore cp file.txt :file.txt
      gitstore cat :file.txt
      gitstore ls

    \b
    Common workflows:
      cp / sync       Copy or sync files between disk and repo
      ls / cat        List or read files from the repo
      log / reflog    View commit history or branch pointer history
      branch / tag    Manage branches and tags
      undo / redo     Step through branch history
      archive / zip / tar          Export to archive
      unarchive / unzip / untar    Import from archive
      backup / restore             Mirror to/from a remote URL

    \b
    Repo paths are prefixed with ':' (e.g. :path/to/file).
    Set GITSTORE_REPO to avoid passing --repo on every call.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


# ---------------------------------------------------------------------------
# Branch and tag group shells
# ---------------------------------------------------------------------------

@main.group(invoke_without_command=True)
@_repo_option
@click.pass_context
def branch(ctx):
    """Manage branches."""
    if ctx.invoked_subcommand is None:
        # Defer to _refs module's branch_list; imported at registration time
        ctx.invoke(branch_list)


@main.group(invoke_without_command=True)
@_repo_option
@click.pass_context
def tag(ctx):
    """Manage tags."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(tag_list)


# These will be set by _refs.py during import to avoid circular dependency
branch_list = None
tag_list = None

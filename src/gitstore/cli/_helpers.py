"""Shared helpers, option decorators, and the main CLI group."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

import click

from ..exceptions import StaleSnapshotError
from ..repo import GitStore
from ..tree import (
    _entry_at_path,
    _normalize_path,
)


# ---------------------------------------------------------------------------
# RefPath parsing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RefPath:
    """Parsed ``ref:path`` specification.

    * ``ref is None`` → local filesystem path
    * ``ref == ""``   → current/default branch
    * ``ref == "xyz"`` → explicit branch/tag/commit
    """
    ref: str | None
    back: int
    path: str

    @property
    def is_repo(self) -> bool:
        return self.ref is not None


def _parse_ref_path(raw: str) -> RefPath:
    """Parse a ``ref:path`` string into a :class:`RefPath`.

    Rules (in order):
    1. No ``:`` → local path.
    2. Starts with ``:`` → current branch, ``path = raw[1:]``.
    3. ``:`` at position > 0:
       - Single letter before ``:`` AND next char is ``\\`` or ``/`` → local (Windows drive).
       - ``/`` or ``\\`` anywhere before the ``:`` → local (filesystem path containing ``:``).
       - Otherwise → parse ref portion for ``~N`` ancestor suffix.
    """
    colon = raw.find(":")
    if colon < 0:
        # No colon → local
        return RefPath(ref=None, back=0, path=raw)
    if colon == 0:
        # Starts with : → current branch
        return RefPath(ref="", back=0, path=raw[1:])

    before = raw[:colon]
    after = raw[colon + 1:]

    # Windows drive letter: single char + next is / or backslash
    if len(before) == 1 and before.isalpha() and after and after[0] in ("/", "\\"):
        return RefPath(ref=None, back=0, path=raw)

    # Slash or backslash before colon → local filesystem path
    if "/" in before or "\\" in before:
        return RefPath(ref=None, back=0, path=raw)

    # It's a ref:path — parse ~N ancestor suffix
    ref_part = before
    back = 0
    tilde = ref_part.rfind("~")
    if tilde >= 0:
        suffix = ref_part[tilde + 1:]
        if not suffix.isdigit():
            raise click.ClickException(
                f"Invalid ancestor suffix '~{suffix}' — must be a positive integer"
            )
        n = int(suffix)
        if n == 0:
            raise click.ClickException(
                f"Invalid ancestor '~0' — use '{ref_part[:tilde]}:{after}' instead"
            )
        ref_part = ref_part[:tilde]
        back = n

    return RefPath(ref=ref_part, back=back, path=after)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_colon(raw: str) -> str:
    """Strip an optional leading ':' from a repo-side path."""
    return _parse_ref_path(raw).path


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


def _current_branch(store: GitStore) -> str:
    """Return the repo's HEAD branch, falling back to 'main'."""
    return store.branches.current_name or "main"


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


def _snapshot_options(f):
    """Shared snapshot filter options: --ref, --path, --match, --before, --back."""
    f = click.option("--back", type=int, default=0,
                     help="Walk back N commits.")(f)
    f = click.option("--before", "before", default=None,
                     help="Use latest commit on or before this date (ISO 8601).")(f)
    f = click.option("--match", "match_pattern", default=None,
                     help="Use latest commit matching this message pattern (* and ?).")(f)
    f = click.option("--path", "at_path", default=None,
                     help="Use latest commit that changed this path.")(f)
    f = click.option("--ref", "ref", default=None,
                     help="Branch, tag, or commit hash to read from.")(f)
    return f


def _tag_option(f):
    """Shared --tag / --force-tag options for write commands."""
    f = click.option("--force-tag", is_flag=True, default=False,
                     help="Overwrite tag if it already exists.")(f)
    f = click.option("--tag", default=None,
                     help="Create a tag at the resulting commit.")(f)
    return f


def _branch_option(f):
    """Shared --branch/-b option for commands that operate on a branch."""
    return click.option(
        "--branch", "-b", default=None,
        help="Branch (defaults to repo's default branch).",
    )(f)


def _message_option(f):
    """Shared -m/--message option for write commands."""
    return click.option(
        "-m", "--message", default=None,
        help="Commit message. Use {default} to include auto-generated message.",
    )(f)


def _dry_run_option(f):
    """Shared -n/--dry-run option."""
    return click.option(
        "-n", "--dry-run", "dry_run", is_flag=True, default=False,
        help="Show what would change without writing.",
    )(f)


def _checksum_option(f):
    """Shared -c/--checksum option for cp/sync."""
    return click.option(
        "-c", "--checksum", is_flag=True, default=False,
        help="Compare files by checksum instead of mtime (slower, exact).",
    )(f)


def _ignore_errors_option(f):
    """Shared --ignore-errors option for cp/sync."""
    return click.option(
        "--ignore-errors", is_flag=True, default=False,
        help="Skip files that fail and continue.",
    )(f)


def _no_glob_option(f):
    """Shared --no-glob option for cp/rm/mv."""
    return click.option(
        "--no-glob", "no_glob", is_flag=True, default=False,
        help="Treat source paths as literal (no * or ? expansion).",
    )(f)


def _format_option(f):
    """Shared --format option for log/reflog output."""
    return click.option(
        "--format", "fmt", default="text",
        type=click.Choice(["text", "json", "jsonl"]),
        help="Output format.",
    )(f)


def _archive_format_option(f):
    """Shared --format option for archive/unarchive."""
    return click.option(
        "--format", "fmt", type=click.Choice(["zip", "tar"]), default=None,
        help="Archive format (auto-detected from extension if omitted).",
    )(f)


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


def _apply_snapshot_filters(fs, *, at_path=None, match_pattern=None, before=None, back=0):
    """Apply --path / --match / --before / --back filters to an already-resolved FS."""
    before = _parse_before(before)
    fs = _resolve_snapshot(fs, at_path, match_pattern, before)
    if back:
        try:
            fs = fs.back(back)
        except ValueError as e:
            raise click.ClickException(str(e))
    return fs


def _resolve_fs(store, branch, ref=None, *,
                at_path=None, match_pattern=None, before=None, back=0):
    """Resolve an FS from branch/ref + snapshot filters + --back."""
    fs = _get_fs(store, branch, ref)
    return _apply_snapshot_filters(fs, at_path=at_path, match_pattern=match_pattern,
                                   before=before, back=back)


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
            if obj.type_num != 1:  # GIT_OBJECT_COMMIT
                raise click.ClickException(
                    f"Object {ref_str} is not a commit"
                )
            from ..fs import FS
            return FS(store, obj.id, writable=False)
    except click.ClickException:
        raise
    except (ValueError, KeyError):
        pass
    raise click.ClickException(f"Unknown ref: {ref_str}")


def _resolve_ref_path(store: GitStore, rp: RefPath, default_ref: str | None, default_branch: str, *,
                      at_path=None, match_pattern=None, before=None, back=0):
    """Resolve a :class:`RefPath` to an FS.

    * ``rp.ref == ""`` → use *default_ref* if set, else *default_branch*
    * ``rp.ref`` non-empty → call :func:`_resolve_ref`
    * Then walk back ``rp.back`` parents.
    * Then apply remaining snapshot filters (*at_path*, *match_pattern*, *before*, *back*).
    """
    if rp.ref == "":
        fs = _get_fs(store, default_branch, default_ref)
    else:
        fs = _resolve_ref(store, rp.ref)
    if rp.back:
        try:
            fs = fs.back(rp.back)
        except ValueError as e:
            raise click.ClickException(str(e))
    return _apply_snapshot_filters(fs, at_path=at_path, match_pattern=match_pattern,
                                   before=before, back=back)


def _check_ref_conflicts(parsed_paths, *, ref=None, branch=None, back=0,
                         before=None, at_path=None, match_pattern=None):
    """Raise if explicit ``ref:path`` conflicts with ``--ref``, ``-b``, or ``--back``."""
    repo_paths = [rp for rp in parsed_paths if rp and rp.is_repo]
    explicit_ref_paths = [rp for rp in repo_paths if rp.ref]
    tilde_paths = [rp for rp in repo_paths if rp.back]

    if explicit_ref_paths:
        if ref:
            raise click.ClickException("Cannot use --ref with explicit ref: in path")
        if branch is not None:
            raise click.ClickException("Cannot use -b/--branch with explicit ref: in path")

    if tilde_paths and back:
        raise click.ClickException("Cannot use --back with ~N in path")

    explicit_refs = {rp.ref for rp in explicit_ref_paths}
    has_filters = back or before or at_path or match_pattern
    if len(explicit_refs) > 1 and has_filters:
        raise click.ClickException(
            "Cannot use snapshot filters with paths targeting different refs"
        )


def _resolve_same_branch(
    store: GitStore,
    parsed: list[RefPath],
    default_branch: str,
    *,
    operation: str = "modify",
) -> str:
    """Ensure all explicit refs in *parsed* target the same branch.

    Returns the resolved branch name.  Raises :class:`click.ClickException`
    when a ref is a tag, not found, or when multiple different refs are used.
    """
    explicit_ref: str | None = None
    for rp in parsed:
        if rp.ref:
            if rp.ref not in store.branches:
                if rp.ref in store.tags:
                    raise click.ClickException(
                        f"Cannot {operation} in tag '{rp.ref}' — use a branch"
                    )
                raise click.ClickException(f"Branch not found: {rp.ref}")
            if explicit_ref is not None and explicit_ref != rp.ref:
                raise click.ClickException(
                    "All paths must target the same branch"
                )
            explicit_ref = rp.ref
    return explicit_ref if explicit_ref is not None else default_branch


def _require_writable_ref(store: GitStore, rp: RefPath, default_branch: str) -> tuple:
    """Resolve a repo dest :class:`RefPath` to ``(FS, branch_name)``.

    Ensures the ref is a branch (not tag/hash) and ``back == 0``.
    """
    if rp.back:
        raise click.ClickException("Cannot write to a historical commit (remove ~N from destination)")
    if rp.ref == "":
        branch = default_branch
    elif rp.ref in store.branches:
        branch = rp.ref
    else:
        if rp.ref in store.tags:
            raise click.ClickException(f"Cannot write to tag '{rp.ref}' — use a branch")
        raise click.ClickException(f"Branch not found: {rp.ref}")
    fs = _get_branch_fs(store, branch)
    return fs, branch


def _log_entry_dict(entry) -> dict:
    return {
        "hash": entry.commit_hash,
        "message": entry.message,
        "time": entry.time.isoformat(),
        "author_name": entry.author_name,
        "author_email": entry.author_email,
        "branch": entry.ref_name,
    }


# ---------------------------------------------------------------------------
# Glob expansion for CLI (pre-expand before calling library)
# ---------------------------------------------------------------------------

def _expand_sources_repo(fs, sources: list[str]) -> list[str]:
    """Expand glob patterns in repo sources using ``fs.glob()``.

    Non-glob sources are passed through unchanged.  Raises
    :exc:`FileNotFoundError` when a glob pattern matches nothing.
    """
    result: list[str] = []
    for src in sources:
        if "*" in src or "?" in src:
            expanded = fs.glob(src)
            if not expanded:
                raise FileNotFoundError(
                    f"No matches for pattern in repo: {src}")
            result.extend(expanded)
        else:
            result.append(src)
    return result


def _expand_sources_disk(sources: list[str]) -> list[str]:
    """Expand glob patterns in disk sources using :func:`disk_glob`.

    Non-glob sources are passed through unchanged.  Raises
    :exc:`FileNotFoundError` when a glob pattern matches nothing.
    """
    from ..copy._resolve import disk_glob

    result: list[str] = []
    for src in sources:
        if "*" in src or "?" in src:
            expanded = disk_glob(src)
            if not expanded:
                raise FileNotFoundError(
                    f"No matches for pattern: {src}")
            result.extend(expanded)
        else:
            result.append(src)
    return result


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="gitstore")
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

"""Basic commands: init, destroy, ls, cat, rm, write, log."""

from __future__ import annotations

import io
import json
import os
import sys

import click

from ..copy._resolve import _walk_repo
from ..exceptions import StaleSnapshotError
from ..repo import GitStore
from ..tree import _normalize_path
from ._helpers import (
    main,
    RefPath,
    _parse_ref_path,
    _resolve_ref_path,
    _require_writable_ref,
    _check_ref_conflicts,
    _repo_option,
    _branch_option,
    _message_option,
    _dry_run_option,
    _format_option,
    _require_repo,
    _status,
    _strip_colon,
    _normalize_repo_path,
    _open_store,
    _open_or_create_store,
    _default_branch,
    _get_branch_fs,
    _get_fs,
    _normalize_at_path,
    _parse_before,
    _resolve_fs,
    _resolve_snapshot,
    _log_entry_dict,
    _no_create_option,
    _snapshot_options,
    _tag_option,
    _apply_tag,
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
    elif os.path.exists(repo_path):
        raise click.ClickException(f"Repository already exists: {repo_path}")
    GitStore.open(repo_path, branch=branch)
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
        store = GitStore.open(repo_path, create=False)
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
# gc
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.pass_context
def gc(ctx):
    """Run garbage collection on the repository.

    Removes unreachable objects (orphaned blobs, etc.) and repacks
    the object store.  Requires git to be installed.
    """
    import shutil
    import subprocess

    repo_path = _require_repo(ctx)
    if not os.path.exists(repo_path):
        raise click.ClickException(f"Repository not found: {repo_path}")

    git = shutil.which("git")
    if git is None:
        raise click.ClickException(
            "git is not installed or not on PATH — gc requires git"
        )

    result = subprocess.run(
        [git, "gc"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise click.ClickException(f"git gc failed: {msg}")

    _status(ctx, f"gc: {repo_path}")


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("paths", nargs=-1)
@_branch_option
@click.option("-R", "--recursive", is_flag=True, help="List all files recursively with full paths.")
@_snapshot_options
@click.pass_context
def ls(ctx, paths, branch, recursive, ref, at_path, match_pattern, before, back):
    """List files/directories at PATH(s) (or root).

    Accepts multiple paths and glob patterns.  Results are coalesced and
    deduplicated.  Quote glob patterns to prevent shell expansion.

    \b
    Examples:
        gitstore ls                         # root listing
        gitstore ls :src                    # subdirectory
        gitstore ls '*.txt' '*.py'          # multiple globs
        gitstore ls :src :docs              # multiple directories
        gitstore ls -R                      # all files recursively
        gitstore ls -R :src :docs           # recursive under multiple dirs
    """
    store = _open_store(_require_repo(ctx))

    # Parse paths and check for conflicts with flags
    if paths:
        parsed = [_parse_ref_path(p) for p in paths]
        _check_ref_conflicts(parsed, ref=ref, branch=branch, back=back,
                             before=before, at_path=at_path, match_pattern=match_pattern)
    else:
        parsed = []

    branch = branch or _default_branch(store)
    default_fs = _resolve_fs(store, branch, ref, at_path=at_path,
                             match_pattern=match_pattern, before=before, back=back)

    # No args → list root (single implicit path)
    if not paths:
        paths = (None,)

    results: set[str] = set()

    for i, path in enumerate(paths):
        # Resolve per-path ref
        if path is not None:
            rp = parsed[i]
            if rp.is_repo and (rp.ref or rp.back):
                fs = _resolve_ref_path(store, rp, ref, branch,
                                       at_path=at_path, match_pattern=match_pattern,
                                       before=before, back=back)
            else:
                fs = default_fs
            repo_path = rp.path if rp.is_repo else path
        else:
            fs = default_fs
            repo_path = None

        has_glob = repo_path is not None and ("*" in repo_path or "?" in repo_path)

        if has_glob:
            pattern = repo_path
            matches = fs.iglob(pattern)
            if recursive:
                for m in matches:
                    if fs.is_dir(m):
                        for dp, _, fnames in fs.walk(m):
                            for f in fnames:
                                results.add(f"{dp}/{f}" if dp else f)
                    else:
                        results.add(m)
            else:
                results.update(matches)

        elif recursive:
            rp_norm = None
            if repo_path:
                rp_norm = _normalize_repo_path(repo_path)
            try:
                for dp, _, fnames in fs.walk(rp_norm if rp_norm else None):
                    for f in fnames:
                        results.add(f"{dp}/{f}" if dp else f)
            except FileNotFoundError:
                raise click.ClickException(f"Path not found: {rp_norm}")
            except NotADirectoryError:
                results.add(rp_norm)

        else:
            rp_norm = None
            if repo_path:
                rp_norm = _normalize_repo_path(repo_path)
            try:
                results.update(fs.ls(rp_norm if rp_norm else None))
            except FileNotFoundError:
                raise click.ClickException(f"Path not found: {rp_norm}")
            except NotADirectoryError:
                results.add(rp_norm)

    for entry in results:
        click.echo(entry)


# ---------------------------------------------------------------------------
# cat
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("paths", nargs=-1, required=True)
@_branch_option
@_snapshot_options
@click.pass_context
def cat(ctx, paths, branch, ref, at_path, match_pattern, before, back):
    """Concatenate file contents to stdout."""
    store = _open_store(_require_repo(ctx))

    # Parse paths and check for conflicts with flags
    parsed = [_parse_ref_path(p) for p in paths]
    _check_ref_conflicts(parsed, ref=ref, branch=branch, back=back,
                         before=before, at_path=at_path, match_pattern=match_pattern)

    branch = branch or _default_branch(store)
    default_fs = _resolve_fs(store, branch, ref, at_path=at_path,
                             match_pattern=match_pattern, before=before, back=back)

    for i, path in enumerate(paths):
        rp = parsed[i]
        if rp.is_repo and (rp.ref or rp.back):
            fs = _resolve_ref_path(store, rp, ref, branch,
                                   at_path=at_path, match_pattern=match_pattern,
                                   before=before, back=back)
        else:
            fs = default_fs
        repo_path = _normalize_repo_path(rp.path if rp.is_repo else path)
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
@click.argument("paths", nargs=-1, required=True)
@click.option("-R", "--recursive", is_flag=True, default=False,
              help="Remove directories recursively.")
@_dry_run_option
@_branch_option
@_message_option
@_tag_option
@click.pass_context
def rm(ctx, paths, recursive, dry_run, branch, message, tag, force_tag):
    """Remove files from the repo.

    Accepts multiple paths and glob patterns.  Quote glob patterns to
    prevent shell expansion.  Directories require -R.

    \b
    Examples:
        gitstore rm :file.txt
        gitstore rm ':*.txt'
        gitstore rm -R :dir
        gitstore rm -n :file.txt         # dry run
        gitstore rm :a.txt :b.txt        # multiple
    """
    from ..copy import remove_from_repo, remove_from_repo_dry_run

    store = _open_store(_require_repo(ctx))
    branch = branch or _default_branch(store)

    # Parse all paths — all explicit refs must resolve to the same branch
    resolved_branch = branch
    for p in paths:
        rp = _parse_ref_path(p)
        if rp.is_repo and rp.ref:
            if rp.ref not in store.branches:
                if rp.ref in store.tags:
                    raise click.ClickException(f"Cannot remove from tag '{rp.ref}' — use a branch")
                raise click.ClickException(f"Branch not found: {rp.ref}")
            if resolved_branch != branch and resolved_branch != rp.ref:
                raise click.ClickException("All paths must target the same branch")
            resolved_branch = rp.ref

    branch = resolved_branch
    fs = _get_branch_fs(store, branch)

    patterns = [_normalize_repo_path(_parse_ref_path(p).path if _parse_ref_path(p).is_repo else p)
                for p in paths]

    try:
        if dry_run:
            report = remove_from_repo_dry_run(fs, patterns, recursive=recursive)
            if report:
                for action in report.actions():
                    click.echo(f"- :{action.path}")
        else:
            new_fs = remove_from_repo(fs, patterns, recursive=recursive,
                                      message=message)
            if tag:
                _apply_tag(store, new_fs, tag, force_tag)
            report = new_fs.report
            n = len(report.delete) if report else 0
            _status(ctx, f"Removed {n} file(s)")
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))
    except IsADirectoryError as exc:
        raise click.ClickException(f"{exc} — use -R to remove recursively")
    except StaleSnapshotError:
        raise click.ClickException(
            "Branch modified concurrently — retry"
        )


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("path")
@_branch_option
@_message_option
@_no_create_option
@_tag_option
@click.option("-p", "--passthrough", is_flag=True, default=False,
              help="Echo stdin to stdout (tee mode for pipelines).")
@click.pass_context
def write(ctx, path, branch, message, no_create, tag, force_tag, passthrough):
    """Write stdin to a file in the repo."""
    from ..fs import retry_write

    # Parse ref:path — explicit ref overrides -b
    rp = _parse_ref_path(path)
    if rp.is_repo and rp.ref:
        branch = rp.ref
    if rp.is_repo and rp.back:
        raise click.ClickException("Cannot write to a historical commit (remove ~N)")

    # Stage 1: open store, resolve branch name (no FS fetch yet)
    repo_path = _require_repo(ctx)
    if no_create:
        store = _open_store(repo_path)
        branch = branch or _default_branch(store)
    else:
        store = _open_or_create_store(repo_path, branch=branch or "main")
        branch = branch or _default_branch(store)

    repo_path_norm = _normalize_repo_path(rp.path if rp.is_repo else _strip_colon(path))

    # Stage 2: read stdin (may take arbitrarily long — no stale FS held)
    if passthrough:
        buf = io.BytesIO()
        stdout = sys.stdout.buffer
        stdin = sys.stdin.buffer
        _read = getattr(stdin, 'read1', stdin.read)
        while True:
            chunk = _read(8192)
            if not chunk:
                break
            stdout.write(chunk)
            stdout.flush()
            buf.write(chunk)
        data = buf.getvalue()
    else:
        data = sys.stdin.buffer.read()

    # Stage 3: commit (fetches fresh FS internally, retries on stale)
    try:
        new_fs = retry_write(store, branch, repo_path_norm, data, message=message)
    except StaleSnapshotError:
        raise click.ClickException(
            "Branch modified concurrently — failed after retries"
        )
    except KeyError:
        raise click.ClickException(f"Branch not found: {branch}")
    if tag:
        _apply_tag(store, new_fs, tag, force_tag)
    _status(ctx, f"Wrote :{repo_path_norm}")


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("target", required=False, default=None)
@click.option("--at", "deprecated_at", default=None, hidden=True)
@_branch_option
@_snapshot_options
@_format_option
@click.pass_context
def log(ctx, target, at_path, deprecated_at, match_pattern, before, branch, ref, back, fmt):
    """Show commit log, optionally filtered by path and/or message pattern.

    \b
    An optional TARGET argument supports ref:path syntax:
        gitstore log main:config.json   →  --ref main --path config.json
        gitstore log main~3:            →  --ref main --back 3
        gitstore log ~3:config.json     →  --back 3 --path config.json
    """
    at_path = at_path or deprecated_at

    # Parse optional positional target
    if target is not None:
        rp = _parse_ref_path(target)
        if rp.is_repo:
            if rp.ref and ref:
                raise click.ClickException("Cannot specify both positional ref and --ref")
            if rp.ref and branch is not None:
                raise click.ClickException("Cannot use -b/--branch with explicit ref: in target")
            if rp.back and back:
                raise click.ClickException("Cannot specify both positional ~N and --back")
            if rp.path and at_path:
                raise click.ClickException("Cannot specify both positional path and --path")
            if rp.ref:
                ref = rp.ref
            if rp.back:
                back = rp.back
            if rp.path:
                at_path = rp.path
        else:
            # Not a repo path — treat the whole thing as a --path filter
            if at_path:
                raise click.ClickException("Cannot specify both positional path and --path")
            at_path = target

    store = _open_store(_require_repo(ctx))
    branch = branch or _default_branch(store)
    fs = _get_fs(store, branch, ref)
    if back:
        try:
            fs = fs.back(back)
        except ValueError as e:
            raise click.ClickException(str(e))

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


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("baseline", required=False, default=None)
@_branch_option
@_snapshot_options
@click.option("--reverse", is_flag=True, help="Swap comparison direction.")
@click.pass_context
def diff(ctx, baseline, branch, ref, at_path, match_pattern, before, back, reverse):
    """Show files that differ between HEAD and another snapshot.

    \b
    An optional BASELINE argument supports ref:path syntax:
        gitstore diff ~3:     →  --back 3
        gitstore diff dev:    →  --ref dev
    """
    # Parse optional positional baseline
    if baseline is not None:
        rp = _parse_ref_path(baseline)
        if rp.is_repo:
            if rp.ref and ref:
                raise click.ClickException("Cannot specify both positional ref and --ref")
            if rp.ref and branch is not None:
                raise click.ClickException("Cannot use -b/--branch with explicit ref: in baseline")
            if rp.back and back:
                raise click.ClickException("Cannot specify both positional ~N and --back")
            if rp.path and at_path:
                raise click.ClickException("Cannot specify both positional path and --path")
            if rp.ref:
                ref = rp.ref
            if rp.back:
                back = rp.back
            if rp.path:
                at_path = rp.path

    store = _open_store(_require_repo(ctx))
    branch = branch or _default_branch(store)
    head_fs = _get_fs(store, branch, None)
    other_fs = _resolve_fs(store, branch, ref, at_path=at_path,
                           match_pattern=match_pattern, before=before, back=back)
    if head_fs.hash == other_fs.hash:
        return
    new_files = _walk_repo(head_fs, "")
    old_files = _walk_repo(other_fs, "")
    if reverse:
        new_files, old_files = old_files, new_files
    for p in sorted(set(new_files) - set(old_files)):
        click.echo(f"A  {p}")
    for p in sorted(set(new_files) & set(old_files)):
        if new_files[p] != old_files[p]:
            click.echo(f"M  {p}")
    for p in sorted(set(old_files) - set(new_files)):
        click.echo(f"D  {p}")


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@_branch_option
@click.argument("steps", type=int, default=1, required=False)
@click.pass_context
def undo(ctx, branch, steps):
    """Move branch back N commits (default 1).

    Walks back through parent commits and updates the branch pointer.
    Creates a reflog entry so you can redo later.

    Examples:
        gitstore --repo data.git undo       # Back 1 commit
        gitstore --repo data.git undo 3     # Back 3 commits
        gitstore --repo data.git undo -b dev 2  # Undo 2 on 'dev' branch
    """
    repo_path = _require_repo(ctx)

    try:
        repo = GitStore.open(repo_path, create=False)
        branch = branch or _default_branch(repo)
        fs = repo.branches[branch]

        # Perform undo
        new_fs = fs.undo(steps)

        # Show what happened
        if steps == 1:
            click.echo(f"Undid 1 commit on '{branch}'")
        else:
            click.echo(f"Undid {steps} commits on '{branch}'")
        click.echo(f"Branch now at: {new_fs.hash[:7]} - {new_fs.message}")

    except KeyError:
        raise click.ClickException(f"Branch {branch!r} not found")
    except ValueError as e:
        raise click.ClickException(str(e))
    except PermissionError as e:
        raise click.ClickException(str(e))


# ---------------------------------------------------------------------------
# redo
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@_branch_option
@click.argument("steps", type=int, default=1, required=False)
@click.pass_context
def redo(ctx, branch, steps):
    """Move branch forward N steps in reflog (default 1).

    Uses the reflog to find where the branch was in the future and moves
    there. Can resurrect commits after undo or divergence.

    Examples:
        gitstore --repo data.git redo       # Forward 1 step
        gitstore --repo data.git redo 2     # Forward 2 steps
        gitstore --repo data.git redo -b dev  # Redo on 'dev' branch
    """
    repo_path = _require_repo(ctx)

    try:
        repo = GitStore.open(repo_path, create=False)
        branch = branch or _default_branch(repo)
        fs = repo.branches[branch]

        # Perform redo
        new_fs = fs.redo(steps)

        # Show what happened
        if steps == 1:
            click.echo(f"Redid 1 step on '{branch}'")
        else:
            click.echo(f"Redid {steps} steps on '{branch}'")
        click.echo(f"Branch now at: {new_fs.hash[:7]} - {new_fs.message}")

    except KeyError:
        raise click.ClickException(f"Branch {branch!r} not found")
    except ValueError as e:
        raise click.ClickException(str(e))
    except PermissionError as e:
        raise click.ClickException(str(e))
    except FileNotFoundError as e:
        raise click.ClickException(str(e))


# ---------------------------------------------------------------------------
# reflog
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@_branch_option
@click.option("-n", "--limit", type=int, help="Limit number of entries shown.")
@_format_option
@click.pass_context
def reflog(ctx, branch, limit, fmt):
    """Show reflog entries for a branch.

    The reflog shows chronological history of where the branch pointer
    has been, including undos and branch updates. This is different from
    'log' which shows the commit tree.

    Examples:
        gitstore --repo data.git reflog              # Show all entries (text)
        gitstore --repo data.git reflog -n 10        # Show last 10
        gitstore --repo data.git reflog -b dev       # Show for 'dev' branch
        gitstore --repo data.git reflog --format json   # JSON output
        gitstore --repo data.git reflog --format jsonl  # JSON Lines output
    """
    repo_path = _require_repo(ctx)

    try:
        repo = GitStore.open(repo_path, create=False)
        branch = branch or _default_branch(repo)
        entries = repo.branches.reflog(branch)

        # Apply limit if specified
        if limit:
            entries = entries[-limit:]

        # Handle empty reflog
        if not entries:
            if fmt == "json":
                click.echo("[]")
            elif fmt == "jsonl":
                pass  # No output for empty
            else:
                click.echo(f"No reflog entries for branch '{branch}'")
            return

        # Output in requested format
        if fmt == "json":
            click.echo(json.dumps(entries, indent=2))
        elif fmt == "jsonl":
            for entry in entries:
                click.echo(json.dumps(entry))
        else:
            # Text format (default)
            import datetime
            click.echo(f"Reflog for branch '{branch}' ({len(entries)} entries):\n")

            for i, entry in enumerate(entries):
                new = entry['new_sha'][:7]
                msg = entry['message']

                # Format timestamp
                ts = datetime.datetime.fromtimestamp(entry['timestamp'])
                time_str = ts.strftime("%Y-%m-%d %H:%M:%S")

                click.echo(f"  [{i}] {new} ({time_str})")
                click.echo(f"      {msg}")
                click.echo()

    except KeyError:
        raise click.ClickException(f"Branch {branch!r} not found")
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

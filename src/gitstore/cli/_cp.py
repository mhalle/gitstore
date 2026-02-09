"""The cp command."""

from __future__ import annotations

import os
from pathlib import Path

import click

from ..exceptions import StaleSnapshotError
from ..tree import GIT_FILEMODE_BLOB, GIT_FILEMODE_BLOB_EXECUTABLE, GIT_FILEMODE_LINK, _entry_at_path
from ._helpers import (
    main,
    _repo_option,
    _no_create_option,
    _require_repo,
    _status,
    _normalize_repo_path,
    _open_store,
    _open_or_create_store,
    _get_fs,
    _parse_before,
    _resolve_snapshot,
)


@main.command()
@_repo_option
@click.argument("args", nargs=-1, required=True)
@click.option("--branch", "-b", default="main", help="Branch to operate on.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to read from.")
@click.option("--path", "at_path", default=None, help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None, help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None, help="Use latest commit on or before this date (ISO 8601).")
@click.option("-m", "message", default=None, help="Commit message.")
@click.option("--mode", type=click.Choice(["644", "755"]), default=None,
              help="File mode (default: 644).")
@click.option("--follow-symlinks", is_flag=True, default=False,
              help="Follow symlinks instead of preserving them (disk→repo only).")
@click.option("-n", "--dry-run", "dry_run", is_flag=True, default=False,
              help="Show what would be copied without writing.")
@click.option("--ignore-existing", is_flag=True, default=False,
              help="Skip files that already exist at the destination.")
@click.option("--delete", is_flag=True, default=False,
              help="Delete destination files not present in source (like rsync --delete).")
@click.option("--ignore-errors", is_flag=True, default=False,
              help="Skip files that fail and continue copying.")
@_no_create_option
@click.pass_context
def cp(ctx, args, branch, ref, at_path, match_pattern, before, message, mode, follow_symlinks, dry_run, ignore_existing, delete, ignore_errors, no_create):
    """Copy files and directories between disk and repo.

    Requires --repo or GITSTORE_REPO environment variable.

    The last argument is the destination; all preceding arguments are sources.
    Sources must all be the same type (all repo or all local), and the
    destination must be the opposite type.

    Directories are copied recursively with their name preserved.
    A trailing '/' on a source means "contents of" (like rsync).
    Glob patterns (* and ?) are expanded; they do not match leading dots.

    Prefix repo-side paths with ':'.

    Examples:

        gitstore --repo path/to/repo.git cp file.txt :
        gitstore --repo path/to/repo.git cp :file.txt ./
        gitstore --repo path/to/repo.git cp '*.jpg' :images/
    """
    from ..copy import (
        copy_to_repo, copy_from_repo,
        copy_to_repo_dry_run, copy_from_repo_dry_run,
    )

    if len(args) < 2:
        raise click.ClickException("cp requires at least two arguments (SRC... DEST)")

    raw_sources = args[:-1]
    raw_dest = args[-1]

    # Determine direction
    dest_is_repo = raw_dest.startswith(":")
    src_is_repo = raw_sources[0].startswith(":")
    if any((s.startswith(":")) != src_is_repo for s in raw_sources):
        raise click.ClickException(
            "All source paths must be the same type (all repo or all local)"
        )
    if src_is_repo == dest_is_repo:
        if src_is_repo:
            raise click.ClickException(
                "Both sources and DEST are repo paths — one side must be local"
            )
        raise click.ClickException(
            "Neither sources nor DEST is a repo path — prefix repo paths with ':'"
        )

    has_snapshot_filters = ref or at_path or match_pattern or before
    if has_snapshot_filters and not src_is_repo:
        raise click.ClickException(
            "--hash/--path/--match/--before only apply when reading from repo"
        )

    repo_path = _require_repo(ctx)
    if not src_is_repo and not dry_run and not no_create:
        store = _open_or_create_store(repo_path, branch)
    else:
        store = _open_store(repo_path)
    before = _parse_before(before)
    fs = _resolve_snapshot(_get_fs(store, branch, ref), at_path, match_pattern, before)

    filemode = (GIT_FILEMODE_BLOB_EXECUTABLE if mode == "755"
                else GIT_FILEMODE_BLOB) if mode else None

    # Detect single-plain-file case (no glob, no trailing slash, no directory).
    # In this case, like standard `cp`, the dest is the exact path, not a
    # parent directory.
    single_file_src = (
        len(raw_sources) == 1
        and "*" not in raw_sources[0] and "?" not in raw_sources[0]
        and not raw_sources[0].endswith("/")
    )

    if not src_is_repo:
        # Disk → repo
        dest_path = raw_dest[1:]  # strip leading ':'
        if dest_path:
            dest_path = dest_path.rstrip("/")
            if dest_path:
                dest_path = _normalize_repo_path(dest_path)

        src_raw = raw_sources[0]
        is_single_file = single_file_src and os.path.isfile(src_raw)

        if is_single_file:
            if delete:
                raise click.ClickException(
                    "Cannot use --delete with a single file source."
                )
            # Single file: dest is the exact repo path, unless dest is an
            # existing directory — then place the file inside it.
            local = Path(src_raw)
            if dest_path and fs.is_dir(dest_path):
                repo_file = _normalize_repo_path(f"{dest_path}/{local.name}")
            elif dest_path:
                repo_file = dest_path
            else:
                repo_file = _normalize_repo_path(local.name)
            if ignore_existing and fs.exists(repo_file):
                return
            try:
                if dry_run:
                    click.echo(f"{local} -> :{repo_file}")
                else:
                    with fs.batch(message=message, operation="cp") as b:
                        b.write_from(repo_file, local, mode=filemode)
                    _status(ctx, f"Copied -> :{repo_file}")
            except (FileNotFoundError, OSError) as exc:
                if ignore_errors:
                    click.echo(f"ERROR: {local}: {exc}", err=True)
                    ctx.exit(1)
                else:
                    raise click.ClickException(str(exc))
            except StaleSnapshotError:
                raise click.ClickException("Branch modified concurrently — retry")
        else:
            source_paths = list(raw_sources)
            try:
                if dry_run:
                    report = copy_to_repo_dry_run(
                        fs, source_paths, dest_path,
                        follow_symlinks=follow_symlinks,
                        ignore_existing=ignore_existing,
                        delete=delete,
                    )
                    if report:
                        for w in report.warnings:
                            click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                        for action in report.actions():
                            prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                            if dest_path and action.path:
                                click.echo(f"{prefix} :{dest_path}/{action.path}")
                            else:
                                click.echo(f"{prefix} :{dest_path or ''}{action.path}")
                else:
                    _new_fs = copy_to_repo(
                        fs, source_paths, dest_path,
                        follow_symlinks=follow_symlinks,
                        message=message, mode=filemode,
                        ignore_existing=ignore_existing,
                        delete=delete,
                        ignore_errors=ignore_errors,
                    )
                    report = _new_fs.report
                    if report:
                        for w in report.warnings:
                            click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                        for e in report.errors:
                            click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                    _status(ctx, f"Copied -> :{dest_path or '/'}")
                    if report and report.errors:
                        ctx.exit(1)
            except (FileNotFoundError, NotADirectoryError) as exc:
                raise click.ClickException(str(exc))
            except StaleSnapshotError:
                raise click.ClickException("Branch modified concurrently — retry")
    else:
        # Repo → disk
        source_paths = [s[1:] for s in raw_sources]  # strip ':'
        dest_path = raw_dest

        src_raw = source_paths[0]
        is_single_repo_file = (
            single_file_src and src_raw
            and not fs.is_dir(_normalize_repo_path(src_raw))
        )

        if is_single_repo_file:
            if delete:
                raise click.ClickException(
                    "Cannot use --delete with a single file source."
                )
            # Single file: dest is the exact local path (or into dir if dir exists)
            src_path = _normalize_repo_path(src_raw)
            if not fs.exists(src_path):
                raise click.ClickException(f"File not found in repo: {src_path}")
            local_dest = Path(dest_path)
            if local_dest.is_dir():
                out = local_dest / Path(src_path).name
            else:
                out = local_dest
            if ignore_existing and out.exists():
                return
            if dry_run:
                click.echo(f":{src_path} -> {out}")
            else:
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    entry = _entry_at_path(fs._store._repo, fs._tree_oid, src_path)
                    if entry and entry[1] == GIT_FILEMODE_LINK:
                        target = fs.readlink(src_path)
                        out.symlink_to(target)
                    else:
                        out.write_bytes(fs.read(src_path))
                except OSError as exc:
                    if ignore_errors:
                        click.echo(f"ERROR: {out}: {exc}", err=True)
                        ctx.exit(1)
                    else:
                        raise click.ClickException(f"Cannot write {out}: {exc}")
                else:
                    _status(ctx, f"Copied :{src_path} -> {out}")
        else:
            try:
                if dry_run:
                    report = copy_from_repo_dry_run(
                        fs, source_paths, dest_path,
                        ignore_existing=ignore_existing,
                        delete=delete,
                    )
                    if report:
                        for w in report.warnings:
                            click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                        for action in report.actions():
                            prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                            click.echo(f"{prefix} {os.path.join(dest_path, action.path)}")
                else:
                    report = copy_from_repo(
                        fs, source_paths, dest_path,
                        ignore_existing=ignore_existing,
                        delete=delete,
                        ignore_errors=ignore_errors,
                    )
                    if report:
                        for w in report.warnings:
                            click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                        for e in report.errors:
                            click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                    _status(ctx, f"Copied -> {dest_path}")
                    if report and report.errors:
                        ctx.exit(1)
            except (FileNotFoundError, NotADirectoryError) as exc:
                raise click.ClickException(str(exc))
            except OSError as exc:
                raise click.ClickException(str(exc))

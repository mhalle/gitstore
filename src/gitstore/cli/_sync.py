"""The sync command."""

from __future__ import annotations

import os

import click

from ..exceptions import StaleSnapshotError
from ._helpers import (
    main,
    _repo_option,
    _no_create_option,
    _require_repo,
    _status,
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
@click.option("-n", "--dry-run", "dry_run", is_flag=True, default=False,
              help="Show what would change without writing.")
@click.option("--ignore-errors", is_flag=True, default=False,
              help="Skip files that fail and continue.")
@_no_create_option
@click.pass_context
def sync(ctx, args, branch, ref, at_path, match_pattern, before, message, dry_run, ignore_errors, no_create):
    """Make one path identical to another (like rsync --delete).

    With one argument, syncs a local directory to the repo root:

        gitstore sync ./dir

    With two arguments, direction is determined by the ':' prefix:

        gitstore sync ./local :repo_path   (disk → repo)
        gitstore sync :repo_path ./local    (repo → disk)
    """
    from ..copy import (
        sync_to_repo, sync_from_repo,
        sync_to_repo_dry_run, sync_from_repo_dry_run,
    )

    if len(args) == 1:
        # 1-arg form: sync local dir to repo root
        if args[0].startswith(":"):
            raise click.ClickException(
                "Single-argument sync must be a local path, not a repo path"
            )
        local_path = args[0]
        repo_dest = ""
        direction = "to_repo"
    elif len(args) == 2:
        src, dest = args
        src_is_repo = src.startswith(":")
        dest_is_repo = dest.startswith(":")
        if src_is_repo and dest_is_repo:
            raise click.ClickException(
                "Both arguments are repo paths — one side must be local"
            )
        if not src_is_repo and not dest_is_repo:
            raise click.ClickException(
                "Neither argument is a repo path — prefix repo paths with ':'"
            )
        if not src_is_repo:
            # disk → repo
            local_path = src
            repo_dest = dest[1:].rstrip("/")
            direction = "to_repo"
        else:
            # repo → disk
            repo_dest = src[1:].rstrip("/")
            local_path = dest
            direction = "from_repo"
    else:
        raise click.ClickException("sync requires 1 or 2 arguments")

    has_snapshot_filters = ref or at_path or match_pattern or before
    if has_snapshot_filters and direction == "to_repo":
        raise click.ClickException(
            "--hash/--path/--match/--before only apply when reading from repo"
        )

    repo_path = _require_repo(ctx)
    if direction == "to_repo" and not dry_run and not no_create:
        store = _open_or_create_store(repo_path, branch)
    else:
        store = _open_store(repo_path)
    before = _parse_before(before)
    fs = _resolve_snapshot(_get_fs(store, branch, ref), at_path, match_pattern, before)

    try:
        if direction == "to_repo":
            if dry_run:
                report = sync_to_repo_dry_run(fs, local_path, repo_dest)
                if report:
                    for w in report.warnings:
                        click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                    for action in report.actions():
                        prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                        if repo_dest and action.path:
                            click.echo(f"{prefix} :{repo_dest}/{action.path}")
                        else:
                            click.echo(f"{prefix} :{repo_dest or ''}{action.path}")
            else:
                _new_fs, report = sync_to_repo(
                    fs, local_path, repo_dest,
                    message=message, ignore_errors=ignore_errors,
                )
                if report:
                    for w in report.warnings:
                        click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                    for e in report.errors:
                        click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                _status(ctx, f"Synced -> :{repo_dest or '/'}")
                if report and report.errors:
                    ctx.exit(1)
        else:
            if dry_run:
                report = sync_from_repo_dry_run(fs, repo_dest, local_path)
                if report:
                    for w in report.warnings:
                        click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                    for action in report.actions():
                        prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                        click.echo(f"{prefix} {os.path.join(local_path, action.path)}")
            else:
                report = sync_from_repo(
                    fs, repo_dest, local_path,
                    ignore_errors=ignore_errors,
                )
                if report:
                    for w in report.warnings:
                        click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                    for e in report.errors:
                        click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                _status(ctx, f"Synced -> {local_path}")
                if report and report.errors:
                    ctx.exit(1)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise click.ClickException(str(exc))
    except StaleSnapshotError:
        raise click.ClickException("Branch modified concurrently — retry")

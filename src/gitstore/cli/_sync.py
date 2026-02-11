"""The sync command."""

from __future__ import annotations

import os

import click

from ..exceptions import StaleSnapshotError
from ._helpers import (
    main,
    _repo_option,
    _branch_option,
    _message_option,
    _dry_run_option,
    _checksum_option,
    _ignore_errors_option,
    _no_create_option,
    _require_repo,
    _status,
    _open_store,
    _open_or_create_store,
    _default_branch,
    _get_fs,
    _parse_before,
    _resolve_fs,
    _resolve_snapshot,
    _snapshot_options,
    _tag_option,
    _apply_tag,
)


@main.command()
@_repo_option
@click.argument("args", nargs=-1, required=True)
@_branch_option
@_snapshot_options
@_message_option
@_dry_run_option
@_ignore_errors_option
@_checksum_option
@_no_create_option
@_tag_option
@click.option("--watch", "watch", is_flag=True, default=False,
              help="Watch for changes and sync continuously (disk→repo only).")
@click.option("--debounce", type=int, default=2000,
              help="Debounce delay in ms for --watch (default: 2000).")
@click.pass_context
def sync(ctx, args, branch, ref, at_path, match_pattern, before, back, message, dry_run, ignore_errors, checksum, no_create, tag, force_tag, watch, debounce):
    """Make one path identical to another (like rsync --delete).

    Requires --repo or GITSTORE_REPO environment variable.

    With one argument, syncs a local directory to the repo root:

        gitstore --repo path/to/repo.git sync ./dir

    With two arguments, direction is determined by the ':' prefix:

        gitstore --repo path/to/repo.git sync ./local :repo_path   (disk → repo)
        gitstore --repo path/to/repo.git sync :repo_path ./local    (repo → disk)
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

    has_snapshot_filters = ref or at_path or match_pattern or before or back
    if has_snapshot_filters and direction == "to_repo":
        raise click.ClickException(
            "--ref/--path/--match/--before only apply when reading from repo"
        )
    if tag and direction == "from_repo":
        raise click.ClickException(
            "--tag only applies when writing to repo (disk → repo)"
        )

    # --watch validation
    if watch:
        if dry_run:
            raise click.ClickException("--watch and --dry-run are incompatible")
        if direction == "from_repo":
            raise click.ClickException("--watch only supports disk → repo")
        if debounce < 100:
            raise click.ClickException("--debounce must be at least 100 ms")

    repo_path = _require_repo(ctx)
    if direction == "to_repo" and not dry_run and not no_create:
        store = _open_or_create_store(repo_path, branch or "main")
        branch = branch or _default_branch(store)
    else:
        store = _open_store(repo_path)
        branch = branch or _default_branch(store)

    if watch:
        from ._watch import watch_and_sync
        watch_and_sync(store, branch, local_path, repo_dest,
                       debounce=debounce, message=message,
                       ignore_errors=ignore_errors, checksum=checksum)
        return

    fs = _resolve_fs(store, branch, ref, at_path=at_path,
                     match_pattern=match_pattern, before=before, back=back)

    try:
        if direction == "to_repo":
            if dry_run:
                report = sync_to_repo_dry_run(fs, local_path, repo_dest,
                                                     checksum=checksum)
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
                _new_fs = sync_to_repo(
                    fs, local_path, repo_dest,
                    message=message, ignore_errors=ignore_errors,
                    checksum=checksum,
                )
                report = _new_fs.report
                if report:
                    for w in report.warnings:
                        click.echo(f"WARNING: {w.path}: {w.error}", err=True)
                    for e in report.errors:
                        click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                if tag:
                    _apply_tag(store, _new_fs, tag, force_tag)
                _status(ctx, f"Synced -> :{repo_dest or '/'}")
                if report and report.errors:
                    ctx.exit(1)
        else:
            if dry_run:
                report = sync_from_repo_dry_run(fs, repo_dest, local_path,
                                                       checksum=checksum)
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
                    checksum=checksum,
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

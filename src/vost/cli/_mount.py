"""CLI mount command — expose a branch/tag as a read-only FUSE filesystem."""

from __future__ import annotations

import os

import click

from ._helpers import (
    _branch_option,
    _current_branch,
    _open_store,
    _repo_option,
    _require_repo,
    _resolve_fs,
    _snapshot_options,
    main,
)


@main.command()
@_repo_option
@click.argument("mountpoint", type=click.Path())
@_branch_option
@_snapshot_options
@click.option("-f", "--foreground", is_flag=True, default=False, help="Run in foreground.")
@click.option("--debug", is_flag=True, default=False, help="Enable FUSE debug output.")
@click.option("--nothreads", is_flag=True, default=False, help="Single-threaded mode.")
@click.option("--allow-other", is_flag=True, default=False, help="Allow other users.")
@click.pass_context
def mount(ctx, mountpoint, branch, ref, at_path, match_pattern, before, back,
          foreground, debug, nothreads, allow_other):
    """Mount a branch/tag as a read-only FUSE filesystem.

    \b
    Examples:
        vost mount /tmp/mnt -r data.git
        vost mount /tmp/mnt -r data.git -b dev
        vost mount /tmp/mnt -r data.git --ref v1.0
        vost mount /tmp/mnt -r data.git --back 2
        vost mount /tmp/mnt -r data.git --before 2025-01-01
        vost mount /tmp/mnt -r data.git --match "release*"
    """
    try:
        from .._fuse import mount as fuse_mount
    except ImportError:
        raise click.ClickException(
            "FUSE support not installed. Install with: pip install vost[fuse]"
        )

    repo_path = _require_repo(ctx)
    store = _open_store(repo_path)

    branch = branch or _current_branch(store)
    fs = _resolve_fs(store, branch, ref,
                     at_path=at_path, match_pattern=match_pattern,
                     before=before, back=back)

    # Force read-only
    from ..fs import FS as _FS

    fs = _FS(store, fs._commit_oid, ref_name=fs.ref_name, writable=False)

    # Validate mountpoint
    mountpoint = os.path.abspath(mountpoint)
    if not os.path.isdir(mountpoint):
        raise click.ClickException(f"Mountpoint is not a directory: {mountpoint}")

    ref_label = fs.ref_name or fs.commit_hash[:12]
    click.echo(f"Mounting {ref_label} at {mountpoint}", err=True)

    fuse_mount(
        fs,
        mountpoint,
        foreground=foreground,
        debug=debug,
        nothreads=nothreads,
        allow_other=allow_other,
    )

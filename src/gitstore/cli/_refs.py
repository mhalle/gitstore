"""Branch and tag subcommands."""

from __future__ import annotations

import click

from ._helpers import (
    branch,
    tag,
    _repo_option,
    _require_repo,
    _status,
    _open_store,
    _parse_before,
    _resolve_snapshot,
    _resolve_ref,
)
import gitstore.cli._helpers as _helpers


# ---------------------------------------------------------------------------
# branch subcommands
# ---------------------------------------------------------------------------

@branch.command("list")
@_repo_option
@click.pass_context
def branch_list(ctx):
    """List all branches."""
    store = _open_store(_require_repo(ctx))
    for name in sorted(store.branches):
        click.echo(name)


@branch.command("create")
@_repo_option
@click.argument("name")
@click.pass_context
def branch_create(ctx, name):
    """Create a new empty branch NAME."""
    store = _open_store(_require_repo(ctx))

    if name in store.branches:
        raise click.ClickException(f"Branch already exists: {name}")

    repo = store._repo
    sig = store._signature
    tree_oid = repo.TreeBuilder().write()
    repo.create_commit(
        f"refs/heads/{name}", sig, sig,
        f"Initialize {name}", tree_oid, [],
    )
    _status(ctx, f"Created branch {name}")


@branch.command("fork")
@_repo_option
@click.argument("name")
@click.option("--ref", default="main",
              help="Ref to fork from (branch, tag, or commit hash). Default: main.")
@click.option("-f", "--force", is_flag=True, default=False,
              help="Overwrite if branch already exists.")
@click.option("--path", "at_path", default=None,
              help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None,
              help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None,
              help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def branch_fork(ctx, name, ref, force, at_path, match_pattern, before):
    """Create a new branch NAME forked from an existing ref."""
    store = _open_store(_require_repo(ctx))

    if name in store.branches and not force:
        raise click.ClickException(f"Branch already exists: {name}")

    before = _parse_before(before)
    source_fs = _resolve_snapshot(_resolve_ref(store, ref), at_path, match_pattern, before)
    from ..fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=name)
    store.branches[name] = new_fs
    _status(ctx, f"Created branch {name}")


@branch.command("set")
@_repo_option
@click.argument("name")
@click.option("--ref", required=True,
              help="Ref to set branch to (branch, tag, or commit hash).")
@click.option("--path", "at_path", default=None,
              help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None,
              help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None,
              help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def branch_set(ctx, name, ref, at_path, match_pattern, before):
    """Point branch NAME at an existing ref (creates if new)."""
    store = _open_store(_require_repo(ctx))

    before = _parse_before(before)
    source_fs = _resolve_snapshot(_resolve_ref(store, ref), at_path, match_pattern, before)
    from ..fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=name)
    store.branches[name] = new_fs
    _status(ctx, f"Set branch {name}")


@branch.command("delete")
@_repo_option
@click.argument("name")
@click.pass_context
def branch_delete(ctx, name):
    """Delete branch NAME."""
    store = _open_store(_require_repo(ctx))
    try:
        del store.branches[name]
    except KeyError:
        raise click.ClickException(f"Branch not found: {name}")
    _status(ctx, f"Deleted branch {name}")


@branch.command("hash")
@_repo_option
@click.argument("name")
@click.option("--back", type=int, default=0, help="Walk back N commits.")
@click.option("--path", "at_path", default=None,
              help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None,
              help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None,
              help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def branch_hash(ctx, name, back, at_path, match_pattern, before):
    """Print the commit hash of branch NAME."""
    store = _open_store(_require_repo(ctx))
    try:
        fs = store.branches[name]
    except KeyError:
        raise click.ClickException(f"Branch not found: {name}")
    before = _parse_before(before)
    fs = _resolve_snapshot(fs, at_path, match_pattern, before)
    if back:
        try:
            fs = fs.back(back)
        except ValueError as e:
            raise click.ClickException(str(e))
    click.echo(fs.hash)


# ---------------------------------------------------------------------------
# tag subcommands
# ---------------------------------------------------------------------------

@tag.command("list")
@_repo_option
@click.pass_context
def tag_list(ctx):
    """List all tags."""
    store = _open_store(_require_repo(ctx))
    for name in sorted(store.tags):
        click.echo(name)


@tag.command("fork")
@_repo_option
@click.argument("name")
@click.option("--ref", default="main",
              help="Ref to tag (branch, tag, or commit hash). Default: main.")
@click.option("--path", "at_path", default=None,
              help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None,
              help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None,
              help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def tag_fork(ctx, name, ref, at_path, match_pattern, before):
    """Create a new tag NAME from an existing ref."""
    before = _parse_before(before)
    store = _open_store(_require_repo(ctx))

    if name in store.tags:
        raise click.ClickException(f"Tag already exists: {name}")

    source_fs = _resolve_snapshot(_resolve_ref(store, ref), at_path, match_pattern, before)

    from ..fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=None)
    store.tags[name] = new_fs
    _status(ctx, f"Created tag {name}")


@tag.command("set")
@_repo_option
@click.argument("name")
@click.option("--ref", required=True,
              help="Ref to set tag to (branch, tag, or commit hash).")
@click.option("--path", "at_path", default=None,
              help="Use latest commit that changed this path.")
@click.option("--match", "match_pattern", default=None,
              help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None,
              help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def tag_set(ctx, name, ref, at_path, match_pattern, before):
    """Point tag NAME at an existing ref (creates or updates)."""
    store = _open_store(_require_repo(ctx))

    before = _parse_before(before)
    source_fs = _resolve_snapshot(_resolve_ref(store, ref), at_path, match_pattern, before)
    from ..fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=None)
    if name in store.tags:
        del store.tags[name]
    store.tags[name] = new_fs
    _status(ctx, f"Set tag {name}")


@tag.command("delete")
@_repo_option
@click.argument("name")
@click.pass_context
def tag_delete(ctx, name):
    """Delete tag NAME."""
    store = _open_store(_require_repo(ctx))
    try:
        del store.tags[name]
    except KeyError:
        raise click.ClickException(f"Tag not found: {name}")
    _status(ctx, f"Deleted tag {name}")


@tag.command("hash")
@_repo_option
@click.argument("name")
@click.pass_context
def tag_hash(ctx, name):
    """Print the commit hash of tag NAME."""
    store = _open_store(_require_repo(ctx))
    try:
        fs = store.tags[name]
    except KeyError:
        raise click.ClickException(f"Tag not found: {name}")
    click.echo(fs.hash)


# Wire up the default subcommand references in _helpers
_helpers.branch_list = branch_list
_helpers.tag_list = tag_list

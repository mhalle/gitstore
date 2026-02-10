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
@click.option("--from", "from_ref", default=None, help="Ref to fork from.")
@click.option("--path", "at_path", default=None,
              help="Use latest commit that changed this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None, help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def branch_create(ctx, name, from_ref, at_path, deprecated_at, match_pattern, before):
    """Create a new branch NAME, optionally forking from an existing ref."""
    at_path = at_path or deprecated_at
    store = _open_store(_require_repo(ctx))

    if name in store.branches:
        raise click.ClickException(f"Branch already exists: {name}")

    has_filters = at_path is not None or match_pattern is not None or before is not None
    if from_ref is None:
        if has_filters:
            raise click.ClickException("--path/--match/--before require --from")
        repo = store._repo
        sig = store._signature
        tree_oid = repo.TreeBuilder().write()
        commit_oid = repo.create_commit(
            f"refs/heads/{name}", sig, sig,
            f"Initialize {name}", tree_oid, [],
        )
    else:
        before = _parse_before(before)
        source_fs = _resolve_snapshot(_resolve_ref(store, from_ref), at_path, match_pattern, before)
        from ..fs import FS
        new_fs = FS(store, source_fs._commit_oid, branch=name)
        store.branches[name] = new_fs
    _status(ctx, f"Created branch {name}")


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


@tag.command("create")
@_repo_option
@click.argument("name")
@click.option("--from", "from_ref", required=True, help="Ref to tag (branch, tag, or commit hash).")
@click.option("--path", "at_path", default=None,
              help="Use latest commit that changed this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Use latest commit matching this message pattern (* and ?).")
@click.option("--before", "before", default=None, help="Use latest commit on or before this date (ISO 8601).")
@click.pass_context
def tag_create(ctx, name, from_ref, at_path, deprecated_at, match_pattern, before):
    """Create a new tag NAME from a ref."""
    at_path = at_path or deprecated_at
    before = _parse_before(before)
    store = _open_store(_require_repo(ctx))

    if name in store.tags:
        raise click.ClickException(f"Tag already exists: {name}")

    source_fs = _resolve_snapshot(_resolve_ref(store, from_ref), at_path, match_pattern, before)

    from ..fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=None)
    store.tags[name] = new_fs
    _status(ctx, f"Created tag {name}")


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


# Wire up the default subcommand references in _helpers
_helpers.branch_list = branch_list
_helpers.tag_list = tag_list

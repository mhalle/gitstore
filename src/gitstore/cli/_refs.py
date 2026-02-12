"""Branch and tag subcommands."""

from __future__ import annotations

import click

from ._helpers import (
    branch,
    tag,
    _repo_option,
    _branch_option,
    _require_repo,
    _status,
    _open_store,
    _default_branch,
    _apply_snapshot_filters,
    _resolve_fs,
    _resolve_ref,
    _snapshot_options,
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
@_branch_option
@click.option("-f", "--force", is_flag=True, default=False,
              help="Overwrite if branch already exists.")
@_snapshot_options
@click.pass_context
def branch_fork(ctx, name, branch, force, ref, at_path, match_pattern, before, back):
    """Create a new branch NAME forked from an existing ref."""
    store = _open_store(_require_repo(ctx))
    branch = branch or _default_branch(store)

    if name in store.branches and not force:
        raise click.ClickException(f"Branch already exists: {name}")

    source_fs = _resolve_fs(store, branch, ref=ref, at_path=at_path,
                            match_pattern=match_pattern, before=before, back=back)
    from ..fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=name)
    try:
        store.branches[name] = new_fs
    except ValueError as e:
        raise click.ClickException(str(e))
    _status(ctx, f"Created branch {name}")


@branch.command("set")
@_repo_option
@click.argument("name")
@_snapshot_options
@click.pass_context
def branch_set(ctx, name, ref, at_path, match_pattern, before, back):
    """Point branch NAME at an existing ref (creates if new)."""
    if not ref:
        raise click.ClickException("--ref is required for this command")
    store = _open_store(_require_repo(ctx))

    source_fs = _apply_snapshot_filters(
        _resolve_ref(store, ref), at_path=at_path,
        match_pattern=match_pattern, before=before, back=back)
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
@_snapshot_options
@click.pass_context
def branch_hash(ctx, name, ref, at_path, match_pattern, before, back):
    """Print the commit hash of branch NAME."""
    store = _open_store(_require_repo(ctx))
    try:
        fs = store.branches[name]
    except KeyError:
        raise click.ClickException(f"Branch not found: {name}")
    fs = _apply_snapshot_filters(fs, at_path=at_path, match_pattern=match_pattern,
                                 before=before, back=back)
    click.echo(fs.commit_hash)


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
@_branch_option
@_snapshot_options
@click.pass_context
def tag_fork(ctx, name, branch, ref, at_path, match_pattern, before, back):
    """Create a new tag NAME from an existing ref."""
    store = _open_store(_require_repo(ctx))
    branch = branch or _default_branch(store)

    if name in store.tags:
        raise click.ClickException(f"Tag already exists: {name}")

    source_fs = _resolve_fs(store, branch, ref=ref, at_path=at_path,
                            match_pattern=match_pattern, before=before, back=back)

    from ..fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=None)
    try:
        store.tags[name] = new_fs
    except ValueError as e:
        raise click.ClickException(str(e))
    _status(ctx, f"Created tag {name}")


@tag.command("set")
@_repo_option
@click.argument("name")
@_snapshot_options
@click.pass_context
def tag_set(ctx, name, ref, at_path, match_pattern, before, back):
    """Point tag NAME at an existing ref (creates or updates)."""
    if not ref:
        raise click.ClickException("--ref is required for this command")
    store = _open_store(_require_repo(ctx))

    source_fs = _apply_snapshot_filters(
        _resolve_ref(store, ref), at_path=at_path,
        match_pattern=match_pattern, before=before, back=back)
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
    click.echo(fs.commit_hash)


@branch.command("default")
@_repo_option
@click.option("--branch", "-b", default=None,
              help="Set the default branch to this name.")
@click.pass_context
def branch_default(ctx, branch):
    """Show or set the repository's default branch.

    Without -b, prints the current default branch.
    With -b NAME, sets the default branch to NAME (must exist).
    """
    store = _open_store(_require_repo(ctx))
    if branch is None:
        name = store._repo.get_head_branch()
        if name is None:
            raise click.ClickException("HEAD does not point to an existing branch")
        click.echo(name)
    else:
        if branch not in store.branches:
            raise click.ClickException(f"Branch not found: {branch}")
        store._repo.set_head_branch(branch)
        _status(ctx, f"Default branch set to {branch}")


# Wire up the default subcommand references in _helpers
_helpers.branch_list = branch_list
_helpers.tag_list = tag_list

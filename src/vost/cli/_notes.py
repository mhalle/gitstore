"""Note subcommands."""

from __future__ import annotations

import click

from ._helpers import (
    main,
    _repo_option,
    _require_repo,
    _status,
    _open_store,
    _current_branch,
)


@main.group()
def note():
    """Manage git notes on commits."""


@note.command("get")
@_repo_option
@click.argument("target")
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_get(ctx, target, namespace):
    """Get the note for a commit hash or ref name (branch/tag)."""
    store = _open_store(_require_repo(ctx))
    ns = store.notes[namespace]
    try:
        text = ns[target]
    except KeyError:
        raise click.ClickException(f"No note for {target} in namespace '{namespace}'")
    except (TypeError, ValueError) as e:
        raise click.ClickException(str(e))
    click.echo(text, nl=False)


@note.command("set")
@_repo_option
@click.argument("target")
@click.argument("text")
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_set(ctx, target, text, namespace):
    """Set the note for a commit hash or ref name (branch/tag)."""
    store = _open_store(_require_repo(ctx))
    ns = store.notes[namespace]
    try:
        ns[target] = text
    except (TypeError, ValueError) as e:
        raise click.ClickException(str(e))
    _status(ctx, f"Note set for {target}")


@note.command("delete")
@_repo_option
@click.argument("target")
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_delete(ctx, target, namespace):
    """Delete the note for a commit hash or ref name (branch/tag)."""
    store = _open_store(_require_repo(ctx))
    ns = store.notes[namespace]
    try:
        del ns[target]
    except KeyError:
        raise click.ClickException(f"No note for {target} in namespace '{namespace}'")
    except (TypeError, ValueError) as e:
        raise click.ClickException(str(e))
    _status(ctx, f"Note deleted for {target}")


@note.command("list")
@_repo_option
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_list(ctx, namespace):
    """List commit hashes that have notes."""
    store = _open_store(_require_repo(ctx))
    ns = store.notes[namespace]
    for h in sorted(ns):
        click.echo(h)


@note.command("get-current")
@_repo_option
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_get_current(ctx, namespace):
    """Get the note for the current branch's HEAD commit."""
    store = _open_store(_require_repo(ctx))
    branch = _current_branch(store)
    try:
        fs = store.branches[branch]
    except KeyError:
        raise click.ClickException(f"Branch not found: {branch}")
    ns = store.notes[namespace]
    try:
        text = ns[fs.commit_hash]
    except KeyError:
        raise click.ClickException(
            f"No note for HEAD ({fs.commit_hash[:7]}) in namespace '{namespace}'"
        )
    click.echo(text, nl=False)


@note.command("set-current")
@_repo_option
@click.argument("text")
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_set_current(ctx, text, namespace):
    """Set the note for the current branch's HEAD commit."""
    store = _open_store(_require_repo(ctx))
    branch = _current_branch(store)
    try:
        fs = store.branches[branch]
    except KeyError:
        raise click.ClickException(f"Branch not found: {branch}")
    ns = store.notes[namespace]
    try:
        ns[fs.commit_hash] = text
    except (TypeError, ValueError) as e:
        raise click.ClickException(str(e))
    _status(ctx, f"Note set for HEAD ({fs.commit_hash[:7]})")

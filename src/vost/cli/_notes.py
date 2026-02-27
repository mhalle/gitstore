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


def _resolve_note_target(store, target):
    """Resolve a note target string to a ref name for NoteNamespace lookup.

    - None or ":" → current branch name
    - "main:" → "main" (strip trailing colon)
    - anything else → passed through unchanged (hash, branch, tag)
    """
    if target is None or target == ":":
        return _current_branch(store)
    if target.endswith(":"):
        return target[:-1]
    return target


@main.group()
def note():
    """Manage git notes on commits."""


@note.command("get")
@_repo_option
@click.argument("target", required=False, default=None)
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_get(ctx, target, namespace):
    """Get the note for a commit hash or ref name (branch/tag).

    \b
    Without TARGET, uses the current branch.
    TARGET can also be ":" (current branch) or "main:" (strip trailing colon).
    """
    store = _open_store(_require_repo(ctx))
    resolved = _resolve_note_target(store, target)
    ns = store.notes[namespace]
    try:
        text = ns[resolved]
    except KeyError:
        raise click.ClickException(f"No note for {resolved} in namespace '{namespace}'")
    except (TypeError, ValueError) as e:
        raise click.ClickException(str(e))
    click.echo(text, nl=False)


@note.command("set")
@_repo_option
@click.argument("args", nargs=-1, required=True)
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_set(ctx, args, namespace):
    """Set the note for a commit hash or ref name (branch/tag).

    \b
    Usage:
        vost note set TEXT                  set note for current branch
        vost note set TARGET TEXT           set note for TARGET
        vost note set : TEXT                set note for current branch (explicit)
        vost note set main: TEXT            set note for main branch
    """
    if len(args) == 1:
        target, text = None, args[0]
    elif len(args) == 2:
        target, text = args
    else:
        raise click.ClickException("Usage: vost note set [TARGET] TEXT")
    store = _open_store(_require_repo(ctx))
    resolved = _resolve_note_target(store, target)
    ns = store.notes[namespace]
    try:
        ns[resolved] = text
    except (TypeError, ValueError) as e:
        raise click.ClickException(str(e))
    _status(ctx, f"Note set for {resolved}")


@note.command("delete")
@_repo_option
@click.argument("target", required=False, default=None)
@click.option("-N", "--namespace", default="commits",
              help="Notes namespace (default: commits).")
@click.pass_context
def note_delete(ctx, target, namespace):
    """Delete the note for a commit hash or ref name (branch/tag).

    \b
    Without TARGET, uses the current branch.
    TARGET can also be ":" (current branch) or "main:" (strip trailing colon).
    """
    store = _open_store(_require_repo(ctx))
    resolved = _resolve_note_target(store, target)
    ns = store.notes[namespace]
    try:
        del ns[resolved]
    except KeyError:
        raise click.ClickException(f"No note for {resolved} in namespace '{namespace}'")
    except (TypeError, ValueError) as e:
        raise click.ClickException(str(e))
    _status(ctx, f"Note deleted for {resolved}")


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

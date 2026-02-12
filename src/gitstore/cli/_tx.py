"""Transaction CLI commands: tx begin, commit, abort, status, ls."""

from __future__ import annotations

import click

from ..tx import (
    tx_begin as _tx_begin,
    tx_commit as _tx_commit,
    tx_abort as _tx_abort,
    tx_status as _tx_status,
    tx_list as _tx_list,
    _tx_source,
)
from ._helpers import (
    main,
    _repo_option,
    _branch_option,
    _message_option,
    _require_repo,
    _status,
    _open_store,
    _default_branch,
    _tag_option,
    _apply_tag,
)


@main.group()
def tx():
    """Transactions: accumulate writes, commit once.

    \b
    Start a transaction, write from multiple processes,
    then squash everything into a single commit:

    \b
        TX=$(gitstore tx begin)
        echo data1 | gitstore write --tx $TX :stage1.txt &
        echo data2 | gitstore write --tx $TX :stage2.txt &
        wait
        gitstore tx commit $TX -m "pipeline run"
    """


@tx.command("begin")
@_repo_option
@_branch_option
@click.pass_context
def begin(ctx, branch):
    """Start a transaction. Prints the transaction ID to stdout."""
    store = _open_store(_require_repo(ctx))
    branch = branch or _default_branch(store)
    try:
        tx_id = _tx_begin(store, branch)
    except KeyError as exc:
        raise click.ClickException(str(exc))
    click.echo(tx_id)


@tx.command("commit")
@_repo_option
@click.argument("tx_id")
@_message_option
@_tag_option
@click.pass_context
def commit(ctx, tx_id, message, tag, force_tag):
    """Squash transaction into a single commit on the source branch.

    TX_ID is the transaction identifier returned by 'tx begin'.
    """
    from ..exceptions import StaleSnapshotError

    store = _open_store(_require_repo(ctx))
    try:
        source = _tx_source(tx_id)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    try:
        result_fs = _tx_commit(store, tx_id, message=message)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc))
    except StaleSnapshotError:
        raise click.ClickException(
            "Target branch modified concurrently — failed after retries"
        )
    if tag:
        _apply_tag(store, result_fs, tag, force_tag)
    _status(ctx, f"Transaction committed to '{source}' ({result_fs.hash[:7]})")
    click.echo(result_fs.hash[:7])


@tx.command("abort")
@_repo_option
@click.argument("tx_id")
@click.pass_context
def abort(ctx, tx_id):
    """Abort a transaction, discarding all changes.

    TX_ID is the transaction identifier returned by 'tx begin'.
    """
    store = _open_store(_require_repo(ctx))
    _tx_abort(store, tx_id)
    _status(ctx, "Transaction aborted")


@tx.command("status")
@_repo_option
@click.argument("tx_id")
@click.pass_context
def status(ctx, tx_id):
    """Show files accumulated in a transaction.

    TX_ID is the transaction identifier returned by 'tx begin'.
    """
    store = _open_store(_require_repo(ctx))
    try:
        source = _tx_source(tx_id)
        adds, updates, removes = _tx_status(store, tx_id)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc))

    click.echo(f"Transaction: {tx_id}")
    click.echo(f"Target: {source}")
    if not adds and not updates and not removes:
        click.echo("No changes")
        return
    for path in adds:
        click.echo(f"  A  {path}")
    for path in updates:
        click.echo(f"  M  {path}")
    for path in removes:
        click.echo(f"  D  {path}")


@tx.command("ls")
@_repo_option
@click.pass_context
def ls(ctx):
    """List active transactions."""
    store = _open_store(_require_repo(ctx))
    transactions = _tx_list(store)
    if not transactions:
        click.echo("No active transactions")
        return
    for tx_id in sorted(transactions):
        try:
            source = _tx_source(tx_id)
            click.echo(f"{tx_id}  (target: {source})")
        except ValueError:
            click.echo(tx_id)

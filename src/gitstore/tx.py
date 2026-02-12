"""Transaction support for atomic multi-file commits.

Transactions allow multiple concurrent writers to accumulate changes on a
temporary branch, then squash all changes into a single commit on the
target branch.

Usage (Python API)::

    from gitstore import GitStore
    from gitstore.tx import tx_begin, tx_commit, tx_abort

    store = GitStore.open("data.git")
    tx_id = tx_begin(store, "main")

    # Multiple writers can write concurrently:
    from gitstore.fs import retry_write
    retry_write(store, tx_id, "file1.txt", b"data1")
    retry_write(store, tx_id, "file2.txt", b"data2")

    # Squash into a single commit on main:
    fs = tx_commit(store, tx_id, message="pipeline results")

Usage (CLI)::

    TX=$(gitstore tx begin -b main)
    echo data1 | gitstore write --tx $TX :file1.txt &
    echo data2 | gitstore write --tx $TX :file2.txt &
    wait
    gitstore tx commit $TX -m "pipeline results"
"""

from __future__ import annotations

import random
import time
import uuid
from typing import TYPE_CHECKING

from . import _compat as pygit2
from .exceptions import StaleSnapshotError
from .tree import GIT_FILEMODE_TREE

if TYPE_CHECKING:
    from .fs import FS
    from .repo import GitStore

__all__ = ["tx_begin", "tx_commit", "tx_abort", "tx_status", "tx_list"]

TX_PREFIX = "_tx/"
TX_REF_PREFIX = "refs/tx/"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tx_uuid(tx_id: str) -> str:
    """Extract the UUID suffix from a transaction ID."""
    if not tx_id.startswith(TX_PREFIX):
        raise ValueError(f"Not a transaction ID: {tx_id!r}")
    return tx_id.rsplit("/", 1)[1]


def _tx_source(tx_id: str) -> str:
    """Extract the source branch name from a transaction ID."""
    if not tx_id.startswith(TX_PREFIX):
        raise ValueError(f"Not a transaction ID: {tx_id!r}")
    rest = tx_id[len(TX_PREFIX):]
    parts = rest.rsplit("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid transaction ID: {tx_id!r}")
    return parts[0]


def _tx_meta_ref(tx_id: str) -> str:
    """Return the metadata ref name for a transaction."""
    return f"{TX_REF_PREFIX}{_tx_uuid(tx_id)}"


def _collect_entries(repo, tree_oid, prefix=""):
    """Return {path: (oid, mode)} for all blobs/links in the tree."""
    entries = {}
    tree = repo[tree_oid]
    for entry in tree:
        full_path = f"{prefix}/{entry.name}" if prefix else entry.name
        if entry.filemode == GIT_FILEMODE_TREE:
            entries.update(_collect_entries(repo, entry.id, full_path))
        else:
            entries[full_path] = (entry.id, entry.filemode)
    return entries


def _diff_trees(repo, base_tree_oid, new_tree_oid):
    """Compute the delta between two trees.

    Returns ``(writes, removes)`` suitable for ``_commit_changes`` /
    ``rebuild_tree``.

    *writes*: ``{path: (oid, mode)}`` — files added or changed.
    *removes*: ``set`` of paths deleted.
    """
    base = _collect_entries(repo, base_tree_oid)
    new = _collect_entries(repo, new_tree_oid)

    writes: dict[str, tuple[pygit2.Oid, int]] = {}
    removes: set[str] = set()

    for path, (oid, mode) in new.items():
        if path not in base or base[path] != (oid, mode):
            writes[path] = (oid, mode)

    for path in base:
        if path not in new:
            removes.add(path)

    return writes, removes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tx_begin(store: GitStore, branch: str = "main") -> str:
    """Start a new transaction forked from *branch*.

    Creates a temporary branch and records the fork-point commit.
    Returns the transaction ID (which doubles as the temp branch name).

    Raises ``KeyError`` if *branch* does not exist.
    """
    uuid_str = uuid.uuid4().hex[:16]
    tx_id = f"{TX_PREFIX}{branch}/{uuid_str}"

    try:
        fs = store.branches[branch]
    except KeyError:
        raise KeyError(f"Branch not found: {branch!r}")

    # Create temp branch at the same commit
    store.branches[tx_id] = fs

    # Store fork-point commit OID in a metadata ref
    meta_ref = _tx_meta_ref(tx_id)
    store._repo.references.create(meta_ref, fs._commit_oid)

    return tx_id


def tx_commit(
    store: GitStore,
    tx_id: str,
    *,
    message: str | None = None,
    retries: int = 5,
) -> FS:
    """Squash transaction changes into a single commit on the source branch.

    Computes the delta between the fork point and the transaction HEAD,
    then applies that delta atomically to the current source branch HEAD.
    Cleans up the temporary branch and metadata ref.

    Retries on ``StaleSnapshotError`` (concurrent writes to the target
    branch).

    Returns the new FS on the source branch.
    """
    source_branch = _tx_source(tx_id)
    meta_ref = _tx_meta_ref(tx_id)

    # Get the fork-point tree
    try:
        base_oid = store._repo.references[meta_ref].resolve().target
    except KeyError:
        raise ValueError(f"Transaction metadata not found: {tx_id!r}")
    base_tree = store._repo[base_oid].tree_id

    # Get current tx state
    try:
        tx_fs = store.branches[tx_id]
    except KeyError:
        raise ValueError(f"Transaction branch not found: {tx_id!r}")
    tx_tree = tx_fs._tree_oid

    # Compute delta (fork-point → tx HEAD)
    writes, removes = _diff_trees(store._repo, base_tree, tx_tree)

    # Apply delta to target branch with retry
    result_fs: FS | None = None
    for attempt in range(retries):
        try:
            target_fs = store.branches[source_branch]
        except KeyError:
            raise KeyError(f"Source branch not found: {source_branch!r}")

        if not writes and not removes:
            result_fs = target_fs
            break

        try:
            result_fs = target_fs._commit_changes(writes, removes, message, "tx")
            break
        except StaleSnapshotError:
            if attempt == retries - 1:
                raise
            delay = min(0.01 * (2 ** attempt), 0.2)
            time.sleep(random.uniform(0, delay))

    # Cleanup temp branch and metadata ref
    del store.branches[tx_id]
    store._repo.references.delete(meta_ref)

    return result_fs


def tx_abort(store: GitStore, tx_id: str) -> None:
    """Abort a transaction, discarding all accumulated changes."""
    meta_ref = _tx_meta_ref(tx_id)

    try:
        del store.branches[tx_id]
    except KeyError:
        pass

    try:
        store._repo.references.delete(meta_ref)
    except KeyError:
        pass


def tx_status(
    store: GitStore, tx_id: str
) -> tuple[list[str], list[str], list[str]]:
    """Return the accumulated changes in a transaction.

    Returns ``(adds, updates, removes)`` — three sorted lists of paths.
    """
    meta_ref = _tx_meta_ref(tx_id)

    try:
        base_oid = store._repo.references[meta_ref].resolve().target
    except KeyError:
        raise ValueError(f"Transaction metadata not found: {tx_id!r}")
    base_tree = store._repo[base_oid].tree_id

    try:
        tx_fs = store.branches[tx_id]
    except KeyError:
        raise ValueError(f"Transaction branch not found: {tx_id!r}")

    writes, removes = _diff_trees(store._repo, base_tree, tx_fs._tree_oid)

    # Split writes into adds vs updates
    base_entries = _collect_entries(store._repo, base_tree)
    adds = sorted(p for p in writes if p not in base_entries)
    updates = sorted(p for p in writes if p in base_entries)

    return adds, updates, sorted(removes)


def tx_list(store: GitStore) -> list[str]:
    """List all active transaction IDs."""
    return [name for name in store.branches if name.startswith(TX_PREFIX)]

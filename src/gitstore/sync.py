"""Path-level sync between local directories and repo paths.

Make a repo path identical to a local directory (``sync_to_repo``) or
a local directory identical to a repo path (``sync_from_repo``).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .tree import (
    GIT_FILEMODE_LINK,
    _entry_at_path,
    _normalize_path,
)

if TYPE_CHECKING:
    from .fs import FS


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SyncAction:
    """A single add/update/delete action."""
    path: str       # relative path (repo-style forward slashes)
    action: str     # "add", "update", "delete"


@dataclass
class SyncPlan:
    """What a sync operation would do."""
    add: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.add and not self.update and not self.delete

    @property
    def total(self) -> int:
        return len(self.add) + len(self.update) + len(self.delete)

    def actions(self) -> list[SyncAction]:
        """All actions sorted by path."""
        result: list[SyncAction] = []
        for p in self.add:
            result.append(SyncAction(path=p, action="add"))
        for p in self.update:
            result.append(SyncAction(path=p, action="update"))
        for p in self.delete:
            result.append(SyncAction(path=p, action="delete"))
        result.sort(key=lambda a: a.path)
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HASH_CHUNK_SIZE = 65536


def _blob_hasher(size: int) -> hashlib._Hash:
    """Return a SHA-1 hasher pre-loaded with the git blob header.

    Git blob OID = SHA-1(``blob <size>\\0`` + content).
    """
    return hashlib.sha1(f"blob {size}\0".encode())


def _local_file_oid(base: Path, rel: str) -> bytes:
    """Compute git blob OID for a local file by streaming through SHA-1.

    Symlinks hash their target string.  Regular files are streamed in
    chunks to avoid loading entire contents into memory.
    """
    full = base / rel
    if full.is_symlink():
        data = os.readlink(full).encode()
        h = _blob_hasher(len(data))
        h.update(data)
        return h.hexdigest().encode("ascii")
    size = full.stat().st_size
    h = _blob_hasher(size)
    with open(full, "rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().encode("ascii")


def _walk_local_paths(local_path: str) -> set[str]:
    """Return the set of relative paths under *local_path*.

    Only collects path names — does not read file content.
    Symlinked directories are recorded as entries (not descended into).
    """
    result: set[str] = set()
    base = Path(local_path)
    for dirpath, _dirnames, filenames in os.walk(base):
        dp = Path(dirpath)
        for fname in filenames:
            full = dp / fname
            rel_str = str(full.relative_to(base)).replace(os.sep, "/")
            result.add(rel_str)
        symlinked = []
        for dname in _dirnames:
            full = dp / dname
            if full.is_symlink():
                rel_str = str(full.relative_to(base)).replace(os.sep, "/")
                result.add(rel_str)
                symlinked.append(dname)
        for dname in symlinked:
            _dirnames.remove(dname)
    return result


def _walk_repo(fs: FS, repo_path: str) -> dict[str, bytes]:
    """Build {relative_path: oid_hex_bytes} for all files under *repo_path*.

    The values are the raw OID hex bytes from the repo (not file content),
    suitable for comparison against ``_local_file_oid()`` results.
    Returns an empty dict if *repo_path* does not exist or is not a directory.
    """
    result: dict[str, bytes] = {}
    if repo_path:
        if not fs.exists(repo_path):
            return result
        if not fs.is_dir(repo_path):
            return result
    walk_path = repo_path or None
    for dirpath, _dirs, files in fs.walk(walk_path):
        for fname in files:
            store_path = f"{dirpath}/{fname}" if dirpath else fname
            if repo_path and store_path.startswith(repo_path + "/"):
                rel = store_path[len(repo_path) + 1:]
            else:
                rel = store_path
            entry = _entry_at_path(fs._store._repo, fs._tree_oid, store_path)
            if entry is not None:
                result[rel] = entry[0]._sha  # raw hex bytes
    return result


def _build_plan_local_to_repo(
    local_paths: set[str],
    repo_files: dict[str, bytes],
    local_base: Path,
) -> SyncPlan:
    """Compare local paths against repo OIDs to produce a SyncPlan.

    Only reads and hashes local files that exist in both sets (potential
    updates).  Adds and deletes are determined by path membership alone.
    """
    repo_keys = repo_files.keys()
    add = sorted(local_paths - repo_keys)
    delete = sorted(repo_keys - local_paths)

    update: list[str] = []
    for path in sorted(local_paths & repo_keys):
        if _local_file_oid(local_base, path) != repo_files[path]:
            update.append(path)

    return SyncPlan(add=add, update=update, delete=delete)


def _build_plan_repo_to_local(
    repo_files: dict[str, bytes],
    local_paths: set[str],
    local_base: Path,
) -> SyncPlan:
    """Compare repo OIDs against local paths to produce a SyncPlan.

    Only reads and hashes local files that exist in both sets (potential
    updates).  Adds and deletes are determined by path membership alone.
    """
    repo_keys = repo_files.keys()
    add = sorted(repo_keys - local_paths)
    delete = sorted(local_paths - repo_keys)

    update: list[str] = []
    for path in sorted(local_paths & repo_keys):
        if _local_file_oid(local_base, path) != repo_files[path]:
            update.append(path)

    return SyncPlan(add=add, update=update, delete=delete)


def _filter_tree_conflicts(
    write_paths: set[str], deletes: list[str],
) -> list[str]:
    """Remove deletes that conflict with writes at file↔directory boundaries.

    When a write replaces a tree with a blob (e.g. write ``foo``, delete
    ``foo/bar``), the tree builder handles the replacement implicitly —
    the delete is redundant and would cause a conflict in ``rebuild_tree``.
    Similarly, when writes create a subtree that replaces a blob (e.g.
    write ``foo/bar``, delete ``foo``), the delete is also redundant.
    """
    result: list[str] = []
    for d in deletes:
        skip = False
        for w in write_paths:
            # write at foo, delete at foo/bar → skip (blob replaces tree)
            if d.startswith(w + "/"):
                skip = True
                break
            # write at foo/bar, delete at foo → skip (tree replaces blob)
            if w.startswith(d + "/"):
                skip = True
                break
        if not skip:
            result.append(d)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_to_repo_dry_run(
    fs: FS, local_path: str, repo_path: str,
) -> SyncPlan:
    """Compute what ``sync_to_repo`` would do without writing."""
    repo_path = _normalize_path(repo_path) if repo_path else ""
    local_paths = _walk_local_paths(local_path)
    repo_files = _walk_repo(fs, repo_path)
    return _build_plan_local_to_repo(local_paths, repo_files, Path(local_path))


def sync_from_repo_dry_run(
    fs: FS, repo_path: str, local_path: str,
) -> SyncPlan:
    """Compute what ``sync_from_repo`` would do without writing."""
    repo_path = _normalize_path(repo_path) if repo_path else ""
    repo_files = _walk_repo(fs, repo_path)
    local_paths = _walk_local_paths(local_path)
    return _build_plan_repo_to_local(repo_files, local_paths, Path(local_path))


def sync_to_repo(
    fs: FS, local_path: str, repo_path: str, *,
    message: str | None = None,
) -> FS:
    """Make *repo_path* identical to *local_path*. Returns new FS."""
    plan = sync_to_repo_dry_run(fs, local_path, repo_path)
    if plan.in_sync:
        return fs

    repo_prefix = _normalize_path(repo_path) if repo_path else ""
    base = Path(local_path)
    write_paths = set(plan.add + plan.update)
    safe_deletes = _filter_tree_conflicts(write_paths, plan.delete)

    with fs.batch(message=message or f"Sync {local_path} -> {repo_prefix or '/'}") as b:
        for rel in plan.add + plan.update:
            local_file = base / rel
            full_repo_path = f"{repo_prefix}/{rel}" if repo_prefix else rel
            if local_file.is_symlink():
                target = os.readlink(local_file)
                b.write_symlink(full_repo_path, target)
            else:
                b.write_from(full_repo_path, local_file)

        for rel in safe_deletes:
            full_repo_path = f"{repo_prefix}/{rel}" if repo_prefix else rel
            b.remove(full_repo_path)

    return b.fs


def sync_from_repo(
    fs: FS, repo_path: str, local_path: str,
) -> None:
    """Make *local_path* identical to *repo_path*."""
    import shutil

    plan = sync_from_repo_dry_run(fs, repo_path, local_path)
    if plan.in_sync:
        return

    repo_prefix = _normalize_path(repo_path) if repo_path else ""
    base = Path(local_path)
    base.mkdir(parents=True, exist_ok=True)

    # Process deletes first so directory↔file conflicts are resolved
    # before we try to create new files/directories.
    for rel in plan.delete:
        out = base / rel
        if out.exists() or out.is_symlink():
            out.unlink()

    # Clear blocking paths: if we need to write foo/bar.txt but foo is
    # a file (or vice versa), remove the blocker before writing.
    for rel in plan.add + plan.update:
        out = base / rel
        # If out is a directory but we need a file there, remove the tree
        if out.is_dir() and not out.is_symlink():
            shutil.rmtree(out)
        # If a parent component is a file/symlink, remove it
        for parent in out.parents:
            if parent == base:
                break
            if parent.exists() and not parent.is_dir():
                parent.unlink()
                break

    for rel in plan.add + plan.update:
        store_path = f"{repo_prefix}/{rel}" if repo_prefix else rel
        out = base / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        # Remove existing file/symlink before writing
        if out.exists() or out.is_symlink():
            out.unlink()
        entry = _entry_at_path(fs._store._repo, fs._tree_oid, store_path)
        if entry and entry[1] == GIT_FILEMODE_LINK:
            target = fs.readlink(store_path)
            out.symlink_to(target)
        else:
            out.write_bytes(fs.read(store_path))

    # Clean up empty directories left after deletes
    _prune_empty_dirs(base)


def _prune_empty_dirs(base: Path) -> None:
    """Remove empty directories under *base* (bottom-up)."""
    for dirpath, _dirnames, _filenames in os.walk(base, topdown=False):
        dp = Path(dirpath)
        if dp == base:
            continue
        try:
            dp.rmdir()  # only succeeds if truly empty
        except OSError:
            pass

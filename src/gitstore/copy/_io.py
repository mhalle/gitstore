"""File I/O helpers: hashing, writing, tree conflict filtering."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..tree import GIT_FILEMODE_BLOB_EXECUTABLE, GIT_FILEMODE_LINK, _entry_at_path
from ._types import CopyError

if TYPE_CHECKING:
    from ..fs import FS


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

_HASH_CHUNK_SIZE = 65536


def _blob_hasher(size: int) -> hashlib._Hash:
    """Return a SHA-1 hasher pre-loaded with the git blob header.

    Git blob OID = SHA-1(``blob <size>\\0`` + content).
    """
    return hashlib.sha1(f"blob {size}\0".encode())


def _local_file_oid(base: Path, rel: str, *, follow_symlinks: bool = False) -> bytes:
    """Compute git blob OID for a local file by streaming through SHA-1.

    Symlinks hash their target string unless *follow_symlinks* is True,
    in which case they are dereferenced and the content is hashed.
    Regular files are streamed in chunks to avoid loading entire
    contents into memory.
    """
    return _local_file_oid_abs(base / rel, follow_symlinks=follow_symlinks)


def _local_file_oid_abs(full: Path, *, follow_symlinks: bool = False) -> bytes:
    """Compute git blob OID for a local file given its absolute path."""
    if not follow_symlinks and full.is_symlink():
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


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def _write_files_to_repo(batch, pairs, *, follow_symlinks=False, mode=None,
                         ignore_errors=False, errors=None):
    """Write ``(local_path, repo_path)`` pairs into a batch."""
    for local_path, repo_path in pairs:
        try:
            p = Path(local_path)
            if not follow_symlinks and p.is_symlink():
                batch.write_symlink(repo_path, os.readlink(local_path))
            else:
                batch.write_from(repo_path, p, mode=mode)
        except OSError as exc:
            if not ignore_errors:
                raise
            if errors is not None:
                errors.append(CopyError(path=local_path, error=str(exc)))


def _write_files_to_disk(fs: FS, pairs, *, base: Path | None = None,
                         ignore_errors=False, errors=None):
    """Write ``(repo_path, local_path)`` pairs to local disk.

    When *base* is given, path-clearing only removes blocking files
    within that root directory (never at or above *base*).
    """
    for repo_path, local_path in pairs:
        try:
            out = Path(local_path)
            # Clear blocking paths: if a parent is a file, remove it
            for parent in out.parents:
                if base is not None and parent == base:
                    break
                if parent.exists() and not parent.is_dir():
                    parent.unlink()
                    break
            # If dest is a directory but we need a file, remove the dir
            if out.is_dir() and not out.is_symlink():
                import shutil
                shutil.rmtree(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() or out.is_symlink():
                out.unlink()
            entry = _entry_at_path(fs._store._repo, fs._tree_oid, repo_path)
            if entry and entry[1] == GIT_FILEMODE_LINK:
                out.symlink_to(fs.readlink(repo_path))
            else:
                out.write_bytes(fs.read(repo_path))
                if entry and entry[1] == GIT_FILEMODE_BLOB_EXECUTABLE:
                    os.chmod(local_path, 0o755)
        except OSError as exc:
            if not ignore_errors:
                raise
            if errors is not None:
                errors.append(CopyError(path=local_path, error=str(exc)))


# ---------------------------------------------------------------------------
# Tree conflict filtering & cleanup
# ---------------------------------------------------------------------------

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

"""Low-level tree manipulation for gitstore.

Provides recursive tree rebuild and path-based read helpers
on top of pygit2's TreeBuilder.
"""

from __future__ import annotations

import os
import stat
from collections import defaultdict
from typing import Iterator, NamedTuple

from . import _compat as pygit2


class WalkEntry(NamedTuple):
    """A file entry yielded by :func:`walk_tree`."""

    name: str
    oid: pygit2.Oid
    filemode: int

    @property
    def file_type(self):
        """Return the :class:`~gitstore.copy._types.FileType` for this entry."""
        from .copy._types import FileType
        return FileType.from_filemode(self.filemode)


GIT_FILEMODE_TREE = 0o040000
GIT_FILEMODE_BLOB = 0o100644
GIT_FILEMODE_BLOB_EXECUTABLE = 0o100755
GIT_FILEMODE_LINK = 0o120000
GIT_OBJECT_TREE = pygit2.GIT_OBJECT_TREE


def _mode_from_disk(local_path: str) -> int:
    """Return git filemode based on the file's executable bit.

    Also validates the path — raises FileNotFoundError, PermissionError,
    or IsADirectoryError before any blob is created.
    """
    st = os.stat(local_path)
    if stat.S_ISDIR(st.st_mode):
        raise IsADirectoryError(local_path)
    if st.st_mode & 0o111:
        return GIT_FILEMODE_BLOB_EXECUTABLE
    return GIT_FILEMODE_BLOB


def _is_root_path(path: str | os.PathLike[str]) -> bool:
    """Return True if path represents the root (empty or only slashes)."""
    p = os.fspath(path)
    if os.name == "nt":
        p = p.replace("\\", "/")
    return p.strip("/") == ""


def _normalize_path(path: str | os.PathLike[str]) -> str:
    """Normalize a path: strip leading/trailing slashes, reject bad segments."""
    path = os.fspath(path)
    if os.name == "nt":
        path = path.replace("\\", "/")
    path = path.strip("/")
    if not path:
        raise ValueError("Path must not be empty")
    segments = path.split("/")
    for seg in segments:
        if not seg:
            raise ValueError(f"Empty segment in path: {path!r}")
        if seg in (".", ".."):
            raise ValueError(f"Invalid path segment: {seg!r}")
    return "/".join(segments)


def rebuild_tree(
    repo: pygit2.Repository,
    base_tree_oid: pygit2.Oid | None,
    writes: dict[str, bytes | tuple[bytes, int] | pygit2.Oid | tuple[pygit2.Oid, int]],
    removes: set[str],
) -> pygit2.Oid:
    """Rebuild a tree with writes and removes applied.

    Only the ancestor chain from changed leaves to root is rebuilt.
    Sibling subtrees are shared by hash reference.

    Args:
        repo: The pygit2 repository.
        base_tree_oid: OID of the existing tree (or None for empty).
        writes: Mapping of normalized path → blob data or (data, filemode).
        removes: Set of normalized paths to remove.

    Returns:
        OID of the new root tree.
    """
    # Group changes by first path segment
    sub_writes: dict[str, dict[str, bytes | tuple[bytes, int] | pygit2.Oid | tuple[pygit2.Oid, int]]] = defaultdict(dict)
    leaf_writes: dict[str, bytes | tuple[bytes, int] | pygit2.Oid | tuple[pygit2.Oid, int]] = {}
    sub_removes: dict[str, set[str]] = defaultdict(set)
    leaf_removes: set[str] = set()

    for path, data in writes.items():
        parts = path.split("/", 1)
        if len(parts) == 1:
            leaf_writes[parts[0]] = data
        else:
            sub_writes[parts[0]][parts[1]] = data

    for path in removes:
        parts = path.split("/", 1)
        if len(parts) == 1:
            leaf_removes.add(parts[0])
        else:
            sub_removes[parts[0]].add(parts[1])

    # Seed TreeBuilder from existing tree
    if base_tree_oid is not None:
        tb = repo.TreeBuilder(repo[base_tree_oid])
    else:
        tb = repo.TreeBuilder()

    # Collect existing subtree entries for dirs we need to recurse into
    existing_subtrees: dict[str, pygit2.Oid] = {}
    if base_tree_oid is not None:
        tree = repo[base_tree_oid]
        for entry in tree:
            if entry.filemode == GIT_FILEMODE_TREE:
                existing_subtrees[entry.name] = entry.id

    # Apply leaf writes (may overwrite existing tree entries)
    for name, value in leaf_writes.items():
        if isinstance(value, tuple):
            data_or_oid, mode = value
        else:
            data_or_oid, mode = value, GIT_FILEMODE_BLOB
        if isinstance(data_or_oid, pygit2.Oid):
            blob_oid = data_or_oid
        else:
            blob_oid = repo.create_blob(data_or_oid)
        tb.insert(name, blob_oid, mode)

    # Apply leaf removes (silently ignore missing — callers check existence)
    for name in leaf_removes:
        try:
            tb.remove(name)
        except pygit2.GitError:
            pass

    # Recurse into subtrees
    all_subdirs = set(sub_writes.keys()) | set(sub_removes.keys())
    for subdir in all_subdirs:
        existing_oid = existing_subtrees.get(subdir)
        # Check if there's a non-tree entry at this name that we need to replace
        if existing_oid is None and base_tree_oid is not None:
            try:
                entry = tree[subdir]
                if entry.filemode != GIT_FILEMODE_TREE:
                    # Remove the blob entry so we can replace with a tree
                    tb.remove(subdir)
            except KeyError:
                pass

        new_subtree_oid = rebuild_tree(
            repo,
            existing_oid,
            sub_writes.get(subdir, {}),
            sub_removes.get(subdir, set()),
        )

        # Prune empty directories
        new_subtree = repo[new_subtree_oid]
        if len(new_subtree) == 0:
            try:
                tb.remove(subdir)
            except pygit2.GitError:
                pass
        else:
            tb.insert(subdir, new_subtree_oid, GIT_FILEMODE_TREE)

    return tb.write()


def _walk_to(
    repo: pygit2.Repository, tree_oid: pygit2.Oid, path: str
) -> pygit2.Object:
    """Walk tree to the object at the given path."""
    segments = path.split("/")
    obj = repo[tree_oid]
    for i, seg in enumerate(segments):
        if obj.type != GIT_OBJECT_TREE:
            partial = "/".join(segments[: i])
            raise NotADirectoryError(partial)
        try:
            entry = obj[seg]
        except KeyError:
            raise FileNotFoundError(path)
        obj = repo[entry.id]
    return obj


def _entry_at_path(
    repo: pygit2.Repository, tree_oid: pygit2.Oid, path: str
) -> tuple[pygit2.Oid, int] | None:
    """Return (oid, filemode) of the entry at *path*, or None if missing."""
    segments = path.split("/")
    tree = repo[tree_oid]
    for i, seg in enumerate(segments):
        if tree.type != GIT_OBJECT_TREE:
            return None
        try:
            entry = tree[seg]
        except KeyError:
            return None
        if i < len(segments) - 1:
            tree = repo[entry.id]
        else:
            return (entry.id, entry.filemode)
    return None


def read_blob_at_path(
    repo: pygit2.Repository, tree_oid: pygit2.Oid, path: str | os.PathLike[str]
) -> bytes:
    """Read a blob at the given path in the tree."""
    path = _normalize_path(path)
    obj = _walk_to(repo, tree_oid, path)
    if obj.type == GIT_OBJECT_TREE:
        raise IsADirectoryError(path)
    return obj.data


def list_tree_at_path(
    repo: pygit2.Repository, tree_oid: pygit2.Oid, path: str | os.PathLike[str] | None = None
) -> list[str]:
    """List entries at the given path (or root if path is None)."""
    return [e.name for e in list_entries_at_path(repo, tree_oid, path)]


def list_entries_at_path(
    repo: pygit2.Repository, tree_oid: pygit2.Oid, path: str | os.PathLike[str] | None = None
) -> list[WalkEntry]:
    """List entries at the given path (or root if path is None).

    Returns :class:`WalkEntry` objects with *name*, *oid*, and *filemode*.
    Directories have ``filemode == GIT_FILEMODE_TREE``.
    """
    if path is None or _is_root_path(path):
        tree = repo[tree_oid]
    else:
        path = _normalize_path(path)
        obj = _walk_to(repo, tree_oid, path)
        if obj.type != GIT_OBJECT_TREE:
            raise NotADirectoryError(path)
        tree = obj
    return [WalkEntry(entry.name, entry.id, entry.filemode) for entry in tree]


def walk_tree(
    repo: pygit2.Repository,
    tree_oid: pygit2.Oid,
    prefix: str = "",
) -> Iterator[tuple[str, list[str], list[WalkEntry]]]:
    """Walk the tree recursively, yielding (dirpath, dirnames, file_entries).

    Each file entry is a :class:`WalkEntry` with *name*, *oid*, and *filemode*.
    """
    tree = repo[tree_oid]
    dirs: list[str] = []
    files: list[WalkEntry] = []
    dir_oids: list[tuple[str, pygit2.Oid]] = []

    for entry in tree:
        if entry.filemode == GIT_FILEMODE_TREE:
            dirs.append(entry.name)
            dir_oids.append((entry.name, entry.id))
        else:
            files.append(WalkEntry(entry.name, entry.id, entry.filemode))

    yield (prefix, dirs, files)

    for name, oid in dir_oids:
        child_prefix = f"{prefix}/{name}" if prefix else name
        yield from walk_tree(repo, oid, child_prefix)


def exists_at_path(
    repo: pygit2.Repository, tree_oid: pygit2.Oid, path: str | os.PathLike[str]
) -> bool:
    """Check if a path exists in the tree."""
    path = _normalize_path(path)
    try:
        _walk_to(repo, tree_oid, path)
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False

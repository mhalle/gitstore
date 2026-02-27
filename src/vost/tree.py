"""Low-level tree manipulation for vost.

Provides recursive tree rebuild and path-based read helpers
using dulwich's tree objects.
"""

from __future__ import annotations

import os
import stat
from collections import defaultdict
from typing import TYPE_CHECKING, Iterator, NamedTuple

from dulwich.objects import Tree as _DTree

if TYPE_CHECKING:
    from .repo import _Repository


class BlobOid(bytes):
    """A blob SHA used as a marker in write dicts to avoid re-hashing.

    Subclass of :class:`bytes`.  When a value in a write dict is a
    ``BlobOid``, the tree builder uses it directly instead of calling
    ``create_blob``.
    """
    __slots__ = ()


class GitError(Exception):
    """Raised when a low-level git tree operation fails."""


class TreeBuilder:
    """Wraps dulwich Tree construction."""

    def __init__(self, repo, base_tree=None):
        self._drepo = repo
        self._entries: dict[bytes, tuple[int, bytes]] = {}
        if base_tree is not None:
            for entry in base_tree.iteritems():
                self._entries[entry.path] = (entry.mode, entry.sha)

    def insert(self, name: str, oid: bytes, mode: int):
        self._entries[name.encode()] = (mode, oid)

    def remove(self, name: str):
        key = name.encode()
        if key not in self._entries:
            raise GitError(f"Entry not found: {name}")
        del self._entries[key]

    def write(self) -> bytes:
        tree = _DTree()
        for name_bytes, (mode, sha) in sorted(self._entries.items()):
            tree.add(name_bytes, mode, sha)
        self._drepo.object_store.add_object(tree)
        return tree.id


class WalkEntry(NamedTuple):
    """A file entry yielded by :meth:`~vost.FS.walk` and :meth:`~vost.FS.listdir`.

    Attributes:
        name: Entry name (file or directory basename).
        oid: Raw object ID (bytes).
        mode: Git filemode integer (e.g. ``0o100644``).
    """

    name: str
    oid: bytes
    mode: int

    @property
    def file_type(self):
        """Return the :class:`~vost.copy._types.FileType` for this entry."""
        from .copy._types import FileType
        return FileType.from_filemode(self.mode)


GIT_FILEMODE_TREE = 0o040000
GIT_FILEMODE_BLOB = 0o100644
GIT_FILEMODE_BLOB_EXECUTABLE = 0o100755
GIT_FILEMODE_LINK = 0o120000
GIT_OBJECT_TREE = 2  # dulwich Tree.type_num


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
    out: list[str] = []
    for seg in segments:
        if not seg:
            raise ValueError(f"Empty segment in path: {path!r}")
        if seg == "..":
            raise ValueError(f"Invalid path segment: {seg!r}")
        if seg == ".":
            continue  # collapse current-directory markers
        out.append(seg)
    if not out:
        raise ValueError("Path must not be empty")
    return "/".join(out)


def rebuild_tree(
    repo: _Repository,
    base_tree_oid: bytes | None,
    writes: dict[str, bytes | tuple[bytes, int] | bytes | tuple[bytes, int]],
    removes: set[str],
) -> bytes:
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
    sub_writes: dict[str, dict[str, bytes | tuple[bytes, int] | bytes | tuple[bytes, int]]] = defaultdict(dict)
    leaf_writes: dict[str, bytes | tuple[bytes, int] | bytes | tuple[bytes, int]] = {}
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
    existing_subtrees: dict[str, bytes] = {}
    if base_tree_oid is not None:
        tree = repo[base_tree_oid]
        for entry in tree.iteritems():
            if entry.mode == GIT_FILEMODE_TREE:
                existing_subtrees[entry.path.decode()] = entry.sha

    # Apply leaf writes (may overwrite existing tree entries)
    for name, value in leaf_writes.items():
        if isinstance(value, tuple):
            data_or_oid, mode = value
        else:
            data_or_oid, mode = value, GIT_FILEMODE_BLOB
        if isinstance(data_or_oid, BlobOid):
            blob_oid = data_or_oid
        else:
            blob_oid = repo.create_blob(data_or_oid)
        tb.insert(name, blob_oid, mode)

    # Apply leaf removes (silently ignore missing — callers check existence)
    for name in leaf_removes:
        try:
            tb.remove(name)
        except GitError:
            pass

    # Recurse into subtrees
    all_subdirs = set(sub_writes.keys()) | set(sub_removes.keys())
    for subdir in all_subdirs:
        existing_oid = existing_subtrees.get(subdir)
        # Check if there's a non-tree entry at this name that we need to replace
        if existing_oid is None and base_tree_oid is not None:
            try:
                mode, _sha = tree[subdir.encode()]
                if mode != GIT_FILEMODE_TREE:
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
            except GitError:
                pass
        else:
            tb.insert(subdir, new_subtree_oid, GIT_FILEMODE_TREE)

    return tb.write()


def _walk_to(
    repo: _Repository, tree_oid: bytes, path: str
):
    """Walk tree to the object at the given path."""
    segments = path.split("/")
    obj = repo[tree_oid]
    for i, seg in enumerate(segments):
        if obj.type_num != GIT_OBJECT_TREE:
            partial = "/".join(segments[: i])
            raise NotADirectoryError(partial)
        try:
            _mode, sha = obj[seg.encode()]
        except KeyError:
            raise FileNotFoundError(path)
        obj = repo[sha]
    return obj


def _entry_at_path(
    repo: _Repository, tree_oid: bytes, path: str
) -> tuple[bytes, int] | None:
    """Return (oid, filemode) of the entry at *path*, or None if missing."""
    segments = path.split("/")
    tree = repo[tree_oid]
    for i, seg in enumerate(segments):
        if tree.type_num != GIT_OBJECT_TREE:
            return None
        try:
            mode, sha = tree[seg.encode()]
        except KeyError:
            return None
        if i < len(segments) - 1:
            tree = repo[sha]
        else:
            return (sha, mode)
    return None


def read_blob_at_path(
    repo: _Repository, tree_oid: bytes, path: str | os.PathLike[str]
) -> bytes:
    """Read a blob at the given path in the tree."""
    path = _normalize_path(path)
    obj = _walk_to(repo, tree_oid, path)
    if obj.type_num == GIT_OBJECT_TREE:
        raise IsADirectoryError(path)
    return obj.data


def list_tree_at_path(
    repo: _Repository, tree_oid: bytes, path: str | os.PathLike[str] | None = None
) -> list[str]:
    """List entries at the given path (or root if path is None)."""
    return [e.name for e in list_entries_at_path(repo, tree_oid, path)]


def list_entries_at_path(
    repo: _Repository, tree_oid: bytes, path: str | os.PathLike[str] | None = None
) -> list[WalkEntry]:
    """List entries at the given path (or root if path is None).

    Returns :class:`WalkEntry` objects with *name*, *oid*, and *mode*.
    Directories have ``mode == GIT_FILEMODE_TREE``.
    """
    if path is None or _is_root_path(path):
        tree = repo[tree_oid]
    else:
        path = _normalize_path(path)
        obj = _walk_to(repo, tree_oid, path)
        if obj.type_num != GIT_OBJECT_TREE:
            raise NotADirectoryError(path)
        tree = obj
    return [WalkEntry(entry.path.decode(), entry.sha, entry.mode) for entry in tree.iteritems()]


def walk_tree(
    repo: _Repository,
    tree_oid: bytes,
    prefix: str = "",
) -> Iterator[tuple[str, list[str], list[WalkEntry]]]:
    """Walk the tree recursively, yielding (dirpath, dirnames, file_entries).

    Each file entry is a :class:`WalkEntry` with *name*, *oid*, and *filemode*.
    """
    tree = repo[tree_oid]
    dirs: list[str] = []
    files: list[WalkEntry] = []
    dir_oids: list[tuple[str, bytes]] = []

    for entry in tree.iteritems():
        name = entry.path.decode()
        if entry.mode == GIT_FILEMODE_TREE:
            dirs.append(name)
            dir_oids.append((name, entry.sha))
        else:
            files.append(WalkEntry(name, entry.sha, entry.mode))

    yield (prefix, dirs, files)

    for name, oid in dir_oids:
        child_prefix = f"{prefix}/{name}" if prefix else name
        yield from walk_tree(repo, oid, child_prefix)


def _count_subdirs(repo, tree_oid: bytes) -> int:
    """Count immediate subdirectory entries in a tree (no recursion)."""
    tree = repo[tree_oid]
    return sum(1 for e in tree.iteritems() if e.mode == GIT_FILEMODE_TREE)


def exists_at_path(
    repo: _Repository, tree_oid: bytes, path: str | os.PathLike[str]
) -> bool:
    """Check if a path exists in the tree."""
    path = _normalize_path(path)
    try:
        _walk_to(repo, tree_oid, path)
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False

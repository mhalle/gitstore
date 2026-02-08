"""FS: immutable snapshot of a committed tree state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from ._lock import repo_lock
from .exceptions import StaleSnapshotError
from .tree import (
    _is_root_path,
    _normalize_path,
    read_blob_at_path,
    list_tree_at_path,
    walk_tree,
    exists_at_path,
    rebuild_tree,
)

if TYPE_CHECKING:
    from .repo import GitStore


class FS:
    """An immutable snapshot of a committed tree.

    Read-only when branch is None (tag snapshot).
    Writable when branch is set — writes auto-commit and return a new FS.
    """

    def __init__(self, gitstore: GitStore, commit_oid, branch: str | None = None):
        self._store = gitstore
        self._commit_oid = commit_oid
        self._branch = branch
        commit = gitstore._repo[commit_oid]
        self._tree_oid = commit.tree_id

    @property
    def _writable(self) -> bool:
        return self._branch is not None

    def __repr__(self) -> str:
        short = str(self._commit_oid)[:7]
        if self._branch:
            return f"FS(branch={self._branch!r}, commit={short})"
        return f"FS(commit={short})"

    @property
    def hash(self) -> str:
        return str(self._commit_oid)

    @property
    def branch(self) -> str | None:
        return self._branch

    @property
    def message(self) -> str:
        return self._store._repo[self._commit_oid].message.rstrip("\n")

    # --- Read operations ---

    def read(self, path: str | os.PathLike[str]) -> bytes:
        return read_blob_at_path(self._store._repo, self._tree_oid, path)

    def ls(self, path: str | os.PathLike[str] | None = None) -> list[str]:
        return list_tree_at_path(self._store._repo, self._tree_oid, path)

    def walk(self, path: str | os.PathLike[str] | None = None) -> Iterator[tuple[str, list[str], list[str]]]:
        if path is None or _is_root_path(path):
            yield from walk_tree(self._store._repo, self._tree_oid)
        else:
            from .tree import _walk_to, GIT_OBJECT_TREE
            path = _normalize_path(path)
            obj = _walk_to(self._store._repo, self._tree_oid, path)
            if obj.type != GIT_OBJECT_TREE:
                raise NotADirectoryError(path)
            yield from walk_tree(self._store._repo, obj.id, path)

    def exists(self, path: str | os.PathLike[str]) -> bool:
        return exists_at_path(self._store._repo, self._tree_oid, path)

    def open(self, path: str | os.PathLike[str], mode: str = "rb"):
        if mode == "rb":
            from ._fileobj import ReadableFile
            return ReadableFile(self.read(path))
        elif mode == "wb":
            if not self._writable:
                raise PermissionError("Cannot write to a read-only snapshot")
            from ._fileobj import WritableFile
            return WritableFile(self, path)
        else:
            raise ValueError(f"Unsupported mode: {mode!r}")

    # --- Write operations ---

    def _commit_changes(
        self,
        writes: dict[str, bytes],
        removes: set[str],
        message: str,
    ) -> FS:
        if not self._writable:
            raise PermissionError("Cannot write to a read-only snapshot")

        repo = self._store._repo
        sig = self._store._signature

        new_tree_oid = rebuild_tree(repo, self._tree_oid, writes, removes)

        # Create commit object without moving the ref
        new_commit_oid = repo.create_commit(
            None,
            sig,
            sig,
            message,
            new_tree_oid,
            [self._commit_oid],
        )

        # Atomic check-and-update under file lock
        ref_name = f"refs/heads/{self._branch}"
        with repo_lock(repo.path):
            ref = repo.references[ref_name]
            if ref.resolve().target != self._commit_oid:
                raise StaleSnapshotError(
                    f"Branch {self._branch!r} has advanced since this snapshot"
                )
            ref.set_target(new_commit_oid)

        return FS(self._store, new_commit_oid, branch=self._branch)

    def write(self, path: str | os.PathLike[str], data: bytes) -> FS:
        path = _normalize_path(path)
        return self._commit_changes({path: data}, set(), f"Write {path}")

    def remove(self, path: str | os.PathLike[str]) -> FS:
        path = _normalize_path(path)
        if not self.exists(path):
            raise FileNotFoundError(path)
        return self._commit_changes({}, {path}, f"Remove {path}")

    def batch(self):
        from .batch import Batch
        return Batch(self)

    # --- Dump ---

    def dump(self, path: str | Path) -> None:
        """Write the tree contents to a directory on the filesystem."""
        path = Path(path)
        for dirpath, dirnames, filenames in self.walk():
            dir_on_disk = path / dirpath if dirpath else path
            dir_on_disk.mkdir(parents=True, exist_ok=True)
            for filename in filenames:
                store_path = f"{dirpath}/{filename}" if dirpath else filename
                (dir_on_disk / filename).write_bytes(self.read(store_path))

    # --- History ---

    @property
    def parent(self) -> FS | None:
        commit = self._store._repo[self._commit_oid]
        if not commit.parents:
            return None
        return FS(self._store, commit.parents[0].id, branch=self._branch)

    def log(self) -> Iterator[FS]:
        current: FS | None = self
        while current is not None:
            yield current
            current = current.parent

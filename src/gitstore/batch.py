"""Batch context manager for gitstore."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .tree import GIT_OBJECT_TREE, _normalize_path, _walk_to, exists_at_path

if TYPE_CHECKING:
    from .fs import FS


class Batch:
    """Accumulates writes and removes, commits once on exit."""

    def __init__(self, fs: FS, message: str | None = None):
        if not fs._writable:
            raise PermissionError("Cannot batch on a read-only snapshot")
        self._fs = fs
        self._message = message
        self._writes: dict[str, bytes] = {}
        self._removes: set[str] = set()
        self._ops: list[str] = []
        self._closed = False
        self.fs: FS | None = None

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Batch is closed")

    def write(self, path: str | os.PathLike[str], data: bytes) -> None:
        self._check_open()
        path = _normalize_path(path)
        self._removes.discard(path)
        self._writes[path] = data
        self._ops.append(f"Write {path}")

    def remove(self, path: str | os.PathLike[str]) -> None:
        self._check_open()
        path = _normalize_path(path)
        pending_write = path in self._writes
        repo = self._fs._store._repo
        exists_in_base = exists_at_path(repo, self._fs._tree_oid, path)
        if not pending_write and not exists_in_base:
            raise FileNotFoundError(path)
        # Check for directory in the base tree — even if there's a pending
        # write, we must not add a directory path to _removes.
        if exists_in_base:
            obj = _walk_to(repo, self._fs._tree_oid, path)
            if obj.type == GIT_OBJECT_TREE:
                raise IsADirectoryError(path)
        self._writes.pop(path, None)
        if exists_in_base:
            self._removes.add(path)
        self._ops.append(f"Remove {path}")

    def open(self, path: str | os.PathLike[str], mode: str = "wb"):
        self._check_open()
        if mode != "wb":
            raise ValueError(f"Batch open only supports 'wb' mode, got {mode!r}")
        from ._fileobj import BatchWritableFile
        return BatchWritableFile(self, path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._closed = True
            return False

        if not self._writes and not self._removes:
            self.fs = self._fs
            self._closed = True
            return False

        message = self._message or "Batch: " + "; ".join(self._ops)
        self.fs = self._fs._commit_changes(self._writes, self._removes, message)
        self._closed = True
        return False

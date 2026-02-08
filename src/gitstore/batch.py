"""Batch context manager for gitstore."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .tree import _normalize_path

if TYPE_CHECKING:
    from .fs import FS


class Batch:
    """Accumulates writes and removes, commits once on exit."""

    def __init__(self, fs: FS):
        if not fs._writable:
            raise PermissionError("Cannot batch on a read-only snapshot")
        self._fs = fs
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
        self._writes.pop(path, None)
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

        message = "Batch: " + "; ".join(self._ops)
        self.fs = self._fs._commit_changes(self._writes, self._removes, message)
        self._closed = True
        return False

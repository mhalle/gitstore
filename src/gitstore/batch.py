"""Batch context manager for gitstore."""

from __future__ import annotations

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
        self.fs: FS | None = None

    def write(self, path: str, data: bytes) -> None:
        path = _normalize_path(path)
        self._removes.discard(path)
        self._writes[path] = data
        self._ops.append(f"Write {path}")

    def remove(self, path: str) -> None:
        path = _normalize_path(path)
        self._writes.pop(path, None)
        self._removes.add(path)
        self._ops.append(f"Remove {path}")

    def open(self, path: str, mode: str = "wb"):
        if mode != "wb":
            raise ValueError(f"Batch open only supports 'wb' mode, got {mode!r}")
        from ._fileobj import BatchWritableFile
        return BatchWritableFile(self, path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            return False

        if not self._writes and not self._removes:
            self.fs = self._fs
            return False

        message = "Batch: " + "; ".join(self._ops)
        self.fs = self._fs._commit_changes(self._writes, self._removes, message)
        return False

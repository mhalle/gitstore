"""Batch context manager for gitstore."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .tree import GIT_FILEMODE_BLOB, GIT_FILEMODE_LINK, GIT_OBJECT_TREE, _mode_from_disk, _normalize_path, _walk_to, exists_at_path

if TYPE_CHECKING:
    from .copy._types import FileType
    from .fs import FS


class Batch:
    """Accumulates writes and removes, commits once on exit."""

    def __init__(self, fs: FS, message: str | None = None, operation: str | None = None):
        if not fs._writable:
            raise fs._readonly_error("batch on")
        self._fs = fs
        self._repo = fs._store._repo
        self._message = message
        self._operation = operation
        self._writes: dict[str, bytes | tuple[bytes, int] | bytes | tuple[bytes, int]] = {}
        self._removes: set[str] = set()
        self._closed = False
        self.fs: FS | None = None

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Batch is closed")

    def write(self, path: str | os.PathLike[str], data: bytes, *, mode: FileType | int | None = None) -> None:
        from .copy._types import FileType
        if isinstance(mode, FileType):
            mode = mode.filemode
        self._check_open()
        path = _normalize_path(path)
        self._removes.discard(path)
        blob_oid = self._repo.create_blob(data)
        self._writes[path] = (blob_oid, mode) if mode is not None else blob_oid

    def write_from_file(self, path: str | os.PathLike[str], local_path: str | os.PathLike[str], *, mode: FileType | int | None = None) -> None:
        from .copy._types import FileType
        if isinstance(mode, FileType):
            mode = mode.filemode
        self._check_open()
        path = _normalize_path(path)
        local_path = os.fspath(local_path)
        self._removes.discard(path)
        detected_mode = _mode_from_disk(local_path)
        if mode is None:
            mode = detected_mode
        blob_oid = self._repo.create_blob_fromdisk(local_path)
        self._writes[path] = (blob_oid, mode) if mode != GIT_FILEMODE_BLOB else blob_oid

    def write_symlink(self, path: str | os.PathLike[str], target: str) -> None:
        self._check_open()
        path = _normalize_path(path)
        self._removes.discard(path)
        blob_oid = self._repo.create_blob(target.encode())
        self._writes[path] = (blob_oid, GIT_FILEMODE_LINK)

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
            if obj.type_num == GIT_OBJECT_TREE:
                raise IsADirectoryError(path)
        self._writes.pop(path, None)
        if exists_in_base:
            self._removes.add(path)

    def open(self, path: str | os.PathLike[str], mode: str = "wb"):
        self._check_open()
        if mode != "wb":
            raise ValueError(f"Batch open only supports 'wb' mode, got {mode!r}")
        from ._fileobj import BatchWritableFile
        return BatchWritableFile(self, path)

    def commit(self) -> None:
        """Explicitly commit the batch, like ``__exit__`` with no exception.

        After calling this the batch is closed and no further writes are
        allowed.  The resulting FS is available as ``self.fs``.
        """
        self._check_open()

        if not self._writes and not self._removes:
            self.fs = self._fs
            self._closed = True
            return

        self.fs = self._fs._commit_changes(self._writes, self._removes, self._message, self._operation)
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._closed = True
            return False

        if self._closed:
            # Already committed via commit()
            return False

        if not self._writes and not self._removes:
            self.fs = self._fs
            self._closed = True
            return False

        # Let _commit_changes build changes and generate message
        self.fs = self._fs._commit_changes(self._writes, self._removes, self._message, self._operation)
        self._closed = True
        return False

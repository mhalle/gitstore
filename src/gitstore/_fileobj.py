"""File-like objects for gitstore."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fs import FS
    from .batch import Batch


class ReadableFile:
    """Read-only file-like object wrapping bytes."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._buf.seek(offset, whence)

    def tell(self) -> int:
        return self._buf.tell()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class WritableFile:
    """Writable file-like object that commits on close."""

    def __init__(self, fs: FS, path: str):
        self._fs = fs
        self._path = path
        self._buf = io.BytesIO()
        self._closed = False
        self.fs: FS | None = None

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        return self._buf.write(data)

    def close(self) -> None:
        if not self._closed:
            self.fs = self._fs.write(self._path, self._buf.getvalue())
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.close()
        else:
            self._closed = True
        return False


class BatchWritableFile:
    """Writable file-like object that stages to a batch on close."""

    def __init__(self, batch: Batch, path: str):
        self._batch = batch
        self._path = path
        self._buf = io.BytesIO()
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        return self._buf.write(data)

    def close(self) -> None:
        if not self._closed:
            self._batch.write(self._path, self._buf.getvalue())
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.close()
        else:
            self._closed = True
        return False

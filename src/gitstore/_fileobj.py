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
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        return self._buf.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        return self._buf.seek(offset, whence)

    def tell(self) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        return self._buf.tell()

    def close(self) -> None:
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class WritableFile:
    """Writable file-like object that commits on close."""

    def __init__(self, fs: FS, path: str):
        self._fs = fs
        self._path = path
        self._buf = io.BytesIO()
        self._closed = False
        self.fs: FS | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

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

    @property
    def closed(self) -> bool:
        return self._closed

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

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

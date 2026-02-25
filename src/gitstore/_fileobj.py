"""File-like objects for gitstore."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fs import FS
    from .batch import Batch


class WritableFile:
    """Writable file-like object that commits on close."""

    def __init__(self, fs: FS, path: str, encoding: str | None = None):
        self._fs = fs
        self._path = path
        self._buf = io.BytesIO()
        self._encoding = encoding
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

    def write(self, data: bytes | str) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        if self._encoding:
            if not isinstance(data, str):
                raise TypeError("expected str for text mode writer")
            data = data.encode(self._encoding)
        elif not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("expected bytes for binary mode writer")
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

    def __init__(self, batch: Batch, path: str, encoding: str | None = None):
        self._batch = batch
        self._path = path
        self._buf = io.BytesIO()
        self._encoding = encoding
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

    def write(self, data: bytes | str) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        if self._encoding:
            if not isinstance(data, str):
                raise TypeError("expected str for text mode writer")
            data = data.encode(self._encoding)
        elif not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("expected bytes for binary mode writer")
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

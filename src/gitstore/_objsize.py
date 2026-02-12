"""Efficient object size queries without loading full content.

For non-delta packed objects, reads only the pack entry header.
For loose objects, decompresses only the object header.
For delta objects, falls back to full resolution via dulwich.
"""

from __future__ import annotations

import os
import zlib


class ObjectSizer:
    """Batch-efficient object size lookup.

    Usage::

        with ObjectSizer(dulwich_object_store) as sizer:
            size = sizer.size(sha_hex)

    *sha_hex* is a 40-char hex bytes SHA (dulwich native format).
    """

    __slots__ = ("_store", "_pack_fds", "_pack_index")

    def __init__(self, object_store):
        self._store = object_store
        self._pack_fds: dict[str, object] = {}
        self._pack_index: dict[bytes, tuple[str, int]] | None = None

    # -- public API ----------------------------------------------------------

    def size(self, sha_hex: bytes) -> int:
        """Return the decompressed size of the object."""
        if self._pack_index is None:
            self._build_pack_index()

        sha_raw = bytes.fromhex(
            sha_hex.decode() if isinstance(sha_hex, bytes) else sha_hex
        )

        entry = self._pack_index.get(sha_raw)  # type: ignore[union-attr]
        if entry is not None:
            fname, offset = entry
            obj_type, obj_size = self._read_pack_header(fname, offset)
            if obj_type <= 4:  # commit=1, tree=2, blob=3, tag=4
                return obj_size
            # OFS_DELTA=6, REF_DELTA=7 — need full decompression
            return self._store[sha_hex].raw_length()

        # Loose object
        return self._read_loose_header(sha_hex)

    # -- internals -----------------------------------------------------------

    def _build_pack_index(self):
        self._pack_index = {}
        for pack in self._store.packs:
            fname = pack.data._filename
            for sha_raw, offset, _crc32 in pack.index.iterentries():
                self._pack_index[sha_raw] = (fname, offset)

    def _read_pack_header(self, filename: str, offset: int) -> tuple[int, int]:
        """Read type and decompressed size from a pack entry header."""
        f = self._pack_fds.get(filename)
        if f is None:
            f = open(filename, "rb")
            self._pack_fds[filename] = f

        f.seek(offset)
        byte = f.read(1)[0]
        obj_type = (byte >> 4) & 0x07
        size = byte & 0x0F
        shift = 4
        while byte & 0x80:
            byte = f.read(1)[0]
            size |= (byte & 0x7F) << shift
            shift += 7
        return obj_type, size

    def _read_loose_header(self, sha_hex: bytes) -> int:
        """Read size from a loose object header."""
        h = sha_hex.decode() if isinstance(sha_hex, bytes) else sha_hex
        path = os.path.join(self._store.path, h[:2], h[2:])
        with open(path, "rb") as f:
            d = zlib.decompressobj()
            header = d.decompress(f.read(64), 256)
        nul = header.index(b"\x00")
        _, size_str = header[:nul].split(b" ", 1)
        return int(size_str)

    # -- context manager -----------------------------------------------------

    def close(self):
        for fd in self._pack_fds.values():
            fd.close()
        self._pack_fds.clear()
        self._pack_index = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

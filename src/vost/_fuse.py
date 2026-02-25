"""Read-only FUSE mount for vost."""

from __future__ import annotations

import errno
import os
import stat
import sys
import threading
from typing import TYPE_CHECKING

try:
    import mfusepy
except OSError as _exc:
    raise ImportError(f"FUSE support unavailable: {_exc}") from _exc

from .tree import (
    GIT_FILEMODE_BLOB,
    GIT_FILEMODE_BLOB_EXECUTABLE,
    GIT_FILEMODE_LINK,
    GIT_FILEMODE_TREE,
)

if TYPE_CHECKING:
    from .fs import FS


def _git_mode_to_stat(git_mode: int) -> int:
    """Convert a git filemode to a POSIX stat mode."""
    if git_mode == GIT_FILEMODE_TREE:
        return stat.S_IFDIR | 0o755
    if git_mode == GIT_FILEMODE_BLOB_EXECUTABLE:
        return stat.S_IFREG | 0o755
    if git_mode == GIT_FILEMODE_LINK:
        return stat.S_IFLNK | 0o777
    # GIT_FILEMODE_BLOB and anything else
    return stat.S_IFREG | 0o644


def _fuse_path(path: str) -> str | None:
    """Convert FUSE path (``/foo/bar``) to vost path (``foo/bar``).

    Returns ``None`` for the root directory.
    """
    stripped = path.lstrip("/")
    return stripped if stripped else None


class GitStoreOperations(mfusepy.Operations):
    """Read-only FUSE operations backed by a vost FS snapshot."""

    def __init__(self, fs: FS):
        self._fs = fs
        self._lock = threading.Lock()
        self._uid = os.getuid()
        self._gid = os.getgid()

    def getattr(self, path, fh=None):
        gs_path = _fuse_path(path)
        with self._lock:
            try:
                st = self._fs.stat(gs_path)
            except FileNotFoundError:
                raise mfusepy.FuseOSError(errno.ENOENT)
            except NotADirectoryError:
                raise mfusepy.FuseOSError(errno.ENOTDIR)

        return {
            "st_mode": _git_mode_to_stat(st.mode),
            "st_size": st.size,
            "st_nlink": st.nlink,
            "st_mtime": st.mtime,
            "st_atime": st.mtime,
            "st_ctime": st.mtime,
            "st_uid": self._uid,
            "st_gid": self._gid,
        }

    def readdir(self, path, fh):
        gs_path = _fuse_path(path)
        with self._lock:
            try:
                entries = self._fs.listdir(gs_path)
            except FileNotFoundError:
                raise mfusepy.FuseOSError(errno.ENOENT)
            except NotADirectoryError:
                raise mfusepy.FuseOSError(errno.ENOTDIR)
        yield "."
        yield ".."
        for entry in entries:
            yield entry.name

    def read(self, path, size, offset, fh):
        gs_path = _fuse_path(path)
        with self._lock:
            try:
                return self._fs.read(gs_path, offset=offset, size=size)
            except FileNotFoundError:
                raise mfusepy.FuseOSError(errno.ENOENT)
            except IsADirectoryError:
                raise mfusepy.FuseOSError(errno.EISDIR)

    def readlink(self, path):
        gs_path = _fuse_path(path)
        with self._lock:
            try:
                return self._fs.readlink(gs_path)
            except FileNotFoundError:
                raise mfusepy.FuseOSError(errno.ENOENT)
            except ValueError:
                raise mfusepy.FuseOSError(errno.EINVAL)

    def open(self, path, flags):
        accmode = flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)
        if accmode != os.O_RDONLY:
            raise mfusepy.FuseOSError(errno.EROFS)
        return 0

    def access(self, path, amode):
        if amode & os.W_OK:
            raise mfusepy.FuseOSError(errno.EROFS)
        gs_path = _fuse_path(path)
        with self._lock:
            if gs_path is not None and not self._fs.exists(gs_path):
                raise mfusepy.FuseOSError(errno.ENOENT)
        return 0

    def statfs(self, path):
        return {
            "f_bsize": 4096,
            "f_frsize": 4096,
            "f_blocks": 0,
            "f_bfree": 0,
            "f_bavail": 0,
            "f_files": 0,
            "f_ffree": 0,
            "f_favail": 0,
            "f_namemax": 255,
        }

    def utimens(self, path, times=None):
        raise mfusepy.FuseOSError(errno.EROFS)

    def destroy(self, path):
        with self._lock:
            self._fs.close()

    # Disable write operations — mfusepy returns ENOSYS at kernel level for None
    chmod = None
    chown = None
    create = None
    link = None
    mkdir = None
    mknod = None
    rename = None
    rmdir = None
    symlink = None
    truncate = None
    unlink = None
    write = None


def mount(
    fs: FS,
    mountpoint: str,
    *,
    foreground: bool = True,
    debug: bool = False,
    nothreads: bool = False,
    allow_other: bool = False,
) -> None:
    """Mount a vost FS snapshot as a read-only FUSE filesystem.

    Blocks until the filesystem is unmounted (Ctrl-C or ``umount``).
    """
    ref_label = fs.ref_name or fs.commit_hash[:12]
    ops = GitStoreOperations(fs)

    fuse_kwargs: dict = {
        "ro": True,
        "attr_timeout": 3600,
        "entry_timeout": 3600,
        "fsname": f"vost:{ref_label}",
        "subtype": "vost",
    }

    if allow_other:
        fuse_kwargs["allow_other"] = True

    if sys.platform == "darwin":
        fuse_kwargs["noappledouble"] = True
        fuse_kwargs["noapplexattr"] = True
        fuse_kwargs["volname"] = f"vost ({ref_label})"

    mfusepy.FUSE(
        ops,
        mountpoint,
        foreground=foreground,
        debug=debug,
        nothreads=nothreads,
        **fuse_kwargs,
    )

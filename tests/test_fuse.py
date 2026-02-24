"""Unit tests for the FUSE operations layer.

Tests call GitStoreOperations methods directly — no actual FUSE mount needed.
"""

from __future__ import annotations

import errno
import os
import stat

import pytest

try:
    import mfusepy
except (ImportError, OSError):
    pytest.skip("mfusepy/libfuse not available", allow_module_level=True)

from gitstore import GitStore
from gitstore._fuse import GitStoreOperations, _fuse_path, _git_mode_to_stat
from gitstore.tree import (
    GIT_FILEMODE_BLOB,
    GIT_FILEMODE_BLOB_EXECUTABLE,
    GIT_FILEMODE_LINK,
    GIT_FILEMODE_TREE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _errno_of(exc_info):
    """Extract the errno from a FuseOSError."""
    return exc_info.value.errno


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fuse_fs(tmp_path):
    """Create a repo with test files and return (GitStoreOperations, FS)."""
    store = GitStore.open(tmp_path / "test.git")
    fs = store.branches["main"]
    fs = fs.write("hello.txt", b"Hello, world!")
    fs = fs.write("run.sh", b"#!/bin/sh\necho hi", mode=0o100755)
    fs = fs.write_symlink("link.txt", "hello.txt")
    fs = fs.write("src/main.py", b"print('hello')")

    # Force read-only
    from gitstore.fs import FS
    fs = FS(store, fs._commit_oid, ref_name=fs.ref_name, writable=False)

    ops = GitStoreOperations(fs)
    return ops, fs


# ---------------------------------------------------------------------------
# _fuse_path
# ---------------------------------------------------------------------------

class TestFusePath:
    def test_root(self):
        assert _fuse_path("/") is None

    def test_file(self):
        assert _fuse_path("/hello.txt") == "hello.txt"

    def test_nested(self):
        assert _fuse_path("/src/main.py") == "src/main.py"


# ---------------------------------------------------------------------------
# _git_mode_to_stat
# ---------------------------------------------------------------------------

class TestGitModeToStat:
    def test_blob(self):
        result = _git_mode_to_stat(GIT_FILEMODE_BLOB)
        assert result == stat.S_IFREG | 0o644

    def test_executable(self):
        result = _git_mode_to_stat(GIT_FILEMODE_BLOB_EXECUTABLE)
        assert result == stat.S_IFREG | 0o755

    def test_link(self):
        result = _git_mode_to_stat(GIT_FILEMODE_LINK)
        assert result == stat.S_IFLNK | 0o777

    def test_tree(self):
        result = _git_mode_to_stat(GIT_FILEMODE_TREE)
        assert result == stat.S_IFDIR | 0o755


# ---------------------------------------------------------------------------
# getattr
# ---------------------------------------------------------------------------

class TestGetattr:
    def test_root(self, fuse_fs):
        ops, fs = fuse_fs
        attrs = ops.getattr("/")
        assert stat.S_ISDIR(attrs["st_mode"])
        assert attrs["st_nlink"] >= 2

    def test_file(self, fuse_fs):
        ops, fs = fuse_fs
        attrs = ops.getattr("/hello.txt")
        assert stat.S_ISREG(attrs["st_mode"])
        assert attrs["st_mode"] & 0o777 == 0o644
        assert attrs["st_size"] == len(b"Hello, world!")
        assert attrs["st_nlink"] == 1

    def test_executable(self, fuse_fs):
        ops, fs = fuse_fs
        attrs = ops.getattr("/run.sh")
        assert stat.S_ISREG(attrs["st_mode"])
        assert attrs["st_mode"] & 0o777 == 0o755

    def test_symlink(self, fuse_fs):
        ops, fs = fuse_fs
        attrs = ops.getattr("/link.txt")
        assert stat.S_ISLNK(attrs["st_mode"])

    def test_directory(self, fuse_fs):
        ops, fs = fuse_fs
        attrs = ops.getattr("/src")
        assert stat.S_ISDIR(attrs["st_mode"])
        assert attrs["st_nlink"] >= 2

    def test_nonexistent(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.getattr("/nope.txt")
        assert _errno_of(exc_info) == errno.ENOENT

    def test_uid_gid(self, fuse_fs):
        ops, fs = fuse_fs
        attrs = ops.getattr("/hello.txt")
        assert attrs["st_uid"] == os.getuid()
        assert attrs["st_gid"] == os.getgid()

    def test_mtime(self, fuse_fs):
        ops, fs = fuse_fs
        attrs = ops.getattr("/hello.txt")
        assert isinstance(attrs["st_mtime"], float)
        assert attrs["st_mtime"] > 0


# ---------------------------------------------------------------------------
# readdir
# ---------------------------------------------------------------------------

class TestReaddir:
    def test_root(self, fuse_fs):
        ops, fs = fuse_fs
        entries = list(ops.readdir("/", None))
        assert "." in entries
        assert ".." in entries
        assert "hello.txt" in entries
        assert "run.sh" in entries
        assert "link.txt" in entries
        assert "src" in entries

    def test_subdirectory(self, fuse_fs):
        ops, fs = fuse_fs
        entries = list(ops.readdir("/src", None))
        assert "." in entries
        assert ".." in entries
        assert "main.py" in entries

    def test_nonexistent(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            list(ops.readdir("/nope", None))
        assert _errno_of(exc_info) == errno.ENOENT


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

class TestRead:
    def test_full_read(self, fuse_fs):
        ops, fs = fuse_fs
        data = ops.read("/hello.txt", 4096, 0, None)
        assert data == b"Hello, world!"

    def test_partial_size(self, fuse_fs):
        ops, fs = fuse_fs
        data = ops.read("/hello.txt", 5, 0, None)
        assert data == b"Hello"

    def test_offset(self, fuse_fs):
        ops, fs = fuse_fs
        data = ops.read("/hello.txt", 5, 7, None)
        assert data == b"world"

    def test_directory_read(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.read("/src", 4096, 0, None)
        assert _errno_of(exc_info) == errno.EISDIR

    def test_nonexistent(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.read("/nope.txt", 4096, 0, None)
        assert _errno_of(exc_info) == errno.ENOENT


# ---------------------------------------------------------------------------
# readlink
# ---------------------------------------------------------------------------

class TestReadlink:
    def test_valid_symlink(self, fuse_fs):
        ops, fs = fuse_fs
        target = ops.readlink("/link.txt")
        assert target == "hello.txt"

    def test_non_symlink(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.readlink("/hello.txt")
        assert _errno_of(exc_info) == errno.EINVAL

    def test_nonexistent(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.readlink("/nope.txt")
        assert _errno_of(exc_info) == errno.ENOENT


# ---------------------------------------------------------------------------
# open
# ---------------------------------------------------------------------------

class TestOpen:
    def test_rdonly(self, fuse_fs):
        ops, fs = fuse_fs
        assert ops.open("/hello.txt", os.O_RDONLY) == 0

    def test_wronly(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.open("/hello.txt", os.O_WRONLY)
        assert _errno_of(exc_info) == errno.EROFS

    def test_rdwr(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.open("/hello.txt", os.O_RDWR)
        assert _errno_of(exc_info) == errno.EROFS


# ---------------------------------------------------------------------------
# access
# ---------------------------------------------------------------------------

class TestAccess:
    def test_r_ok(self, fuse_fs):
        ops, fs = fuse_fs
        assert ops.access("/hello.txt", os.R_OK) == 0

    def test_w_ok(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.access("/hello.txt", os.W_OK)
        assert _errno_of(exc_info) == errno.EROFS

    def test_nonexistent(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.access("/nope.txt", os.R_OK)
        assert _errno_of(exc_info) == errno.ENOENT

    def test_root_r_ok(self, fuse_fs):
        ops, fs = fuse_fs
        assert ops.access("/", os.R_OK) == 0


# ---------------------------------------------------------------------------
# statfs
# ---------------------------------------------------------------------------

class TestStatfs:
    def test_statfs(self, fuse_fs):
        ops, fs = fuse_fs
        result = ops.statfs("/")
        assert result["f_bfree"] == 0
        assert result["f_bsize"] == 4096
        assert result["f_namemax"] == 255


# ---------------------------------------------------------------------------
# utimens
# ---------------------------------------------------------------------------

class TestUtimens:
    def test_erofs(self, fuse_fs):
        ops, fs = fuse_fs
        with pytest.raises(mfusepy.FuseOSError) as exc_info:
            ops.utimens("/hello.txt")
        assert _errno_of(exc_info) == errno.EROFS


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------

class TestDestroy:
    def test_idempotent_close(self, fuse_fs):
        ops, fs = fuse_fs
        ops.destroy("/")
        ops.destroy("/")  # second call should not raise

"""Tests for batch context manager."""

import os
import stat

import pygit2
import pytest

from gitstore import GitStore, StaleSnapshotError
from gitstore.tree import GIT_FILEMODE_BLOB_EXECUTABLE


@pytest.fixture
def repo_fs(tmp_path):
    repo = GitStore.open(tmp_path / "test.git", create="main")
    fs = repo.branches["main"]
    fs = fs.write("a.txt", b"a")
    return repo, fs


class TestBatch:
    def test_multiple_writes_single_commit(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            b.write("x.txt", b"x")
            b.write("y.txt", b"y")
        new_fs = b.fs
        assert new_fs.read("x.txt") == b"x"
        assert new_fs.read("y.txt") == b"y"
        # Should be exactly one commit ahead
        assert new_fs.parent.hash == fs.hash

    def test_custom_message(self, repo_fs):
        _, fs = repo_fs
        with fs.batch(message="bulk upload") as b:
            b.write("x.txt", b"x")
            b.write("y.txt", b"y")
        assert b.fs.message == "bulk upload"

    def test_write_and_remove(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            b.write("new.txt", b"new")
            b.remove("a.txt")
        new_fs = b.fs
        assert new_fs.exists("new.txt")
        assert not new_fs.exists("a.txt")

    def test_empty_batch_same_fs(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            pass
        assert b.fs.hash == fs.hash

    def test_exception_no_commit(self, repo_fs):
        _, fs = repo_fs
        try:
            with fs.batch() as b:
                b.write("x.txt", b"x")
                raise RuntimeError("oops")
        except RuntimeError:
            pass
        assert b.fs is None

    def test_batch_on_readonly_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        with pytest.raises(PermissionError):
            tag_fs.batch()

    def test_last_op_wins(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            b.write("f.txt", b"first")
            b.remove("f.txt")
        assert not b.fs.exists("f.txt")

    def test_overwrite_then_remove_existing(self, repo_fs):
        """Overwrite an existing file in batch, then remove it — file must be gone."""
        _, fs = repo_fs
        with fs.batch() as b:
            b.write("a.txt", b"overwritten")
            b.remove("a.txt")
        assert not b.fs.exists("a.txt")

    def test_remove_then_write(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            b.remove("a.txt")
            b.write("a.txt", b"rewritten")
        assert b.fs.read("a.txt") == b"rewritten"

    def test_batch_open(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            with b.open("via_file.txt", "wb") as f:
                f.write(b"file data")
        assert b.fs.read("via_file.txt") == b"file data"

    def test_invalid_batch_open_mode(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            with pytest.raises(ValueError):
                b.open("x.txt", "rb")

    def test_write_after_exit_raises(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            b.write("a.txt", b"data")
        with pytest.raises(RuntimeError):
            b.write("b.txt", b"too late")

    def test_remove_after_exit_raises(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            pass
        with pytest.raises(RuntimeError):
            b.remove("a.txt")

    def test_open_after_exit_raises(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            pass
        with pytest.raises(RuntimeError):
            b.open("x.txt")

    def test_batch_file_close_outside_context(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            f = b.open("via_close.txt", "wb")
            f.write(b"closed data")
            f.close()
        assert b.fs.read("via_close.txt") == b"closed data"

    def test_remove_directory_raises(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("dir/file.txt", b"data")
        with pytest.raises(IsADirectoryError):
            with fs2.batch() as b:
                b.remove("dir")

    def test_write_over_directory_then_remove_raises(self, repo_fs):
        """Write over a base-tree directory, then remove — must still reject."""
        _, fs = repo_fs
        fs2 = fs.write("dir/file.txt", b"data")
        with pytest.raises(IsADirectoryError):
            with fs2.batch() as b:
                b.write("dir", b"replacing directory with file")
                b.remove("dir")

    def test_remove_missing_raises(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(FileNotFoundError):
            with fs.batch() as b:
                b.remove("nonexistent.txt")

    def test_stale_batch_retryable(self, repo_fs):
        repo, fs = repo_fs
        # Advance branch behind fs's back
        fs.write("first.txt", b"first")
        with pytest.raises(StaleSnapshotError):
            with fs.batch() as b:
                b.write("second.txt", b"second")
        # Batch should not be closed — we can refetch and retry
        assert b.fs is None
        assert not b._closed

    def test_write_from_basic(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "hello.txt"
        local.write_bytes(b"hello from disk")
        with fs.batch() as b:
            b.write_from("hello.txt", local)
        assert b.fs.read("hello.txt") == b"hello from disk"

    def test_write_from_preserves_executable(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "run.sh"
        local.write_bytes(b"#!/bin/sh\necho hi")
        local.chmod(local.stat().st_mode | stat.S_IXUSR)
        with fs.batch() as b:
            b.write_from("run.sh", local)
        tree = b.fs._store._repo[b.fs._tree_oid]
        assert tree["run.sh"].filemode == GIT_FILEMODE_BLOB_EXECUTABLE

    def test_write_from_mode_override(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "script.sh"
        local.write_bytes(b"#!/bin/sh")
        # File is NOT executable on disk, but we override
        with fs.batch() as b:
            b.write_from("script.sh", local, mode=GIT_FILEMODE_BLOB_EXECUTABLE)
        tree = b.fs._store._repo[b.fs._tree_oid]
        assert tree["script.sh"].filemode == GIT_FILEMODE_BLOB_EXECUTABLE

    def test_write_from_missing_file(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(FileNotFoundError):
            with fs.batch() as b:
                b.write_from("x.txt", "/nonexistent/path/file.txt")

    def test_write_from_directory_raises(self, repo_fs, tmp_path):
        _, fs = repo_fs
        with pytest.raises(IsADirectoryError):
            with fs.batch() as b:
                b.write_from("x.txt", str(tmp_path))

    def test_batch_mode_parameter(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            b.write("exec.sh", b"#!/bin/sh", mode=GIT_FILEMODE_BLOB_EXECUTABLE)
        tree = b.fs._store._repo[b.fs._tree_oid]
        assert tree["exec.sh"].filemode == GIT_FILEMODE_BLOB_EXECUTABLE

    def test_eager_blob_memory(self, repo_fs):
        _, fs = repo_fs
        with fs.batch() as b:
            b.write("a.txt", b"alpha")
            b.write("b.txt", b"bravo")
            # Values should be OIDs, not raw bytes
            for value in b._writes.values():
                if isinstance(value, tuple):
                    assert isinstance(value[0], pygit2.Oid)
                else:
                    assert isinstance(value, pygit2.Oid)

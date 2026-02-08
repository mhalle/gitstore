"""Tests for batch context manager."""

import pytest

from gitstore import GitStore, StaleSnapshotError


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

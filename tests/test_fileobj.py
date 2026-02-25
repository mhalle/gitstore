"""Tests for file-like objects."""

import pytest

from vost import GitStore


@pytest.fixture
def repo_fs(tmp_path):
    repo = GitStore.open(tmp_path / "test.git")
    fs = repo.branches["main"]
    fs = fs.write("hello.txt", b"Hello World")
    return repo, fs


class TestWritableFile:
    def test_write_context_manager(self, repo_fs):
        _, fs = repo_fs
        with fs.writer("new.txt") as f:
            f.write(b"New content")
        assert f.fs is not None
        assert f.fs.read("new.txt") == b"New content"

    def test_fs_attribute(self, repo_fs):
        _, fs = repo_fs
        with fs.writer("x.txt") as f:
            f.write(b"x")
        new_fs = f.fs
        assert new_fs.exists("x.txt")
        assert new_fs.commit_hash != fs.commit_hash

    def test_exception_no_commit(self, repo_fs):
        _, fs = repo_fs
        try:
            with fs.writer("fail.txt") as f:
                f.write(b"data")
                raise RuntimeError("oops")
        except RuntimeError:
            pass
        assert f.fs is None

    def test_write_on_tag_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        with pytest.raises(PermissionError):
            tag_fs.writer("x.txt")

    def test_invalid_writer_mode(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(ValueError):
            fs.writer("hello.txt", "a")

    def test_close_commits(self, repo_fs):
        _, fs = repo_fs
        f = fs.writer("closed.txt")
        f.write(b"via close")
        f.close()
        assert f.fs is not None
        assert f.fs.read("closed.txt") == b"via close"

    def test_write_after_close_raises(self, repo_fs):
        _, fs = repo_fs
        f = fs.writer("closed.txt")
        f.write(b"data")
        f.close()
        with pytest.raises(ValueError):
            f.write(b"more")

    def test_double_close_is_idempotent(self, repo_fs):
        _, fs = repo_fs
        f = fs.writer("closed.txt")
        f.write(b"data")
        f.close()
        first_hash = f.fs.commit_hash
        f.close()  # should not commit again
        assert f.fs.commit_hash == first_hash

    def test_writable_properties(self, repo_fs):
        _, fs = repo_fs
        f = fs.writer("new.txt")
        assert not f.readable()
        assert f.writable()
        assert not f.seekable()
        assert not f.closed
        f.close()
        assert f.closed

    def test_writer_text_mode(self, repo_fs):
        _, fs = repo_fs
        with fs.writer("x.txt", "w") as f:
            f.write("hello ")
            f.write("world")
        assert f.fs.read("x.txt") == b"hello world"

    def test_writer_text_rejects_bytes(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(TypeError, match="expected str"):
            with fs.writer("x.txt", "w") as f:
                f.write(b"oops")

    def test_writer_binary_rejects_str(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(TypeError, match="expected bytes"):
            with fs.writer("x.txt") as f:
                f.write("oops")

"""Tests for file-like objects."""

import pytest

from gitstore import GitStore


@pytest.fixture
def repo_fs(tmp_path):
    repo = GitStore.open(tmp_path / "test.git", create="main")
    fs = repo.branches["main"]
    fs = fs.write("hello.txt", b"Hello World")
    return repo, fs


class TestReadableFile:
    def test_read_context_manager(self, repo_fs):
        _, fs = repo_fs
        with fs.open("hello.txt", "rb") as f:
            data = f.read()
        assert data == b"Hello World"

    def test_read_partial(self, repo_fs):
        _, fs = repo_fs
        with fs.open("hello.txt", "rb") as f:
            assert f.read(5) == b"Hello"
            assert f.read(6) == b" World"

    def test_seek_tell(self, repo_fs):
        _, fs = repo_fs
        with fs.open("hello.txt", "rb") as f:
            f.seek(6)
            assert f.tell() == 6
            assert f.read() == b"World"

    def test_read_missing_raises(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(FileNotFoundError):
            fs.open("nope.txt", "rb")


class TestWritableFile:
    def test_write_context_manager(self, repo_fs):
        _, fs = repo_fs
        with fs.open("new.txt", "wb") as f:
            f.write(b"New content")
        assert f.fs is not None
        assert f.fs.read("new.txt") == b"New content"

    def test_fs_attribute(self, repo_fs):
        _, fs = repo_fs
        with fs.open("x.txt", "wb") as f:
            f.write(b"x")
        new_fs = f.fs
        assert new_fs.exists("x.txt")
        assert new_fs.hash != fs.hash

    def test_exception_no_commit(self, repo_fs):
        _, fs = repo_fs
        try:
            with fs.open("fail.txt", "wb") as f:
                f.write(b"data")
                raise RuntimeError("oops")
        except RuntimeError:
            pass
        assert f.fs is None

    def test_write_on_tag_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        with pytest.raises(PermissionError):
            tag_fs.open("x.txt", "wb")

    def test_invalid_open_mode(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(ValueError):
            fs.open("hello.txt", "a")

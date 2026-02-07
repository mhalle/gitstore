"""Tests for FS write operations."""

import pytest

from gitstore import GitStore


@pytest.fixture
def repo_fs(tmp_path):
    repo = GitStore.open(tmp_path / "test.git", create="main")
    fs = repo.branches["main"]
    return repo, fs


class TestWrite:
    def test_write_returns_new_fs(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("a.txt", b"a")
        assert fs2.hash != fs.hash

    def test_old_fs_unchanged(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("a.txt", b"a")
        assert not fs.exists("a.txt")
        assert fs2.exists("a.txt")

    def test_written_data_readable(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("data.bin", b"\x00\x01\x02")
        assert fs2.read("data.bin") == b"\x00\x01\x02"

    def test_nested_path_creates_dirs(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("a/b/c.txt", b"deep")
        assert fs2.read("a/b/c.txt") == b"deep"
        assert fs2.exists("a/b")
        assert fs2.exists("a")

    def test_branch_advances(self, repo_fs):
        repo, fs = repo_fs
        fs2 = fs.write("a.txt", b"a")
        # Getting branch again should see latest commit
        latest = repo.branches["main"]
        assert latest.hash == fs2.hash

    def test_write_on_tag_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        with pytest.raises(PermissionError):
            tag_fs.write("x.txt", b"x")


class TestRemove:
    def test_remove(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("a.txt", b"a")
        fs3 = fs2.remove("a.txt")
        assert not fs3.exists("a.txt")

    def test_remove_missing_raises(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(FileNotFoundError):
            fs.remove("nope.txt")

    def test_remove_on_tag_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"].write("x.txt", b"x")
        repo.tags["v1"] = fs
        with pytest.raises(PermissionError):
            repo.tags["v1"].remove("x.txt")

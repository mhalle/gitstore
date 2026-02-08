"""Tests for FS write operations."""

import pytest

from gitstore import GitStore, StaleSnapshotError


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

    def test_write_custom_message(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("a.txt", b"a", message="custom msg")
        assert fs2.message == "custom msg"

    def test_write_with_mode(self, repo_fs):
        from gitstore.tree import GIT_FILEMODE_BLOB_EXECUTABLE
        _, fs = repo_fs
        fs2 = fs.write("run.sh", b"#!/bin/sh", mode=GIT_FILEMODE_BLOB_EXECUTABLE)
        tree = fs2._store._repo[fs2._tree_oid]
        assert tree["run.sh"].filemode == GIT_FILEMODE_BLOB_EXECUTABLE

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

    def test_remove_directory_raises(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("dir/file.txt", b"data")
        with pytest.raises(IsADirectoryError):
            fs2.remove("dir")


class TestLog:
    def test_filemode_only_change_detected(self, repo_fs):
        """log(at=path) should detect filemode-only changes (no content change)."""
        from gitstore.tree import GIT_FILEMODE_BLOB_EXECUTABLE
        _, fs = repo_fs
        # Write a file with default mode (644)
        fs2 = fs.write("script.sh", b"#!/bin/sh\necho hi")
        # Re-write with same content but executable mode (755)
        fs3 = fs2.write(
            "script.sh", b"#!/bin/sh\necho hi",
            mode=GIT_FILEMODE_BLOB_EXECUTABLE, message="Make executable",
        )
        # log --at script.sh should see both commits (content write + mode change)
        entries = list(fs3.log(at="script.sh"))
        messages = [e.message for e in entries]
        assert "Make executable" in messages
        assert "Write script.sh" in messages


class TestStaleSnapshot:
    def test_stale_write_raises(self, repo_fs):
        _, fs = repo_fs
        # Advance the branch behind fs's back
        fs.write("first.txt", b"first")
        with pytest.raises(StaleSnapshotError):
            fs.write("second.txt", b"second")

    def test_stale_remove_raises(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("a.txt", b"a")
        # fs2 is now stale because branch advanced past fs
        fs2.write("b.txt", b"b")
        with pytest.raises(StaleSnapshotError):
            fs2.remove("a.txt")

    def test_stale_batch_raises(self, repo_fs):
        _, fs = repo_fs
        # Advance the branch behind fs's back
        fs.write("first.txt", b"first")
        with pytest.raises(StaleSnapshotError):
            with fs.batch() as b:
                b.write("second.txt", b"second")

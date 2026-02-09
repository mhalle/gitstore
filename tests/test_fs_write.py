"""Tests for FS write operations."""

import stat

import pytest

from gitstore import GitStore, StaleSnapshotError
from gitstore.tree import GIT_FILEMODE_BLOB_EXECUTABLE, GIT_FILEMODE_LINK


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
        entries = list(fs3.log(path="script.sh"))
        messages = [e.message for e in entries]
        assert "Make executable" in messages
        assert "+ script.sh" in messages


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


class TestWriteFrom:
    def test_write_from_basic(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "data.bin"
        local.write_bytes(b"\x00\x01\x02\x03")
        fs2 = fs.write_from("data.bin", local)
        assert fs2.read("data.bin") == b"\x00\x01\x02\x03"

    def test_write_from_preserves_executable(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "run.sh"
        local.write_bytes(b"#!/bin/sh\necho hi")
        local.chmod(local.stat().st_mode | stat.S_IXUSR)
        fs2 = fs.write_from("run.sh", local)
        tree = fs2._store._repo[fs2._tree_oid]
        assert tree["run.sh"].filemode == GIT_FILEMODE_BLOB_EXECUTABLE

    def test_write_from_mode_override(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "script.sh"
        local.write_bytes(b"#!/bin/sh")
        # File is NOT executable on disk, but we override
        fs2 = fs.write_from("script.sh", local, mode=GIT_FILEMODE_BLOB_EXECUTABLE)
        tree = fs2._store._repo[fs2._tree_oid]
        assert tree["script.sh"].filemode == GIT_FILEMODE_BLOB_EXECUTABLE

    def test_write_from_custom_message(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "file.txt"
        local.write_bytes(b"content")
        fs2 = fs.write_from("file.txt", local, message="Import file")
        assert fs2.message == "Import file"

    def test_write_from_on_tag_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        local = tmp_path / "file.txt"
        local.write_bytes(b"data")
        with pytest.raises(PermissionError):
            tag_fs.write_from("file.txt", local)

    def test_write_from_missing_file(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(FileNotFoundError):
            fs.write_from("x.txt", "/nonexistent/path/file.txt")

    def test_write_from_directory_raises(self, repo_fs, tmp_path):
        _, fs = repo_fs
        with pytest.raises(IsADirectoryError):
            fs.write_from("x.txt", str(tmp_path))


class TestSymlink:
    def test_write_symlink_basic(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write_symlink("link.txt", "target.txt")
        assert fs2.readlink("link.txt") == "target.txt"

    def test_write_symlink_filemode(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write_symlink("link.txt", "target.txt")
        tree = fs2._store._repo[fs2._tree_oid]
        assert tree["link.txt"].filemode == GIT_FILEMODE_LINK

    def test_write_symlink_nested_target(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write_symlink("shortcut", "a/b/c.txt")
        assert fs2.readlink("shortcut") == "a/b/c.txt"

    def test_write_symlink_custom_message(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write_symlink("link.txt", "target.txt", message="add link")
        assert fs2.message == "add link"

    def test_write_symlink_default_message(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write_symlink("link.txt", "target.txt")
        assert fs2.message == "+ link.txt (L)"

    def test_write_symlink_on_tag_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        with pytest.raises(PermissionError):
            tag_fs.write_symlink("link.txt", "target.txt")

    def test_readlink_missing_raises(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(FileNotFoundError):
            fs.readlink("nonexistent")

    def test_readlink_on_regular_file_raises(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write("regular.txt", b"data")
        with pytest.raises(ValueError):
            fs2.readlink("regular.txt")

    def test_read_returns_symlink_target_bytes(self, repo_fs):
        """read() on a symlink returns the raw target as bytes."""
        _, fs = repo_fs
        fs2 = fs.write_symlink("link.txt", "target.txt")
        assert fs2.read("link.txt") == b"target.txt"

    def test_remove_symlink(self, repo_fs):
        _, fs = repo_fs
        fs2 = fs.write_symlink("link.txt", "target.txt")
        fs3 = fs2.remove("link.txt")
        assert not fs3.exists("link.txt")


class TestNoOpCommit:
    def test_write_identical_content_no_new_commit(self, repo_fs):
        """Writing the same data to the same path should not create a new commit."""
        _, fs = repo_fs
        fs2 = fs.write("a.txt", b"hello")
        fs3 = fs2.write("a.txt", b"hello")
        assert fs3.hash == fs2.hash

    def test_write_identical_via_batch_no_new_commit(self, repo_fs):
        """Batch-writing identical content should not create a new commit."""
        _, fs = repo_fs
        fs2 = fs.write("a.txt", b"hello")
        with fs2.batch() as b:
            b.write("a.txt", b"hello")
        assert b.fs.hash == fs2.hash

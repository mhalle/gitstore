"""Tests for WriteEntry and FS.apply()."""

import os
import stat
from pathlib import Path

import pytest

from gitstore import GitStore, FileType, StaleSnapshotError, WriteEntry


@pytest.fixture
def repo_fs(tmp_path):
    repo = GitStore.open(tmp_path / "test.git")
    fs = repo.branches["main"]
    fs = fs.write("a.txt", b"aaa")
    return repo, fs


# --- WriteEntry construction ---


class TestWriteEntry:
    def test_bytes_data(self):
        e = WriteEntry(data=b"data")
        assert e.data == b"data"
        assert e.mode is None
        assert e.target is None

    def test_str_data(self):
        e = WriteEntry(data="hello")
        assert e.data == "hello"

    def test_path_data(self):
        e = WriteEntry(data=Path("/tmp/f"))
        assert e.data == Path("/tmp/f")

    def test_target(self):
        e = WriteEntry(target="target")
        assert e.target == "target"
        assert e.data is None

    def test_mode(self):
        e = WriteEntry(data=b"x", mode=FileType.EXECUTABLE)
        assert e.mode == FileType.EXECUTABLE

    def test_both_data_and_target_raises(self):
        with pytest.raises(ValueError, match="both data and target"):
            WriteEntry(data=b"x", target="t")

    def test_neither_data_nor_target_raises(self):
        with pytest.raises(ValueError, match="Must specify either"):
            WriteEntry()

    def test_target_with_mode_raises(self):
        with pytest.raises(ValueError, match="Cannot specify mode for symlinks"):
            WriteEntry(target="t", mode=FileType.EXECUTABLE)

    def test_frozen(self):
        e = WriteEntry(data=b"x")
        with pytest.raises(AttributeError):
            e.data = b"y"


# --- apply() with each source type ---


class TestApplyWrites:
    def test_bytes(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"data.bin": WriteEntry(data=b"\x00\x01")})
        assert new.read("data.bin") == b"\x00\x01"

    def test_str_utf8(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"hello.txt": WriteEntry(data="caf\u00e9")})
        assert new.read("hello.txt") == "caf\u00e9".encode("utf-8")

    def test_path_from_disk(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "local.txt"
        local.write_bytes(b"from disk")
        new = fs.apply(writes={"disk.txt": WriteEntry(data=local)})
        assert new.read("disk.txt") == b"from disk"

    def test_symlink(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"link": WriteEntry(target="target")})
        assert new.readlink("link") == "target"

    def test_executable_mode(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={
            "run.sh": WriteEntry(data=b"#!/bin/sh", mode=FileType.EXECUTABLE),
        })
        assert new.read("run.sh") == b"#!/bin/sh"
        assert new.file_type("run.sh") == FileType.EXECUTABLE

    def test_path_auto_detects_executable(self, repo_fs, tmp_path):
        _, fs = repo_fs
        script = tmp_path / "script.sh"
        script.write_bytes(b"#!/bin/sh")
        script.chmod(0o755)
        new = fs.apply(writes={"s.sh": WriteEntry(data=script)})
        assert new.file_type("s.sh") == FileType.EXECUTABLE

    def test_path_mode_override(self, repo_fs, tmp_path):
        _, fs = repo_fs
        # File is not executable on disk, but we force EXECUTABLE mode
        f = tmp_path / "plain.txt"
        f.write_bytes(b"data")
        new = fs.apply(writes={
            "forced.sh": WriteEntry(data=f, mode=FileType.EXECUTABLE),
        })
        assert new.file_type("forced.sh") == FileType.EXECUTABLE

    def test_multiple_writes_single_commit(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={
            "x.txt": WriteEntry(data=b"x"),
            "y.txt": WriteEntry(data=b"y"),
        })
        assert new.read("x.txt") == b"x"
        assert new.read("y.txt") == b"y"
        assert new.parent.commit_hash == fs.commit_hash


# --- Bare shorthand values ---


class TestApplyBareShorthand:
    def test_bare_bytes(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"f.bin": b"\xff"})
        assert new.read("f.bin") == b"\xff"

    def test_bare_str(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"f.txt": "hello"})
        assert new.read("f.txt") == b"hello"

    def test_bare_path(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "src.txt"
        local.write_bytes(b"path data")
        new = fs.apply(writes={"dst.txt": local})
        assert new.read("dst.txt") == b"path data"

    def test_mixed(self, repo_fs, tmp_path):
        _, fs = repo_fs
        local = tmp_path / "f.txt"
        local.write_bytes(b"file")
        new = fs.apply(writes={
            "a": b"bytes",
            "b": "string",
            "c": local,
            "d": WriteEntry(target="target"),
        })
        assert new.read("a") == b"bytes"
        assert new.read("b") == b"string"
        assert new.read("c") == b"file"
        assert new.readlink("d") == "target"


# --- Removes ---


class TestApplyRemoves:
    def test_single_str(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(removes="a.txt")
        assert not new.exists("a.txt")

    def test_list(self, repo_fs):
        _, fs = repo_fs
        fs = fs.write("b.txt", b"b")
        new = fs.apply(removes=["a.txt", "b.txt"])
        assert not new.exists("a.txt")
        assert not new.exists("b.txt")

    def test_set(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(removes={"a.txt"})
        assert not new.exists("a.txt")

    def test_none_is_no_op(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"x.txt": b"x"}, removes=None)
        assert new.exists("a.txt")  # not removed
        assert new.exists("x.txt")


# --- Combined writes + removes ---


class TestApplyCombined:
    def test_write_and_remove(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(
            writes={"new.txt": b"new content"},
            removes=["a.txt"],
        )
        assert new.exists("new.txt")
        assert not new.exists("a.txt")
        # Single commit
        assert new.parent.commit_hash == fs.commit_hash

    def test_empty_no_op(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply()
        assert new.commit_hash == fs.commit_hash


# --- Commit options ---


class TestApplyCommitOptions:
    def test_custom_message(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"x.txt": b"x"}, message="custom msg")
        assert new.message == "custom msg"

    def test_operation(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(
            writes={"x.txt": b"x", "y.txt": b"y"},
            operation="import",
        )
        assert "import" in new.message

    def test_auto_message(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"x.txt": b"x"})
        # Auto-generated message should mention the path
        assert "x.txt" in new.message


# --- Errors ---


class TestApplyErrors:
    def test_readonly_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        with pytest.raises(PermissionError):
            tag_fs.apply(writes={"x": b"x"})

    def test_stale_raises(self, repo_fs):
        repo, fs = repo_fs
        # Advance branch behind fs's back
        fs2 = repo.branches["main"]
        fs2.write("z.txt", b"z")
        with pytest.raises(StaleSnapshotError):
            fs.apply(writes={"x": b"x"})

    def test_invalid_type_raises(self, repo_fs):
        _, fs = repo_fs
        with pytest.raises(TypeError, match="Expected WriteEntry"):
            fs.apply(writes={"x": 42})

    def test_missing_path_raises(self, repo_fs, tmp_path):
        _, fs = repo_fs
        missing = tmp_path / "nonexistent.txt"
        with pytest.raises(FileNotFoundError):
            fs.apply(writes={"x": WriteEntry(data=missing)})

    def test_directory_path_raises(self, repo_fs, tmp_path):
        _, fs = repo_fs
        d = tmp_path / "subdir"
        d.mkdir()
        with pytest.raises((IsADirectoryError, PermissionError)):
            fs.apply(writes={"x": WriteEntry(data=d)})


# --- Changes report ---


class TestApplyChangesReport:
    def test_add(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"new.txt": b"new"})
        assert new.changes is not None
        assert len(new.changes.add) == 1
        assert new.changes.add[0].path == "new.txt"

    def test_update(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(writes={"a.txt": b"updated"})
        assert new.changes is not None
        assert len(new.changes.update) == 1
        assert new.changes.update[0].path == "a.txt"

    def test_delete(self, repo_fs):
        _, fs = repo_fs
        new = fs.apply(removes=["a.txt"])
        assert new.changes is not None
        assert len(new.changes.delete) == 1
        assert new.changes.delete[0].path == "a.txt"

    def test_identical_write_no_commit(self, repo_fs):
        _, fs = repo_fs
        # Write same data — should return same FS (no new commit)
        new = fs.apply(writes={"a.txt": b"aaa"})
        assert new.commit_hash == fs.commit_hash

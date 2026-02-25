"""Tests for FUSE-readiness APIs: stat, listdir, tree_hash, read range, read_by_hash, close."""

import pytest

from vost import FileType, GitStore, StatResult


@pytest.fixture
def repo_with_types(tmp_path):
    """Repo with a blob, executable, symlink, and nested dir."""
    repo = GitStore.open(tmp_path / "test.git")
    fs = repo.branches["main"]
    fs = fs.write("hello.txt", b"Hello!")
    fs = fs.write("run.sh", b"#!/bin/sh\n", mode=FileType.EXECUTABLE)
    fs = fs.write_symlink("link.txt", "hello.txt")
    fs = fs.write("src/main.py", b"print('hi')")
    fs = fs.write("src/lib/util.py", b"# util")
    return repo, fs


# ── stat() ──────────────────────────────────────────────────────────────


class TestStat:
    def test_stat_file(self, repo_with_types):
        _, fs = repo_with_types
        st = fs.stat("hello.txt")
        assert isinstance(st, StatResult)
        assert st.mode == 0o100644
        assert st.file_type == FileType.BLOB
        assert st.size == len(b"Hello!")
        assert st.nlink == 1
        assert len(st.hash) == 40
        assert st.mtime > 0

    def test_stat_executable(self, repo_with_types):
        _, fs = repo_with_types
        st = fs.stat("run.sh")
        assert st.mode == 0o100755
        assert st.file_type == FileType.EXECUTABLE
        assert st.size == len(b"#!/bin/sh\n")
        assert st.nlink == 1

    def test_stat_symlink(self, repo_with_types):
        _, fs = repo_with_types
        st = fs.stat("link.txt")
        assert st.mode == 0o120000
        assert st.file_type == FileType.LINK
        # Symlink size = length of target string
        assert st.size == len("hello.txt")
        assert st.nlink == 1

    def test_stat_directory(self, repo_with_types):
        _, fs = repo_with_types
        st = fs.stat("src")
        assert st.mode == 0o040000
        assert st.file_type == FileType.TREE
        assert st.size == 0
        # src/ has 1 subdir (lib), so nlink = 2 + 1 = 3
        assert st.nlink == 3

    def test_stat_root(self, repo_with_types):
        _, fs = repo_with_types
        st = fs.stat()
        assert st.mode == 0o040000
        assert st.file_type == FileType.TREE
        assert st.size == 0
        # Root has 1 subdir (src), so nlink = 2 + 1 = 3
        assert st.nlink == 3
        assert len(st.hash) == 40

    def test_stat_root_explicit_none(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.stat(None) == fs.stat()

    def test_stat_nonexistent(self, repo_with_types):
        _, fs = repo_with_types
        with pytest.raises(FileNotFoundError):
            fs.stat("nope.txt")

    def test_stat_size_matches_size_method(self, repo_with_types):
        _, fs = repo_with_types
        for path in ("hello.txt", "run.sh", "src/main.py", "src/lib/util.py"):
            assert fs.stat(path).size == fs.size(path)

    def test_stat_hash_matches_object_hash(self, repo_with_types):
        _, fs = repo_with_types
        for path in ("hello.txt", "src", "src/main.py"):
            assert fs.stat(path).hash == fs.object_hash(path)

    def test_stat_nlink_leaf_dir(self, repo_with_types):
        _, fs = repo_with_types
        # src/lib has no subdirs, so nlink = 2
        st = fs.stat("src/lib")
        assert st.nlink == 2

    def test_stat_mtime_consistent(self, repo_with_types):
        _, fs = repo_with_types
        # All paths should share the same commit mtime
        assert fs.stat("hello.txt").mtime == fs.stat("src").mtime == fs.stat().mtime


# ── listdir() ───────────────────────────────────────────────────────────


class TestListdir:
    def test_listdir_root(self, repo_with_types):
        _, fs = repo_with_types
        entries = fs.listdir()
        names = sorted(e.name for e in entries)
        assert names == sorted(fs.ls())

    def test_listdir_subdir(self, repo_with_types):
        _, fs = repo_with_types
        entries = fs.listdir("src")
        names = sorted(e.name for e in entries)
        assert names == sorted(fs.ls("src"))

    def test_listdir_returns_walk_entries(self, repo_with_types):
        _, fs = repo_with_types
        from vost import WalkEntry
        entries = fs.listdir()
        assert all(isinstance(e, WalkEntry) for e in entries)

    def test_listdir_entry_types(self, repo_with_types):
        _, fs = repo_with_types
        entries = {e.name: e for e in fs.listdir()}
        assert entries["hello.txt"].file_type == FileType.BLOB
        assert entries["run.sh"].file_type == FileType.EXECUTABLE
        assert entries["link.txt"].file_type == FileType.LINK
        assert entries["src"].file_type == FileType.TREE

    def test_listdir_on_file_raises(self, repo_with_types):
        _, fs = repo_with_types
        with pytest.raises(NotADirectoryError):
            fs.listdir("hello.txt")


# ── tree_hash ───────────────────────────────────────────────────────────


class TestTreeHash:
    def test_tree_hash_is_hex(self, repo_with_types):
        _, fs = repo_with_types
        h = fs.tree_hash
        assert isinstance(h, str)
        assert len(h) == 40
        int(h, 16)

    def test_tree_hash_stable(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.tree_hash == fs.tree_hash

    def test_tree_hash_changes_on_write(self, repo_with_types):
        _, fs = repo_with_types
        old = fs.tree_hash
        fs2 = fs.write("new.txt", b"data")
        assert fs2.tree_hash != old


# ── read() with offset/size ─────────────────────────────────────────────


class TestReadRange:
    def test_read_no_range_unchanged(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt") == b"Hello!"

    def test_read_offset_and_size(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", offset=0, size=3) == b"Hel"

    def test_read_offset_middle(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", offset=2, size=2) == b"ll"

    def test_read_offset_end(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", offset=4, size=2) == b"o!"

    def test_read_size_beyond_end(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", offset=4, size=100) == b"o!"

    def test_read_size_zero(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", offset=0, size=0) == b""

    def test_read_offset_at_end(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", offset=6, size=10) == b""

    def test_read_offset_only(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", offset=3) == b"lo!"

    def test_read_size_only(self, repo_with_types):
        _, fs = repo_with_types
        assert fs.read("hello.txt", size=3) == b"Hel"

    def test_read_range_nonexistent(self, repo_with_types):
        _, fs = repo_with_types
        with pytest.raises(FileNotFoundError):
            fs.read("nope.txt", offset=0, size=10)

    def test_read_range_directory(self, repo_with_types):
        _, fs = repo_with_types
        with pytest.raises(IsADirectoryError):
            fs.read("src", offset=0, size=10)


# ── read_by_hash() ──────────────────────────────────────────────────────


class TestReadByHash:
    def test_roundtrip_with_object_hash(self, repo_with_types):
        _, fs = repo_with_types
        h = fs.object_hash("hello.txt")
        assert fs.read_by_hash(h) == b"Hello!"

    def test_accepts_bytes_hash(self, repo_with_types):
        _, fs = repo_with_types
        h = fs.object_hash("hello.txt").encode()
        assert fs.read_by_hash(h) == b"Hello!"

    def test_accepts_str_hash(self, repo_with_types):
        _, fs = repo_with_types
        h = fs.object_hash("hello.txt")
        assert isinstance(h, str)
        assert fs.read_by_hash(h) == b"Hello!"

    def test_matches_read(self, repo_with_types):
        _, fs = repo_with_types
        for path in ("hello.txt", "run.sh", "src/main.py"):
            h = fs.object_hash(path)
            assert fs.read_by_hash(h) == fs.read(path)

    def test_range_offset_and_size(self, repo_with_types):
        _, fs = repo_with_types
        h = fs.object_hash("hello.txt")
        assert fs.read_by_hash(h, offset=2, size=2) == b"ll"

    def test_range_offset_only(self, repo_with_types):
        _, fs = repo_with_types
        h = fs.object_hash("hello.txt")
        assert fs.read_by_hash(h, offset=3) == b"lo!"

    def test_range_size_only(self, repo_with_types):
        _, fs = repo_with_types
        h = fs.object_hash("hello.txt")
        assert fs.read_by_hash(h, size=3) == b"Hel"


# ── close() ─────────────────────────────────────────────────────────────


class TestClose:
    def test_close_idempotent(self, repo_with_types):
        _, fs = repo_with_types
        # Trigger sizer creation
        fs.size("hello.txt")
        fs.close()
        fs.close()  # second close should not raise

    def test_close_then_reuse(self, repo_with_types):
        _, fs = repo_with_types
        fs.size("hello.txt")
        fs.close()
        # Sizer should be re-created on next use
        assert fs.size("hello.txt") == len(b"Hello!")

    def test_close_without_sizer(self, repo_with_types):
        _, fs = repo_with_types
        # Never accessed sizer — close should be safe
        fs.close()


# ── Cached sizer ────────────────────────────────────────────────────────


class TestCachedSizer:
    def test_size_many_files(self, tmp_path):
        """size() works across many calls without resource leak."""
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        for i in range(50):
            fs = fs.write(f"file{i}.txt", f"content {i}".encode())
        for i in range(50):
            assert fs.size(f"file{i}.txt") == len(f"content {i}".encode())
        fs.close()

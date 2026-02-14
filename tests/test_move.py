"""API-level tests for FS.move() — portable to TypeScript."""

import pytest
from gitstore import GitStore


@pytest.fixture
def store_with_files(tmp_path):
    """Repo with hello.txt, dir/a.txt, dir/b.txt, other/c.txt on 'main'."""
    store = GitStore.open(tmp_path / "test.git", branch="main")
    fs = store.branches["main"]
    with fs.batch(message="seed") as b:
        b.write("hello.txt", b"hello world")
        b.write("dir/a.txt", b"aaa")
        b.write("dir/b.txt", b"bbb")
        b.write("other/c.txt", b"ccc")
    return store


class TestMoveRename:
    def test_rename_file(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("hello.txt", "renamed.txt")
        assert fs2.read("renamed.txt") == b"hello world"
        assert not fs2.exists("hello.txt")

    def test_rename_preserves_other_files(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("hello.txt", "renamed.txt")
        assert fs2.read("dir/a.txt") == b"aaa"

    def test_move_into_directory(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("hello.txt", "dir/")
        assert fs2.read("dir/hello.txt") == b"hello world"
        assert not fs2.exists("hello.txt")

    def test_move_multiple_into_directory(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move(["hello.txt", "other/c.txt"], "dir/")
        assert fs2.exists("dir/hello.txt")
        assert fs2.exists("dir/c.txt")
        assert not fs2.exists("hello.txt")
        assert not fs2.exists("other/c.txt")

    def test_rename_directory(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("dir", "newdir", recursive=True)
        assert fs2.read("newdir/a.txt") == b"aaa"
        assert fs2.read("newdir/b.txt") == b"bbb"
        assert not fs2.exists("dir/a.txt")


class TestMoveAtomicity:
    def test_single_commit(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("hello.txt", "moved.txt")
        # New state: moved.txt exists, hello.txt gone
        assert fs2.exists("moved.txt")
        assert not fs2.exists("hello.txt")
        # Previous commit: hello.txt exists, moved.txt doesn't
        prev = fs2.back(1)
        assert prev.exists("hello.txt")
        assert not prev.exists("moved.txt")


class TestMoveDryRun:
    def test_dry_run_no_changes(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("hello.txt", "renamed.txt", dry_run=True)
        # Original still exists
        assert fs2.exists("hello.txt")
        assert not fs2.exists("renamed.txt")
        # But changes are reported
        assert fs2.changes is not None
        assert len(fs2.changes.add) == 1
        assert len(fs2.changes.delete) == 1

    def test_dry_run_reports_correct_paths(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("hello.txt", "renamed.txt", dry_run=True)
        add_paths = [e.path for e in fs2.changes.add]
        del_paths = [e.path for e in fs2.changes.delete]
        assert "renamed.txt" in add_paths
        assert "hello.txt" in del_paths


class TestMoveErrors:
    def test_same_source_and_dest(self, store_with_files):
        fs = store_with_files.branches["main"]
        with pytest.raises(ValueError, match="same"):
            fs.move("hello.txt", "hello.txt")

    def test_nonexistent_source(self, store_with_files):
        fs = store_with_files.branches["main"]
        with pytest.raises(FileNotFoundError):
            fs.move("missing.txt", "dest.txt")

    def test_directory_without_recursive(self, store_with_files):
        fs = store_with_files.branches["main"]
        with pytest.raises(IsADirectoryError):
            fs.move("dir", "newdir")

    def test_write_to_tag_raises(self, store_with_files):
        store_with_files.tags["v1"] = store_with_files.branches["main"]
        fs = store_with_files.tags["v1"]
        with pytest.raises(PermissionError):
            fs.move("hello.txt", "renamed.txt")


class TestMoveMessage:
    def test_custom_message(self, store_with_files):
        fs = store_with_files.branches["main"]
        fs2 = fs.move("hello.txt", "renamed.txt", message="renamed hello")
        # Verify commit message by checking log
        for entry in fs2.log():
            if entry.message.startswith("renamed hello"):
                break
        else:
            pytest.fail("Custom message not found in log")

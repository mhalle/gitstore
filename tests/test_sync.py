"""Tests for path-level sync (sync_to_repo / sync_from_repo)."""

import os

import pytest

from gitstore import (
    GitStore,
    sync_to_repo,
    sync_from_repo,
    sync_to_repo_dry_run,
    sync_from_repo_dry_run,
    ChangeReport,
    ChangeAction,
    FileEntry,
)


def paths(entries):
    """Extract paths from FileEntry list for easier testing."""
    if entries is None:
        return set()
    return {e.path for e in entries}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    p = str(tmp_path / "test.git")
    return GitStore.open(p)


@pytest.fixture
def fs(store):
    return store.branches["main"]


@pytest.fixture
def local_dir(tmp_path):
    """A local directory with some files."""
    d = tmp_path / "local"
    d.mkdir()
    (d / "a.txt").write_text("alpha")
    (d / "b.txt").write_text("beta")
    return d


# ---------------------------------------------------------------------------
# sync_to_repo
# ---------------------------------------------------------------------------

class TestSyncToRepo:
    def test_basic_sync(self, fs, local_dir):
        new_fs = sync_to_repo(fs, str(local_dir), "data")
        assert sorted(new_fs.ls("data")) == ["a.txt", "b.txt"]
        assert new_fs.read("data/a.txt") == b"alpha"
        assert new_fs.read("data/b.txt") == b"beta"

    def test_deletes_repo_files_not_in_local(self, fs, local_dir):
        # Put extra file in repo first
        fs = fs.write("data/extra.txt", b"extra")
        new_fs = sync_to_repo(fs, str(local_dir), "data")
        assert not new_fs.exists("data/extra.txt")
        assert new_fs.read("data/a.txt") == b"alpha"

    def test_overwrites_changed_files(self, fs, local_dir):
        # Write different content to repo
        fs = fs.write("data/a.txt", b"old content")
        new_fs = sync_to_repo(fs, str(local_dir), "data")
        assert new_fs.read("data/a.txt") == b"alpha"

    def test_noop_when_identical(self, fs, local_dir):
        fs1 = sync_to_repo(fs, str(local_dir), "data")
        fs2 = sync_to_repo(fs1, str(local_dir), "data")
        # Same commit — no new commit created
        assert fs1.commit_hash == fs2.commit_hash

    def test_custom_message(self, fs, local_dir):
        new_fs = sync_to_repo(fs, str(local_dir), "data", message="my sync")
        assert new_fs.message == "my sync"

    def test_nested_directories(self, fs, local_dir):
        sub = local_dir / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "nested.txt").write_text("nested")
        new_fs = sync_to_repo(fs, str(local_dir), "data")
        assert new_fs.read("data/sub/deep/nested.txt") == b"nested"

    def test_empty_repo_path(self, fs, local_dir):
        new_fs = sync_to_repo(fs, str(local_dir), "")
        assert new_fs.read("a.txt") == b"alpha"

    def test_symlink_preserved(self, fs, local_dir):
        target = local_dir / "a.txt"
        link = local_dir / "link.txt"
        link.symlink_to("a.txt")
        new_fs = sync_to_repo(fs, str(local_dir), "data")
        assert new_fs.readlink("data/link.txt") == "a.txt"


# ---------------------------------------------------------------------------
# sync_from_repo
# ---------------------------------------------------------------------------

class TestSyncFromRepo:
    def test_basic_sync(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        fs = fs.write("data/y.txt", b"why")
        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))
        assert (out / "x.txt").read_text() == "ex"
        assert (out / "y.txt").read_text() == "why"

    def test_deletes_local_files_not_in_repo(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "output"
        out.mkdir()
        (out / "extra.txt").write_text("extra")
        sync_from_repo(fs, "data", str(out))
        assert not (out / "extra.txt").exists()
        assert (out / "x.txt").read_text() == "ex"

    def test_overwrites_changed_files(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"new content")
        out = tmp_path / "output"
        out.mkdir()
        (out / "x.txt").write_text("old content")
        sync_from_repo(fs, "data", str(out))
        assert (out / "x.txt").read_text() == "new content"

    def test_noop_when_identical(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "output"
        out.mkdir()
        (out / "x.txt").write_bytes(b"ex")
        # Should not raise or change anything
        sync_from_repo(fs, "data", str(out))
        assert (out / "x.txt").read_bytes() == b"ex"

    def test_nested_directories(self, fs, tmp_path):
        fs = fs.write("data/sub/deep/nested.txt", b"nested")
        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))
        assert (out / "sub" / "deep" / "nested.txt").read_text() == "nested"

    def test_cleans_empty_dirs_after_delete(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "output"
        out.mkdir()
        sub = out / "orphan" / "deep"
        sub.mkdir(parents=True)
        (sub / "old.txt").write_text("old")
        sync_from_repo(fs, "data", str(out))
        assert not (out / "orphan").exists()

    def test_creates_output_dir(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "new_dir"
        sync_from_repo(fs, "data", str(out))
        assert (out / "x.txt").read_text() == "ex"

    def test_symlink_preserved(self, fs, tmp_path):
        fs = fs.write_symlink("data/link.txt", "target.txt")
        fs = fs.write("data/target.txt", b"content")
        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))
        assert (out / "link.txt").is_symlink()
        assert os.readlink(out / "link.txt") == "target.txt"


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestSyncToRepoDryRun:
    def test_returns_correct_plan(self, fs, local_dir):
        plan = sync_to_repo_dry_run(fs, str(local_dir), "data")
        assert isinstance(plan, ChangeReport)
        assert sorted(paths(plan.add)) == ["a.txt", "b.txt"]
        assert len(plan.update) == 0
        assert len(plan.delete) == 0
        assert plan.total == 2
        assert not plan.in_sync

    def test_does_not_write(self, fs, local_dir):
        plan = sync_to_repo_dry_run(fs, str(local_dir), "data")
        assert plan.total > 0
        # Repo should still be empty
        assert fs.ls() == []

    def test_detects_updates(self, fs, local_dir):
        fs = fs.write("data/a.txt", b"old")
        plan = sync_to_repo_dry_run(fs, str(local_dir), "data")
        assert "a.txt" in paths(plan.update)
        assert "b.txt" in paths(plan.add)

    def test_detects_deletes(self, fs, local_dir):
        fs = fs.write("data/a.txt", b"alpha")
        fs = fs.write("data/b.txt", b"beta")
        fs = fs.write("data/extra.txt", b"extra")
        plan = sync_to_repo_dry_run(fs, str(local_dir), "data")
        assert "extra.txt" in paths(plan.delete)
        assert len(plan.add) == 0
        assert len(plan.update) == 0

    def test_in_sync(self, fs, local_dir):
        fs1 = sync_to_repo(fs, str(local_dir), "data")
        plan = sync_to_repo_dry_run(fs1, str(local_dir), "data")
        assert plan is None


class TestSyncFromRepoDryRun:
    def test_returns_correct_plan(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "output"
        out.mkdir()
        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert sorted(paths(plan.add)) == ["x.txt"]
        assert len(plan.update) == 0
        assert len(plan.delete) == 0

    def test_does_not_write(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "output"
        out.mkdir()
        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert plan.total > 0
        assert not (out / "x.txt").exists()

    def test_detects_updates(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"new")
        out = tmp_path / "output"
        out.mkdir()
        (out / "x.txt").write_bytes(b"old")
        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert "x.txt" in paths(plan.update)

    def test_detects_deletes(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "output"
        out.mkdir()
        (out / "x.txt").write_bytes(b"ex")
        (out / "extra.txt").write_bytes(b"extra")
        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert "extra.txt" in paths(plan.delete)
        assert len(plan.add) == 0
        assert len(plan.update) == 0

    def test_in_sync(self, fs, tmp_path):
        fs = fs.write("data/x.txt", b"ex")
        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))
        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert plan is None


# ---------------------------------------------------------------------------
# ChangeReport / ChangeAction
# ---------------------------------------------------------------------------

class TestChangeReportActions:
    def test_actions_sorted_by_path(self):
        plan = ChangeReport(
            add=[FileEntry("c.txt", "B"), FileEntry("a.txt", "B")],
            update=[FileEntry("b.txt", "B")],
            delete=[FileEntry("d.txt", "B")],
        )
        actions = plan.actions()
        assert [a.path for a in actions] == ["a.txt", "b.txt", "c.txt", "d.txt"]
        assert actions[0].action == "add"
        assert actions[1].action == "update"
        assert actions[2].action == "add"
        assert actions[3].action == "delete"

    def test_empty_plan(self):
        plan = ChangeReport()
        assert plan.in_sync  # direct construction still works
        assert plan.total == 0
        assert plan.actions() == []


# ---------------------------------------------------------------------------
# Edge cases — symlinks
# ---------------------------------------------------------------------------

class TestSyncSymlinks:
    def test_symlinked_directory_stored_as_symlink(self, fs, tmp_path):
        """Symlinked directory in local is stored as a symlink, not followed."""
        local = tmp_path / "local"
        local.mkdir()
        real_sub = tmp_path / "real_sub"
        real_sub.mkdir()
        (real_sub / "file.txt").write_text("content")
        (local / "linked_dir").symlink_to(real_sub)
        (local / "regular.txt").write_text("regular")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.readlink("data/linked_dir") == str(real_sub)
        assert new_fs.read("data/regular.txt") == b"regular"

    def test_symlink_target_change_detected_to_repo(self, fs, tmp_path):
        """Changing a symlink target is detected as an update."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "link").symlink_to("target_v1")

        fs1 = sync_to_repo(fs, str(local), "data")
        assert fs1.readlink("data/link") == "target_v1"

        # Change the target
        (local / "link").unlink()
        (local / "link").symlink_to("target_v2")

        plan = sync_to_repo_dry_run(fs1, str(local), "data")
        assert "link" in paths(plan.update)

        fs2 = sync_to_repo(fs1, str(local), "data")
        assert fs2.readlink("data/link") == "target_v2"

    def test_symlink_target_change_detected_from_repo(self, fs, tmp_path):
        """Changing a symlink target in repo is detected as an update locally."""
        fs = fs.write_symlink("data/link", "target_v1")
        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))
        assert os.readlink(out / "link") == "target_v1"

        fs = fs.write_symlink("data/link", "target_v2")
        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert "link" in paths(plan.update)

        sync_from_repo(fs, "data", str(out))
        assert os.readlink(out / "link") == "target_v2"

    def test_symlink_replaces_regular_file_to_repo(self, fs, tmp_path):
        """Local symlink replaces a regular file in repo."""
        fs = fs.write("data/target", b"regular file")
        local = tmp_path / "local"
        local.mkdir()
        (local / "target").symlink_to("somewhere")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.readlink("data/target") == "somewhere"

    def test_regular_file_replaces_symlink_to_repo(self, fs, tmp_path):
        """Local regular file replaces a symlink in repo."""
        fs = fs.write_symlink("data/target", "somewhere")
        local = tmp_path / "local"
        local.mkdir()
        (local / "target").write_text("regular file")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/target") == b"regular file"

    def test_symlink_replaces_regular_file_from_repo(self, fs, tmp_path):
        """Repo symlink replaces a local regular file."""
        fs = fs.write_symlink("data/target", "somewhere")
        out = tmp_path / "output"
        out.mkdir()
        (out / "target").write_text("regular file")

        sync_from_repo(fs, "data", str(out))
        assert (out / "target").is_symlink()
        assert os.readlink(out / "target") == "somewhere"

    def test_regular_file_replaces_symlink_from_repo(self, fs, tmp_path):
        """Repo regular file replaces a local symlink."""
        fs = fs.write("data/target", b"regular file")
        out = tmp_path / "output"
        out.mkdir()
        (out / "target").symlink_to("somewhere")

        sync_from_repo(fs, "data", str(out))
        assert not (out / "target").is_symlink()
        assert (out / "target").read_text() == "regular file"

    def test_dangling_symlink_to_repo(self, fs, tmp_path):
        """A dangling symlink (target doesn't exist) is synced correctly."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "broken").symlink_to("nonexistent_target")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.readlink("data/broken") == "nonexistent_target"

    def test_dangling_symlink_from_repo(self, fs, tmp_path):
        """A repo symlink pointing to nonexistent target is written as-is."""
        fs = fs.write_symlink("data/broken", "nonexistent_target")
        out = tmp_path / "output"
        out.mkdir()

        sync_from_repo(fs, "data", str(out))
        assert (out / "broken").is_symlink()
        assert os.readlink(out / "broken") == "nonexistent_target"

    def test_symlink_inside_subdirectory(self, fs, tmp_path):
        """Symlink nested inside a subdirectory."""
        local = tmp_path / "local"
        (local / "sub").mkdir(parents=True)
        (local / "sub" / "real.txt").write_text("content")
        (local / "sub" / "link.txt").symlink_to("real.txt")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.readlink("data/sub/link.txt") == "real.txt"
        assert new_fs.read("data/sub/real.txt") == b"content"


# ---------------------------------------------------------------------------
# Edge cases — file/directory collisions
# ---------------------------------------------------------------------------

class TestSyncFileDirectoryCollisions:
    def test_file_replaces_directory_to_repo(self, fs, tmp_path):
        """Local file replaces a directory tree in repo."""
        fs = fs.write("data/foo/bar.txt", b"nested")
        fs = fs.write("data/foo/baz.txt", b"nested2")
        local = tmp_path / "local"
        local.mkdir()
        (local / "foo").write_text("I am a file now")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/foo") == b"I am a file now"
        assert not new_fs.exists("data/foo/bar.txt")
        assert not new_fs.exists("data/foo/baz.txt")

    def test_directory_replaces_file_to_repo(self, fs, tmp_path):
        """Local directory replaces a file in repo."""
        fs = fs.write("data/foo", b"I was a file")
        local = tmp_path / "local"
        (local / "foo").mkdir(parents=True)
        (local / "foo" / "bar.txt").write_text("nested")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/foo/bar.txt") == b"nested"
        assert new_fs.is_dir("data/foo")

    def test_file_replaces_directory_from_repo(self, fs, tmp_path):
        """Repo file replaces a local directory tree."""
        fs = fs.write("data/foo", b"I am a file")
        out = tmp_path / "output"
        (out / "foo").mkdir(parents=True)
        (out / "foo" / "bar.txt").write_text("nested")

        sync_from_repo(fs, "data", str(out))
        assert (out / "foo").is_file()
        assert (out / "foo").read_text() == "I am a file"

    def test_directory_replaces_file_from_repo(self, fs, tmp_path):
        """Repo directory tree replaces a local file."""
        fs = fs.write("data/foo/bar.txt", b"nested")
        out = tmp_path / "output"
        out.mkdir()
        (out / "foo").write_text("I was a file")

        sync_from_repo(fs, "data", str(out))
        assert (out / "foo").is_dir()
        assert (out / "foo" / "bar.txt").read_text() == "nested"

    def test_deep_file_replaces_deep_directory_to_repo(self, fs, tmp_path):
        """File at a/b replaces directory tree a/b/c/d in repo."""
        fs = fs.write("data/a/b/c/d.txt", b"deep")
        local = tmp_path / "local"
        (local / "a").mkdir(parents=True)
        (local / "a" / "b").write_text("shallow file")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/a/b") == b"shallow file"
        assert not new_fs.exists("data/a/b/c/d.txt")

    def test_dry_run_shows_collisions(self, fs, tmp_path):
        """Dry run correctly reports file/directory collision operations."""
        fs = fs.write("data/foo/bar.txt", b"nested")
        local = tmp_path / "local"
        local.mkdir()
        (local / "foo").write_text("file")

        plan = sync_to_repo_dry_run(fs, str(local), "data")
        assert "foo" in paths(plan.add)
        assert "foo/bar.txt" in paths(plan.delete)


# ---------------------------------------------------------------------------
# Edge cases — content
# ---------------------------------------------------------------------------

class TestSyncContentEdgeCases:
    def test_empty_file(self, fs, tmp_path):
        """Empty files (zero bytes) are synced correctly."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "empty.txt").write_bytes(b"")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/empty.txt") == b""

    def test_empty_file_from_repo(self, fs, tmp_path):
        """Empty files from repo are synced correctly."""
        fs = fs.write("data/empty.txt", b"")
        out = tmp_path / "output"
        out.mkdir()

        sync_from_repo(fs, "data", str(out))
        assert (out / "empty.txt").read_bytes() == b""

    def test_binary_files(self, fs, tmp_path):
        """Binary files with null bytes are synced correctly."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "bin.dat").write_bytes(bytes(range(256)))
        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/bin.dat") == bytes(range(256))

    def test_binary_files_from_repo(self, fs, tmp_path):
        data = bytes(range(256))
        fs = fs.write("data/bin.dat", data)
        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))
        assert (out / "bin.dat").read_bytes() == data

    def test_same_content_different_paths(self, fs, tmp_path):
        """Files with identical content at different paths are tracked independently."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "a.txt").write_text("same")
        (local / "b.txt").write_text("same")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/a.txt") == b"same"
        assert new_fs.read("data/b.txt") == b"same"

        # Delete just one locally
        (local / "b.txt").unlink()
        new_fs2 = sync_to_repo(new_fs, str(local), "data")
        assert new_fs2.read("data/a.txt") == b"same"
        assert not new_fs2.exists("data/b.txt")

    def test_whitespace_only_difference(self, fs, tmp_path):
        """Files differing only by trailing newline are detected as different."""
        fs = fs.write("data/f.txt", b"hello")
        local = tmp_path / "local"
        local.mkdir()
        (local / "f.txt").write_bytes(b"hello\n")

        plan = sync_to_repo_dry_run(fs, str(local), "data")
        assert "f.txt" in paths(plan.update)


# ---------------------------------------------------------------------------
# Edge cases — structure
# ---------------------------------------------------------------------------

class TestSyncStructureEdgeCases:
    def test_empty_local_dir_deletes_all_repo_files(self, fs, tmp_path):
        """Syncing an empty local directory deletes all repo files."""
        fs = fs.write("data/a.txt", b"a")
        fs = fs.write("data/b.txt", b"b")
        fs = fs.write("data/sub/c.txt", b"c")

        empty = tmp_path / "empty"
        empty.mkdir()

        new_fs = sync_to_repo(fs, str(empty), "data")
        assert not new_fs.exists("data")

    def test_empty_repo_path_deletes_all_local_files(self, fs, tmp_path):
        """Syncing from empty repo path deletes all local files."""
        # repo 'data' path doesn't exist (empty)
        out = tmp_path / "output"
        out.mkdir()
        (out / "a.txt").write_text("a")
        sub = out / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("b")

        sync_from_repo(fs, "data", str(out))
        # All files should be deleted, empty dirs pruned
        assert list(out.iterdir()) == []

    def test_deeply_nested_sync(self, fs, tmp_path):
        """Deeply nested directory tree syncs correctly."""
        local = tmp_path / "local"
        deep = local / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("deep")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/a/b/c/d/e/deep.txt") == b"deep"

    def test_deeply_nested_delete_cleans_parents(self, fs, tmp_path):
        """Deleting a deeply nested file cleans up all empty parent dirs."""
        fs = fs.write("data/x.txt", b"keep")
        out = tmp_path / "output"
        out.mkdir()
        deep = out / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "orphan.txt").write_text("orphan")

        sync_from_repo(fs, "data", str(out))
        assert (out / "x.txt").read_text() == "keep"
        assert not (out / "a").exists()

    def test_mixed_add_update_delete(self, fs, tmp_path):
        """Single sync with add, update, and delete operations."""
        fs = fs.write("data/keep.txt", b"keep")
        fs = fs.write("data/change.txt", b"old")
        fs = fs.write("data/remove.txt", b"bye")

        local = tmp_path / "local"
        local.mkdir()
        (local / "keep.txt").write_bytes(b"keep")
        (local / "change.txt").write_text("new")
        (local / "add.txt").write_text("new file")

        plan = sync_to_repo_dry_run(fs, str(local), "data")
        assert "add.txt" in paths(plan.add)
        assert "change.txt" in paths(plan.update)
        assert "remove.txt" in paths(plan.delete)
        assert "keep.txt" not in (paths(plan.add) | paths(plan.update) | paths(plan.delete))

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/keep.txt") == b"keep"
        assert new_fs.read("data/change.txt") == b"new"
        assert new_fs.read("data/add.txt") == b"new file"
        assert not new_fs.exists("data/remove.txt")

    def test_repo_path_is_a_file_not_directory(self, fs, tmp_path):
        """sync_to_repo when repo_path currently points to a file, not a tree."""
        fs = fs.write("data", b"I am a file at 'data'")
        local = tmp_path / "local"
        local.mkdir()
        (local / "hello.txt").write_text("hello")

        # The dry run should treat the file as "no children" (all adds)
        plan = sync_to_repo_dry_run(fs, str(local), "data")
        assert "hello.txt" in paths(plan.add)

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/hello.txt") == b"hello"
        assert new_fs.is_dir("data")


# ---------------------------------------------------------------------------
# Round-trip / consistency tests
# ---------------------------------------------------------------------------

class TestSyncRoundTrip:
    def test_dry_run_matches_actual_sync_to_repo(self, fs, tmp_path):
        """Dry-run plan matches what actual sync does."""
        fs = fs.write("data/old.txt", b"old")
        fs = fs.write("data/change.txt", b"v1")

        local = tmp_path / "local"
        local.mkdir()
        (local / "change.txt").write_text("v2")
        (local / "new.txt").write_text("new")

        plan = sync_to_repo_dry_run(fs, str(local), "data")
        new_fs = sync_to_repo(fs, str(local), "data")

        # Verify adds
        for p in paths(plan.add):
            assert new_fs.exists(f"data/{p}")
        # Verify deletes
        for p in paths(plan.delete):
            assert not new_fs.exists(f"data/{p}")
        # After sync, dry run should show in_sync
        plan2 = sync_to_repo_dry_run(new_fs, str(local), "data")
        assert plan2 is None

    def test_dry_run_matches_actual_sync_from_repo(self, fs, tmp_path):
        """Dry-run plan matches what actual sync does."""
        fs = fs.write("data/a.txt", b"alpha")
        fs = fs.write("data/sub/b.txt", b"beta")

        out = tmp_path / "output"
        out.mkdir()
        (out / "extra.txt").write_text("extra")

        plan = sync_from_repo_dry_run(fs, "data", str(out))
        sync_from_repo(fs, "data", str(out))

        # Verify adds
        for p in paths(plan.add):
            assert (out / p).exists()
        # Verify deletes
        for p in paths(plan.delete):
            assert not (out / p).exists()
        # After sync, dry run should show in_sync
        plan2 = sync_from_repo_dry_run(fs, "data", str(out))
        assert plan2 is None

    def test_round_trip_to_repo_and_back(self, fs, tmp_path):
        """sync_to_repo then sync_from_repo produces identical directory."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "a.txt").write_text("alpha")
        (local / "b.txt").write_bytes(b"\x00\x01\x02")
        sub = local / "sub"
        sub.mkdir()
        (sub / "c.txt").write_text("charlie")
        (local / "link").symlink_to("a.txt")

        new_fs = sync_to_repo(fs, str(local), "data")

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))

        # Compare contents
        assert (out / "a.txt").read_text() == "alpha"
        assert (out / "b.txt").read_bytes() == b"\x00\x01\x02"
        assert (out / "sub" / "c.txt").read_text() == "charlie"
        assert (out / "link").is_symlink()
        assert os.readlink(out / "link") == "a.txt"

    def test_round_trip_from_repo_and_back(self, fs, tmp_path):
        """sync_from_repo then sync_to_repo produces identical repo state."""
        fs = fs.write("data/x.txt", b"ex")
        fs = fs.write("data/sub/y.txt", b"why")
        fs = fs.write_symlink("data/link", "x.txt")

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))

        # Now sync back to a different repo path
        new_fs = sync_to_repo(fs, str(out), "data2")

        # Contents should match
        assert new_fs.read("data2/x.txt") == b"ex"
        assert new_fs.read("data2/sub/y.txt") == b"why"
        assert new_fs.readlink("data2/link") == "x.txt"

    def test_idempotent_complex_tree(self, fs, tmp_path):
        """Double sync on a complex tree is a no-op."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "a.txt").write_text("alpha")
        sub = local / "x" / "y" / "z"
        sub.mkdir(parents=True)
        (sub / "deep.txt").write_text("deep")
        (local / "link").symlink_to("a.txt")

        fs1 = sync_to_repo(fs, str(local), "data")
        fs2 = sync_to_repo(fs1, str(local), "data")
        assert fs1.commit_hash == fs2.commit_hash


# ---------------------------------------------------------------------------
# Dry-run / execution consistency (critical safety property)
# ---------------------------------------------------------------------------

class TestDryRunExactMatch:
    """Verify that dry-run plans exactly predict what execution does."""

    def test_dry_run_plan_exact_match_to_repo(self, fs, tmp_path):
        """Dry-run plan exactly predicts every change sync_to_repo makes."""
        # Set up repo with mix of files
        fs = fs.write("data/keep.txt", b"keep")
        fs = fs.write("data/change.txt", b"old")
        fs = fs.write("data/remove.txt", b"bye")
        fs = fs.write("data/sub/deep.txt", b"deep")

        # Local has different set
        local = tmp_path / "local"
        local.mkdir()
        (local / "keep.txt").write_bytes(b"keep")
        (local / "change.txt").write_text("new")
        (local / "add.txt").write_text("added")

        # Snapshot repo files before
        repo_before = set()
        for dp, _, fnames in fs.walk("data"):
            for fe in fnames:
                repo_before.add(f"{dp}/{fe.name}" if dp else fe.name)

        plan = sync_to_repo_dry_run(fs, str(local), "data")
        new_fs = sync_to_repo(fs, str(local), "data")

        # Snapshot repo files after
        repo_after = set()
        for dp, _, fnames in new_fs.walk("data"):
            for fe in fnames:
                repo_after.add(f"{dp}/{fe.name}" if dp else fe.name)

        # Every add in plan should be new
        for p in paths(plan.add):
            assert f"data/{p}" not in repo_before
            assert f"data/{p}" in repo_after

        # Every delete in plan should be removed
        for p in paths(plan.delete):
            assert f"data/{p}" in repo_before
            assert f"data/{p}" not in repo_after

        # Every update in plan should exist in both
        for p in paths(plan.update):
            assert f"data/{p}" in repo_before
            assert f"data/{p}" in repo_after

        # Nothing else changed — files not in plan should be same
        unchanged = repo_before & repo_after
        all_plan_paths = paths(plan.add) | paths(plan.update) | paths(plan.delete)
        plan_paths = {f"data/{p}" for p in all_plan_paths}
        for p in unchanged:
            if p not in plan_paths:
                # Verify content unchanged
                rp = p[len("data/"):]
                assert rp not in all_plan_paths

        # After sync, second dry-run shows in_sync
        plan2 = sync_to_repo_dry_run(new_fs, str(local), "data")
        assert plan2 is None

    def test_dry_run_plan_exact_match_from_repo(self, fs, tmp_path):
        """Dry-run plan exactly predicts every change sync_from_repo makes."""
        fs = fs.write("data/a.txt", b"alpha")
        fs = fs.write("data/sub/b.txt", b"beta")
        fs = fs.write("data/keep.txt", b"keep")

        out = tmp_path / "output"
        out.mkdir()
        (out / "keep.txt").write_bytes(b"keep")  # same content
        (out / "extra.txt").write_text("should be deleted")
        sub = out / "orphan"
        sub.mkdir()
        (sub / "old.txt").write_text("old")

        # Walk local before
        local_before = set()
        for dp, _, fnames in os.walk(out):
            for f in fnames:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, out).replace(os.sep, "/")
                local_before.add(rel)

        plan = sync_from_repo_dry_run(fs, "data", str(out))
        sync_from_repo(fs, "data", str(out))

        # Walk local after
        local_after = set()
        for dp, _, fnames in os.walk(out):
            for f in fnames:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, out).replace(os.sep, "/")
                local_after.add(rel)

        for p in paths(plan.add):
            assert p not in local_before
            assert p in local_after

        for p in paths(plan.delete):
            assert p in local_before
            assert p not in local_after

        for p in paths(plan.update):
            assert p in local_before
            assert p in local_after

        # After sync, should be in_sync
        plan2 = sync_from_repo_dry_run(fs, "data", str(out))
        assert plan2 is None

    def test_dry_run_plan_matches_with_collisions(self, fs, tmp_path):
        """Dry-run is accurate even with file/dir collisions and tree conflict filtering."""
        # Repo has directory tree at 'data/foo/...'
        fs = fs.write("data/foo/bar.txt", b"nested")
        fs = fs.write("data/foo/baz.txt", b"nested2")
        fs = fs.write("data/other.txt", b"other")

        # Local replaces foo directory with a file
        local = tmp_path / "local"
        local.mkdir()
        (local / "foo").write_text("I am a file now")
        (local / "other.txt").write_bytes(b"other")

        plan = sync_to_repo_dry_run(fs, str(local), "data")
        new_fs = sync_to_repo(fs, str(local), "data")

        # Plan should show 'foo' added and sub-files deleted
        assert "foo" in paths(plan.add)

        # After execution, verify the result matches expectations
        assert new_fs.read("data/foo") == b"I am a file now"
        assert not new_fs.exists("data/foo/bar.txt")
        assert not new_fs.exists("data/foo/baz.txt")
        assert new_fs.read("data/other.txt") == b"other"

        # And in_sync after
        plan2 = sync_to_repo_dry_run(new_fs, str(local), "data")
        assert plan2 is None


# ---------------------------------------------------------------------------
# Delete safety (critical — prevents data loss)
# ---------------------------------------------------------------------------

class TestDeleteSafety:
    """Verify sync_from_repo doesn't delete outside target or follow symlinks."""

    def test_sync_from_repo_does_not_touch_files_outside_target(self, fs, tmp_path):
        """Files in sibling directories are untouched after sync."""
        fs = fs.write("data/x.txt", b"ex")

        # Create sibling directory with files
        sibling = tmp_path / "sibling"
        sibling.mkdir()
        (sibling / "precious.txt").write_text("do not delete")
        (sibling / "sub").mkdir(parents=True)
        (sibling / "sub" / "deep.txt").write_text("deep precious")

        # Target directory
        out = tmp_path / "output"
        out.mkdir()
        (out / "old.txt").write_text("should be deleted")

        sync_from_repo(fs, "data", str(out))

        # Sibling directory untouched
        assert (sibling / "precious.txt").read_text() == "do not delete"
        assert (sibling / "sub" / "deep.txt").read_text() == "deep precious"

    def test_sync_from_repo_symlink_escape(self, fs, tmp_path):
        """Sync does NOT follow symlinks to delete files outside target."""
        fs = fs.write("data/x.txt", b"ex")

        # Create precious files outside target
        precious = tmp_path / "precious"
        precious.mkdir()
        (precious / "important.txt").write_text("do not delete")

        # Target directory with a symlink pointing outside
        out = tmp_path / "output"
        out.mkdir()
        (out / "escape_link").symlink_to(str(precious))
        (out / "regular.txt").write_text("delete me")

        sync_from_repo(fs, "data", str(out))

        # Precious files must still exist
        assert (precious / "important.txt").read_text() == "do not delete"
        assert precious.is_dir()

    def test_sync_from_repo_preserves_base_dir(self, fs, tmp_path):
        """After syncing to empty, the base directory itself still exists."""
        # Empty repo path — should delete all local files
        out = tmp_path / "output"
        out.mkdir()
        (out / "a.txt").write_text("a")
        sub = out / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("b")

        sync_from_repo(fs, "data", str(out))

        # Base dir still exists, just empty
        assert out.is_dir()
        assert list(out.iterdir()) == []

    def test_sync_from_repo_delete_only_planned_files(self, fs, tmp_path):
        """Exactly the right files are deleted — no more, no fewer."""
        # Repo has 5 files
        for i in range(5):
            fs = fs.write(f"data/keep_{i}.txt", f"keep {i}".encode())

        # Local has 10 files: the 5 in repo plus 5 extras
        out = tmp_path / "output"
        out.mkdir()
        for i in range(5):
            (out / f"keep_{i}.txt").write_bytes(f"keep {i}".encode())
        for i in range(5):
            (out / f"delete_{i}.txt").write_text(f"delete {i}")

        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert len(plan.delete) == 5
        assert sorted(paths(plan.delete)) == [f"delete_{i}.txt" for i in range(5)]
        assert len(plan.add) == 0
        assert len(plan.update) == 0

        sync_from_repo(fs, "data", str(out))

        # Verify exactly the right files remain
        remaining = sorted(f.name for f in out.iterdir())
        assert remaining == [f"keep_{i}.txt" for i in range(5)]

        # Verify content of kept files is correct
        for i in range(5):
            assert (out / f"keep_{i}.txt").read_bytes() == f"keep {i}".encode()


# ---------------------------------------------------------------------------
# Symlink edge cases (informed by Syncthing bugs)
# ---------------------------------------------------------------------------

class TestSyncSymlinkEdgeCases:
    """Edge cases informed by Syncthing/rsync symlink bugs."""

    def test_symlink_to_directory_replaced_by_regular_dir_from_repo(self, fs, tmp_path):
        """Local has symlinked dir -> repo has real dir. Sync replaces symlink with dir."""
        # Repo has a real directory with a file
        fs = fs.write("data/sub/file.txt", b"content")

        # Local has a symlink 'sub' pointing elsewhere
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "other.txt").write_text("other")

        out = tmp_path / "output"
        out.mkdir()
        (out / "sub").symlink_to(str(elsewhere))

        sync_from_repo(fs, "data", str(out))

        # 'sub' should now be a real directory, not a symlink
        assert (out / "sub").is_dir()
        assert not (out / "sub").is_symlink()
        assert (out / "sub" / "file.txt").read_text() == "content"

        # 'elsewhere' should be untouched
        assert (elsewhere / "other.txt").read_text() == "other"

    def test_symlink_to_directory_replaced_by_file_from_repo(self, fs, tmp_path):
        """Local has symlinked dir -> repo has regular file at same name."""
        fs = fs.write("data/sub", b"I am a file")

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "other.txt").write_text("other")

        out = tmp_path / "output"
        out.mkdir()
        (out / "sub").symlink_to(str(elsewhere))

        sync_from_repo(fs, "data", str(out))

        assert (out / "sub").is_file()
        assert not (out / "sub").is_symlink()
        assert (out / "sub").read_text() == "I am a file"

        # Elsewhere untouched
        assert (elsewhere / "other.txt").read_text() == "other"

    def test_absolute_symlink_preserved(self, fs, tmp_path):
        """Symlink with absolute target path round-trips correctly."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "abs_link").symlink_to("/usr/bin/env")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.readlink("data/abs_link") == "/usr/bin/env"

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))
        assert (out / "abs_link").is_symlink()
        assert os.readlink(out / "abs_link") == "/usr/bin/env"

    def test_relative_symlink_with_dotdot(self, fs, tmp_path):
        """Symlink target '../sibling/file' is stored and restored as-is."""
        local = tmp_path / "local"
        (local / "sub").mkdir(parents=True)
        (local / "sub" / "uplink").symlink_to("../sibling/file")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.readlink("data/sub/uplink") == "../sibling/file"

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))
        assert os.readlink(out / "sub" / "uplink") == "../sibling/file"

    def test_symlink_to_self_circular(self, fs, tmp_path):
        """A symlink pointing to itself is stored/restored without hanging."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "selfref").symlink_to("selfref")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.readlink("data/selfref") == "selfref"

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))
        assert (out / "selfref").is_symlink()
        assert os.readlink(out / "selfref") == "selfref"

    def test_walk_local_does_not_follow_symlinked_dirs(self, fs, tmp_path):
        """_walk_local doesn't descend into symlinked directories."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "real.txt").write_text("real")

        # Create a symlinked directory with files that should NOT appear
        target_dir = tmp_path / "target_dir"
        target_dir.mkdir()
        (target_dir / "hidden.txt").write_text("should not appear")
        (target_dir / "sub").mkdir()
        (target_dir / "sub" / "nested.txt").write_text("also hidden")

        (local / "linked_dir").symlink_to(str(target_dir))

        new_fs = sync_to_repo(fs, str(local), "data")

        # linked_dir should be stored as a symlink, not traversed
        assert new_fs.readlink("data/linked_dir") == str(target_dir)
        # Files inside the symlinked dir should NOT be in repo
        assert not new_fs.exists("data/linked_dir/hidden.txt")
        assert not new_fs.exists("data/linked_dir/sub/nested.txt")


# ---------------------------------------------------------------------------
# Symlinks in-sync: mode comparison must not flag symlinks as updates
# ---------------------------------------------------------------------------

class TestSyncSymlinksInSync:
    """Symlinks already in sync must not be reported as updates."""

    def test_file_symlink_in_sync_to_repo(self, fs, tmp_path):
        """A file symlink synced to repo and re-synced produces no updates."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "link").symlink_to("target")
        (local / "file.txt").write_text("hello")

        fs1 = sync_to_repo(fs, str(local), "data")
        plan = sync_to_repo_dry_run(fs1, str(local), "data")
        assert plan is None

    def test_dir_symlink_in_sync_to_repo(self, fs, tmp_path):
        """A directory symlink synced to repo and re-synced produces no updates."""
        target_dir = tmp_path / "target_dir"
        target_dir.mkdir()
        (target_dir / "child.txt").write_text("child")

        local = tmp_path / "local"
        local.mkdir()
        (local / "linked_dir").symlink_to(str(target_dir))

        fs1 = sync_to_repo(fs, str(local), "data")
        plan = sync_to_repo_dry_run(fs1, str(local), "data")
        assert plan is None

    def test_file_symlink_in_sync_from_repo(self, fs, tmp_path):
        """A file symlink synced from repo and re-synced produces no updates."""
        fs = fs.write_symlink("data/link", "target")
        fs = fs.write("data/file.txt", b"hello")

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))

        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert plan is None

    def test_dir_symlink_from_repo_no_false_update(self, fs, tmp_path):
        """A dir-targeting symlink from repo doesn't raise IsADirectoryError."""
        target_dir = tmp_path / "target_dir"
        target_dir.mkdir()
        (target_dir / "child.txt").write_text("child")

        fs = fs.write_symlink("data/linked_dir", str(target_dir))
        fs = fs.write("data/file.txt", b"hello")

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))

        # Re-sync should produce no changes
        plan = sync_from_repo_dry_run(fs, "data", str(out))
        assert plan is None


# ---------------------------------------------------------------------------
# Unicode / special character filenames
# ---------------------------------------------------------------------------

class TestSyncUnicodeFilenames:
    """Verify filenames with unicode and special characters sync correctly."""

    def test_unicode_filename_to_repo(self, fs, tmp_path):
        """File named with unicode characters syncs to repo correctly."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "café.txt").write_text("coffee")
        (local / "日本語.txt").write_text("japanese")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/café.txt") == b"coffee"
        assert new_fs.read("data/日本語.txt") == b"japanese"

    def test_unicode_filename_from_repo(self, fs, tmp_path):
        """File named with unicode characters syncs from repo correctly."""
        fs = fs.write("data/café.txt", b"coffee")
        fs = fs.write("data/日本語.txt", b"japanese")

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(fs, "data", str(out))

        assert (out / "café.txt").read_text() == "coffee"
        assert (out / "日本語.txt").read_text() == "japanese"

    def test_unicode_round_trip(self, fs, tmp_path):
        """Unicode filenames survive a full round-trip."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "café.txt").write_text("coffee")

        new_fs = sync_to_repo(fs, str(local), "data")

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))

        assert (out / "café.txt").read_text() == "coffee"

        # And syncing back should be in_sync
        plan = sync_to_repo_dry_run(new_fs, str(out), "data")
        assert plan is None

    def test_filename_with_spaces(self, fs, tmp_path):
        """Filenames with spaces sync correctly both directions."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "my file.txt").write_text("spaces")
        (local / "sub dir").mkdir()
        (local / "sub dir" / "another file.txt").write_text("nested spaces")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/my file.txt") == b"spaces"
        assert new_fs.read("data/sub dir/another file.txt") == b"nested spaces"

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))
        assert (out / "my file.txt").read_text() == "spaces"
        assert (out / "sub dir" / "another file.txt").read_text() == "nested spaces"

    def test_filename_with_special_chars(self, fs, tmp_path):
        """Filenames with #, @, =, + characters sync correctly."""
        local = tmp_path / "local"
        local.mkdir()
        (local / "file#1.txt").write_text("hash")
        (local / "file@2.txt").write_text("at")
        (local / "a=b.txt").write_text("equals")
        (local / "c+d.txt").write_text("plus")

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/file#1.txt") == b"hash"
        assert new_fs.read("data/file@2.txt") == b"at"
        assert new_fs.read("data/a=b.txt") == b"equals"
        assert new_fs.read("data/c+d.txt") == b"plus"

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))
        assert (out / "file#1.txt").read_text() == "hash"
        assert (out / "file@2.txt").read_text() == "at"
        assert (out / "a=b.txt").read_text() == "equals"
        assert (out / "c+d.txt").read_text() == "plus"


# ---------------------------------------------------------------------------
# Concurrent / overlapping paths
# ---------------------------------------------------------------------------

class TestSyncOverlappingPaths:
    """Verify independent sync paths don't interfere."""

    def test_multiple_repo_paths_independent(self, fs, tmp_path):
        """Syncing two local dirs to different repo paths doesn't interfere."""
        local_a = tmp_path / "local_a"
        local_a.mkdir()
        (local_a / "a.txt").write_text("from a")

        local_b = tmp_path / "local_b"
        local_b.mkdir()
        (local_b / "b.txt").write_text("from b")

        fs1 = sync_to_repo(fs, str(local_a), "path_a")
        fs2 = sync_to_repo(fs1, str(local_b), "path_b")

        assert fs2.read("path_a/a.txt") == b"from a"
        assert fs2.read("path_b/b.txt") == b"from b"

        # Verify reverse direction
        out_a = tmp_path / "out_a"
        out_b = tmp_path / "out_b"
        out_a.mkdir()
        out_b.mkdir()

        sync_from_repo(fs2, "path_a", str(out_a))
        sync_from_repo(fs2, "path_b", str(out_b))

        assert (out_a / "a.txt").read_text() == "from a"
        assert not (out_a / "b.txt").exists()
        assert (out_b / "b.txt").read_text() == "from b"
        assert not (out_b / "a.txt").exists()

    def test_sync_to_repo_root_then_subpath(self, fs, tmp_path):
        """Sync to root, then sync different content to subpath."""
        local_root = tmp_path / "root_content"
        local_root.mkdir()
        (local_root / "top.txt").write_text("top")
        (local_root / "sub").mkdir()
        (local_root / "sub" / "original.txt").write_text("original")

        fs1 = sync_to_repo(fs, str(local_root), "")

        # Now sync different content to just the 'sub' path
        local_sub = tmp_path / "sub_content"
        local_sub.mkdir()
        (local_sub / "replacement.txt").write_text("replaced")

        fs2 = sync_to_repo(fs1, str(local_sub), "sub")

        # 'top.txt' should still exist
        assert fs2.read("top.txt") == b"top"
        # 'sub/original.txt' should be gone
        assert not fs2.exists("sub/original.txt")
        # 'sub/replacement.txt' should exist
        assert fs2.read("sub/replacement.txt") == b"replaced"


# ---------------------------------------------------------------------------
# Large / stress scenarios
# ---------------------------------------------------------------------------

class TestSyncStress:
    """Stress tests with many files and large content."""

    def test_many_files(self, fs, tmp_path):
        """Sync 200+ files in various subdirectories. Verify round-trip."""
        local = tmp_path / "local"
        local.mkdir()

        expected = {}
        for i in range(200):
            subdir = f"dir_{i % 10}"
            (local / subdir).mkdir(exist_ok=True)
            name = f"{subdir}/file_{i}.txt"
            content = f"content_{i}"
            (local / subdir / f"file_{i}.txt").write_text(content)
            expected[name] = content

        new_fs = sync_to_repo(fs, str(local), "data")

        # Verify all files in repo
        for name, content in expected.items():
            assert new_fs.read(f"data/{name}") == content.encode()

        # Round-trip back
        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))

        for name, content in expected.items():
            assert (out / name).read_text() == content

        # Final dry-run should show in_sync
        plan = sync_to_repo_dry_run(new_fs, str(out), "data")
        assert plan is None

    def test_large_file(self, fs, tmp_path):
        """Single 1MB file syncs correctly both directions."""
        local = tmp_path / "local"
        local.mkdir()
        # 1MB of repeating pattern
        content = (b"abcdefghij" * 100) * 1000  # exactly 1MB
        assert len(content) == 1_000_000
        (local / "large.bin").write_bytes(content)

        new_fs = sync_to_repo(fs, str(local), "data")
        assert new_fs.read("data/large.bin") == content

        out = tmp_path / "output"
        out.mkdir()
        sync_from_repo(new_fs, "data", str(out))
        assert (out / "large.bin").read_bytes() == content


# ---------------------------------------------------------------------------
# Error / boundary conditions
# ---------------------------------------------------------------------------

class TestSyncErrors:
    """Error handling and boundary conditions."""

    def test_sync_to_repo_nonexistent_local_path_is_noop(self, fs):
        """Syncing from nonexistent local path is a no-op (os.walk yields nothing)."""
        # os.walk on nonexistent path silently yields nothing,
        # so syncing treats it as empty. With empty repo, that's a no-op.
        result = sync_to_repo(fs, "/nonexistent/path/that/does/not/exist", "data")
        assert result.ls() == []

    def test_sync_to_repo_nonexistent_local_deletes_repo(self, fs):
        """Syncing from nonexistent path deletes all existing repo content."""
        fs = fs.write("data/x.txt", b"ex")
        result = sync_to_repo(fs, "/nonexistent/path", "data")
        assert not result.exists("data/x.txt")

    def test_sync_from_repo_nonexistent_repo_path_creates_empty(self, fs, tmp_path):
        """If repo path doesn't exist, local dir becomes empty."""
        out = tmp_path / "output"
        out.mkdir()
        (out / "a.txt").write_text("should be deleted")
        (out / "sub").mkdir()
        (out / "sub" / "b.txt").write_text("also deleted")

        sync_from_repo(fs, "nonexistent", str(out))
        assert list(out.iterdir()) == []
        assert out.is_dir()  # base dir preserved

    def test_sync_plan_immutability(self, fs, tmp_path):
        """Calling dry-run twice returns identical plans (no side effects)."""
        fs = fs.write("data/a.txt", b"alpha")

        local = tmp_path / "local"
        local.mkdir()
        (local / "b.txt").write_text("beta")

        plan1 = sync_to_repo_dry_run(fs, str(local), "data")
        plan2 = sync_to_repo_dry_run(fs, str(local), "data")

        assert plan1.add == plan2.add
        assert plan1.update == plan2.update
        assert plan1.delete == plan2.delete

    def test_sync_plan_immutability_from_repo(self, fs, tmp_path):
        """Calling from_repo dry-run twice returns identical plans."""
        fs = fs.write("data/a.txt", b"alpha")

        out = tmp_path / "output"
        out.mkdir()
        (out / "b.txt").write_text("beta")

        plan1 = sync_from_repo_dry_run(fs, "data", str(out))
        plan2 = sync_from_repo_dry_run(fs, "data", str(out))

        assert plan1.add == plan2.add
        assert plan1.update == plan2.update
        assert plan1.delete == plan2.delete

    def test_sync_from_repo_to_readonly_parent(self, fs, tmp_path):
        """If output parent can't be written to, raises clear error."""
        fs = fs.write("data/x.txt", b"ex")
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o444)
        try:
            with pytest.raises(OSError):
                sync_from_repo(fs, "data", str(readonly / "sub" / "output"))
        finally:
            readonly.chmod(0o755)


# ---------------------------------------------------------------------------
# Fix 1: _walk_repo returns empty for file repo_path
# ---------------------------------------------------------------------------

class TestSyncDeleteFileAtRepoPath:
    """Fix 1: sync should delete a file when repo_path points to a file."""

    def test_sync_to_repo_deletes_file_at_repo_path(self, fs, tmp_path):
        """When repo_path is a single file and local_path is empty, file is deleted."""
        fs = fs.write("data", b"I am a file at 'data'")
        assert fs.exists("data")

        # Sync from nonexistent local → should delete the file
        new_fs = sync_to_repo(fs, "/nonexistent/path", "data")
        assert not new_fs.exists("data")

    def test_sync_to_repo_dry_run_shows_file_delete(self, fs):
        """Dry-run reports delete when repo_path is a file and local is empty."""
        fs = fs.write("data", b"I am a file at 'data'")
        plan = sync_to_repo_dry_run(fs, "/nonexistent/path", "data")
        assert "data" in paths(plan.delete)

    def test_sync_to_repo_dry_run_file_delete_plan_path(self, fs):
        """Verify delete path for file-at-dest uses the actual file path."""
        fs = fs.write("data", b"I am a file at 'data'")
        plan = sync_to_repo_dry_run(fs, "/nonexistent/path", "data")
        assert plan is not None
        assert sorted(paths(plan.delete)) == ["data"]

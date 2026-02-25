"""Tests for FS.copy_from_ref() — branch-to-branch atomic copy."""

import os

import pytest

from gitstore import GitStore
from gitstore.copy._types import FileType
from gitstore.fs import FS


def paths(entries):
    """Extract paths from FileEntry list."""
    return {e.path for e in entries} if entries else set()


@pytest.fixture
def store(tmp_path):
    """Create a store with two branches: main and worker."""
    repo = GitStore.open(tmp_path / "test.git")

    # Seed main with some files
    main = repo.branches["main"]
    main = main.write("readme.txt", b"hello")
    main = main.write("data/x.txt", b"x-main")

    # Create worker branch from main
    repo.branches["worker"] = main
    worker = repo.branches["worker"]
    worker = worker.write("results/a.json", b'{"a":1}')
    worker = worker.write("results/b.json", b'{"b":2}')
    worker = worker.write("data/x.txt", b"x-worker")
    worker = worker.write("data/y.txt", b"y-worker")

    return repo


class TestCopyRefBasic:
    def test_copy_subtree_adds_files(self, store):
        """Dir mode: 'results' copies results/ as results/ into root."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results")
        assert main.read("results/a.json") == b'{"a":1}'
        assert main.read("results/b.json") == b'{"b":2}'
        # Existing files untouched
        assert main.read("readme.txt") == b"hello"

    def test_copy_with_updates(self, store):
        """Dir mode: 'data' copies data/ as data/ — updates existing files."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "data")
        assert main.read("data/x.txt") == b"x-worker"
        assert main.read("data/y.txt") == b"y-worker"

    def test_dest_defaults_to_root(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results")
        assert main.exists("results/a.json")
        assert main.exists("results/b.json")

    def test_copy_to_different_dest_contents_mode(self, store):
        """Contents mode with explicit dest: pour results/ contents into backup/results."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results/", "backup/results")
        assert main.read("backup/results/a.json") == b'{"a":1}'
        assert main.read("backup/results/b.json") == b'{"b":2}'
        # Original path untouched
        assert not main.exists("results/a.json")

    def test_copy_root_to_root(self, store):
        """Copy everything from worker to main (default paths)."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker)
        # Worker files present
        assert main.read("results/a.json") == b'{"a":1}'
        assert main.read("data/x.txt") == b"x-worker"
        assert main.read("data/y.txt") == b"y-worker"
        # Existing main files still present (no delete)
        assert main.read("readme.txt") == b"hello"


class TestCopyRefDelete:
    def test_delete_removes_extra_dest_files(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        # main has data/x.txt, worker has data/x.txt + data/y.txt
        # Copy worker data/ into main data/ — no deletes yet
        main = main.copy_from_ref(worker, "data")
        assert main.exists("data/x.txt")
        assert main.exists("data/y.txt")

        # Now remove y from worker and sync with delete
        worker = store.branches["worker"]
        worker = worker.remove("data/y.txt")
        main = store.branches["main"]
        main = main.copy_from_ref(worker, "data", delete=True)
        assert main.exists("data/x.txt")
        assert not main.exists("data/y.txt")

    def test_delete_only_affects_dest_path(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results", delete=True)
        # readme.txt is outside dest_path, should be untouched
        assert main.read("readme.txt") == b"hello"

    def test_delete_with_dir_mode(self, store):
        """Delete only removes files under the dir-mode target."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        # First copy results into main
        main = main.copy_from_ref(worker, "results")
        # Add an extra file under results/
        main = main.write("results/extra.txt", b"extra")

        # Now copy again with delete — extra.txt should be removed
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "results", delete=True)
        assert main.exists("results/a.json")
        assert main.exists("results/b.json")
        assert not main.exists("results/extra.txt")


class TestCopyRefDryRun:
    def test_dry_run_no_commit(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        original_hash = main.commit_hash

        result = main.copy_from_ref(worker, "results", dry_run=True)
        assert result.commit_hash == original_hash
        assert result.changes is not None
        assert len(result.changes.add) == 2
        # Verify files not actually written
        assert not result.exists("results/a.json")

    def test_dry_run_with_updates(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        result = main.copy_from_ref(worker, "data", dry_run=True)
        assert result.changes is not None
        assert paths(result.changes.update) == {"data/x.txt"}
        assert paths(result.changes.add) == {"data/y.txt"}

    def test_dry_run_with_delete(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        # Put extra file in main's results
        main = main.write("results/extra.txt", b"extra")
        worker = store.branches["worker"]

        result = main.copy_from_ref(worker, "results", delete=True, dry_run=True)
        assert result.changes is not None
        assert paths(result.changes.delete) == {"results/extra.txt"}


class TestCopyRefFromTag:
    def test_copy_from_tag(self, store):
        worker = store.branches["worker"]
        store.tags["v1.0"] = worker

        main = store.branches["main"]
        tag_fs = store.tags["v1.0"]
        main = main.copy_from_ref(tag_fs, "results")
        assert main.read("results/a.json") == b'{"a":1}'

    def test_copy_from_detached(self, store):
        worker = store.branches["worker"]
        detached = FS(store, worker._commit_oid)  # branch=None → read-only

        main = store.branches["main"]
        main = main.copy_from_ref(detached, "results")
        assert main.read("results/a.json") == b'{"a":1}'


class TestCopyRefNoop:
    def test_noop_returns_same_fs(self, store):
        """If source matches dest, no commit is created."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        # Copy results in
        main = main.copy_from_ref(worker, "results")
        hash_after_first = main.commit_hash

        # Copy again — same content, should be a noop
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "results")
        assert main.commit_hash == hash_after_first


class TestCopyRefValidation:
    def test_reject_cross_repo(self, tmp_path):
        repo1 = GitStore.open(tmp_path / "r1.git")
        repo2 = GitStore.open(tmp_path / "r2.git")
        fs1 = repo1.branches["main"]
        fs1 = fs1.write("a.txt", b"a")
        fs2 = repo2.branches["main"]
        fs2 = fs2.write("b.txt", b"b")

        with pytest.raises(ValueError, match="same repo"):
            fs2.copy_from_ref(fs1, "a.txt")

    def test_reject_readonly_dest(self, store):
        worker = store.branches["worker"]
        readonly = FS(store, worker._commit_oid)  # branch=None → read-only

        with pytest.raises(PermissionError):
            readonly.copy_from_ref(worker, "results")

    def test_nonexistent_src_raises(self, store):
        """Copying from a nonexistent path raises FileNotFoundError."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        with pytest.raises(FileNotFoundError):
            main.copy_from_ref(worker, "nonexistent")


class TestCopyRefMode:
    def test_preserves_executable_mode(self, store):
        worker = store.branches["worker"]
        worker = worker.write("bin/run.sh", b"#!/bin/sh", mode=FileType.EXECUTABLE)

        main = store.branches["main"]
        main = main.copy_from_ref(worker, "bin")
        assert main.file_type("bin/run.sh") == FileType.EXECUTABLE

    def test_preserves_symlink(self, store):
        worker = store.branches["worker"]
        worker = worker.write_symlink("links/readme", "../readme.txt")

        main = store.branches["main"]
        main = main.copy_from_ref(worker, "links")
        assert main.file_type("links/readme") == FileType.LINK
        assert main.readlink("links/readme") == "../readme.txt"


class TestCopyRefMessage:
    def test_custom_message(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results", message="Import results from worker")
        assert main.message == "Import results from worker"

    def test_auto_message(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results")
        # Auto-generated message should exist and not be empty
        assert main.message


class TestCopyRefPathNormalization:
    """copy_from_ref follows rsync conventions for trailing slashes."""

    def test_contents_mode_trailing_slash(self, store):
        """Trailing slash = contents mode: pour contents into dest."""
        main = store.branches["main"]
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "results/")
        # Contents mode at root → files land at root
        assert main.read("a.json") == b'{"a":1}'
        assert main.read("b.json") == b'{"b":2}'

    def test_contents_mode_to_dest(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "results/", "backup/results")
        assert main.read("backup/results/a.json") == b'{"a":1}'
        assert main.read("backup/results/b.json") == b'{"b":2}'

    def test_dry_run_with_trailing_slash(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        result = main.copy_from_ref(worker, "results/", dry_run=True)
        assert result.changes is not None
        assert len(result.changes.add) == 2


class TestCopyRefStale:
    def test_stale_snapshot_propagates(self, store):
        from gitstore.exceptions import StaleSnapshotError

        main = store.branches["main"]
        worker = store.branches["worker"]

        # Advance main behind our back
        main2 = store.branches["main"]
        main2.write("conflict.txt", b"conflict")

        with pytest.raises(StaleSnapshotError):
            main.copy_from_ref(worker, "results")


class TestCopyRefSingleFile:
    """New: single file copy support."""

    def test_single_file_to_root(self, store):
        """Copying a single file places it at the root."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results/a.json")
        assert main.read("a.json") == b'{"a":1}'

    def test_single_file_to_dest(self, store):
        """Copying a single file into a dest directory."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results/a.json", "backup")
        assert main.read("backup/a.json") == b'{"a":1}'

    def test_single_file_dry_run(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        result = main.copy_from_ref(worker, "results/a.json", dry_run=True)
        assert result.changes is not None
        assert len(result.changes.add) == 1
        assert result.changes.add[0].path == "a.json"


class TestCopyRefDirMode:
    """New: dir mode (no trailing slash) preserves directory name."""

    def test_dir_mode_to_explicit_dest(self, store):
        """Dir mode copies dirname into dest."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results", "backup")
        assert main.read("backup/results/a.json") == b'{"a":1}'
        assert main.read("backup/results/b.json") == b'{"b":2}'

    def test_contents_mode_to_explicit_dest(self, store):
        """Contents mode pours files directly into dest (no dirname)."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results/", "backup")
        assert main.read("backup/a.json") == b'{"a":1}'
        assert main.read("backup/b.json") == b'{"b":2}'
        # Should NOT have backup/results/
        assert not main.exists("backup/results")


class TestCopyRefMultipleSources:
    """New: multiple sources in a single call."""

    def test_multiple_mixed_sources(self, store):
        """Mix of dir and file sources in one call."""
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, ["results", "data/x.txt"])
        # Dir mode: results/ → results/
        assert main.read("results/a.json") == b'{"a":1}'
        assert main.read("results/b.json") == b'{"b":2}'
        # File mode: data/x.txt → x.txt at root
        assert main.read("x.txt") == b"x-worker"

    def test_multiple_sources_to_dest(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, ["results/", "data/x.txt"], "backup")
        # Contents: results/ contents poured into backup/
        assert main.read("backup/a.json") == b'{"a":1}'
        # File: x.txt placed in backup/
        assert main.read("backup/x.txt") == b"x-worker"

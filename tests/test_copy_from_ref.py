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
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results")
        assert main.read("results/a.json") == b'{"a":1}'
        assert main.read("results/b.json") == b'{"b":2}'
        # Existing files untouched
        assert main.read("readme.txt") == b"hello"

    def test_copy_with_updates(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "data")
        assert main.read("data/x.txt") == b"x-worker"
        assert main.read("data/y.txt") == b"y-worker"

    def test_dest_defaults_to_src_path(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results")
        assert main.exists("results/a.json")
        assert main.exists("results/b.json")

    def test_copy_to_different_dest(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]

        main = main.copy_from_ref(worker, "results", "backup/results")
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

    def test_nonexistent_src_path_is_noop(self, store):
        """Copying from a nonexistent subtree should be a noop."""
        main = store.branches["main"]
        worker = store.branches["worker"]
        original_hash = main.commit_hash

        main = main.copy_from_ref(worker, "nonexistent")
        assert main.commit_hash == original_hash


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
    """Fix 1: copy_from_ref normalizes leading/trailing slashes."""

    def test_leading_slash_src_path(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "/results")
        assert main.read("results/a.json") == b'{"a":1}'

    def test_trailing_slash_src_path(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "results/")
        assert main.read("results/a.json") == b'{"a":1}'

    def test_leading_and_trailing_slashes(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "/results/", "/backup/results/")
        assert main.read("backup/results/a.json") == b'{"a":1}'

    def test_dest_path_trailing_slash(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        main = main.copy_from_ref(worker, "results", "backup/")
        assert main.read("backup/a.json") == b'{"a":1}'

    def test_dry_run_with_slashes(self, store):
        main = store.branches["main"]
        worker = store.branches["worker"]
        result = main.copy_from_ref(worker, "/results/", dry_run=True)
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

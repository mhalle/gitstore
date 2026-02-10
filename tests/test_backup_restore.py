"""Tests for the gitstore backup/restore CLI commands."""

import pytest
from click.testing import CliRunner
from dulwich.repo import Repo as DulwichRepo

from gitstore.cli import main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def repo_path(tmp_path):
    """Return a path to a not-yet-created repo."""
    return str(tmp_path / "test.git")


@pytest.fixture
def remote_path(tmp_path):
    """Return a path to a bare remote repo (pre-created)."""
    p = str(tmp_path / "remote.git")
    DulwichRepo.init_bare(p, mkdir=True)
    return p


@pytest.fixture
def repo_with_data(tmp_path, runner):
    """Create a repo with files on 'main' and a tag, return its path."""
    p = str(tmp_path / "src.git")
    r = runner.invoke(main, ["init", "--repo", p, "--branch", "main"])
    assert r.exit_code == 0, r.output

    hello = tmp_path / "hello.txt"
    hello.write_text("hello world\n")
    r = runner.invoke(main, ["cp", "--repo", p, str(hello), ":hello.txt"])
    assert r.exit_code == 0, r.output

    r = runner.invoke(main, ["tag", "--repo", p, "create", "v1", "--from", "main"])
    assert r.exit_code == 0, r.output

    return p


def _get_refs(repo_path):
    """Return {ref_name_str: sha_hex_str} for a bare repo, excluding HEAD."""
    repo = DulwichRepo(repo_path)
    return {
        ref.decode(): sha.decode()
        for ref, sha in repo.get_refs().items()
        if ref != b"HEAD"
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBackupCreatesMirror:
    def test_backup_to_empty_remote(self, runner, repo_with_data, tmp_path):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        local_refs = _get_refs(repo_with_data)
        remote_refs = _get_refs(remote)
        assert local_refs == remote_refs
        assert any("refs/heads/main" in ref for ref in remote_refs)
        assert any("refs/tags/v1" in ref for ref in remote_refs)


class TestRestoreFromBackup:
    def test_restore_reverts_local_changes(self, runner, repo_with_data, tmp_path):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup original state
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output
        original_refs = _get_refs(repo_with_data)

        # Modify local: add a new file
        newfile = tmp_path / "new.txt"
        newfile.write_text("new content\n")
        r = runner.invoke(main, ["cp", "--repo", repo_with_data, str(newfile), ":new.txt"])
        assert r.exit_code == 0, r.output

        # Refs have changed (new commit)
        modified_refs = _get_refs(repo_with_data)
        assert modified_refs != original_refs

        # Restore from backup
        r = runner.invoke(main, ["restore", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        restored_refs = _get_refs(repo_with_data)
        assert restored_refs == original_refs


class TestBackupDryRun:
    def test_dry_run_shows_changes_without_modifying_remote(
        self, runner, repo_with_data, tmp_path
    ):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        r = runner.invoke(main, ["backup", "--repo", repo_with_data, "-n", remote])
        assert r.exit_code == 0, r.output
        assert "create" in r.output

        # Remote should still be empty
        remote_refs = _get_refs(remote)
        assert len(remote_refs) == 0

    def test_dry_run_in_sync(self, runner, repo_with_data, tmp_path):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup first
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Dry-run should show nothing to push
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, "-n", remote])
        assert r.exit_code == 0, r.output
        assert "already in sync" in r.output


class TestRestoreDryRun:
    def test_dry_run_shows_changes_without_modifying_local(
        self, runner, repo_with_data, tmp_path
    ):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup to remote
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Create a new local-only branch
        r = runner.invoke(main, [
            "branch", "--repo", repo_with_data, "create", "feature",
            "--from", "main",
        ])
        assert r.exit_code == 0, r.output
        refs_before = _get_refs(repo_with_data)

        # Dry-run restore: should show the delete but not apply it
        r = runner.invoke(main, ["restore", "--repo", repo_with_data, "-n", remote])
        assert r.exit_code == 0, r.output
        assert "delete" in r.output

        # Local refs should be unchanged
        refs_after = _get_refs(repo_with_data)
        assert refs_after == refs_before


class TestBackupDeletesRemoteOnlyRefs:
    def test_remote_only_branch_deleted(self, runner, repo_with_data, tmp_path):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Create a branch on remote only (via a second repo)
        remote_dulwich = DulwichRepo(remote)
        main_sha = remote_dulwich.refs[b"refs/heads/main"]
        remote_dulwich.refs[b"refs/heads/extra"] = main_sha

        assert b"refs/heads/extra" in remote_dulwich.get_refs()

        # Backup again — should delete 'extra' from remote
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        remote_refs = _get_refs(remote)
        assert "refs/heads/extra" not in remote_refs


class TestRestoreDeletesLocalOnlyRefs:
    def test_local_only_branch_deleted(self, runner, repo_with_data, tmp_path):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Create a local-only branch
        r = runner.invoke(main, [
            "branch", "--repo", repo_with_data, "create", "local-only",
            "--from", "main",
        ])
        assert r.exit_code == 0, r.output
        assert "refs/heads/local-only" in _get_refs(repo_with_data)

        # Restore — should delete 'local-only'
        r = runner.invoke(main, ["restore", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        local_refs = _get_refs(repo_with_data)
        assert "refs/heads/local-only" not in local_refs


class TestBackupForceOverwrites:
    def test_diverged_histories_overwritten(self, runner, repo_with_data, tmp_path):
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        original_refs = _get_refs(remote)

        # Create a divergent commit on remote
        remote_dulwich = DulwichRepo(remote)
        from dulwich.objects import Blob, Commit, Tree
        import time

        blob = Blob.from_string(b"divergent content")
        remote_dulwich.object_store.add_object(blob)
        tree = Tree()
        tree.add(b"divergent.txt", 0o100644, blob.id)
        remote_dulwich.object_store.add_object(tree)
        commit = Commit()
        commit.tree = tree.id
        commit.author = commit.committer = b"test <test@test>"
        commit.author_time = commit.commit_time = int(time.time())
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"divergent commit\n"
        commit.encoding = b"UTF-8"
        commit.parents = []  # no parent — diverged
        remote_dulwich.object_store.add_object(commit)
        remote_dulwich.refs[b"refs/heads/main"] = commit.id

        diverged_refs = _get_refs(remote)
        assert diverged_refs != original_refs

        # Backup again — should force-overwrite
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        final_refs = _get_refs(remote)
        local_refs = _get_refs(repo_with_data)
        assert final_refs == local_refs


class TestBackupAutoCreate:
    def test_backup_creates_nonexistent_destination(self, runner, repo_with_data, tmp_path):
        import os

        # Destination path that doesn't exist yet
        remote = str(tmp_path / "nonexistent.git")
        assert not os.path.exists(remote)

        # Backup should auto-create the destination and succeed
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Verify destination was created
        assert os.path.exists(remote)

        # Verify refs were synced correctly
        local_refs = _get_refs(repo_with_data)
        remote_refs = _get_refs(remote)
        assert local_refs == remote_refs
        assert any("refs/heads/main" in ref for ref in remote_refs)
        assert any("refs/tags/v1" in ref for ref in remote_refs)

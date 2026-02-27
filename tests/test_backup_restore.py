"""Tests for the vost backup/restore CLI commands."""

import pytest
from click.testing import CliRunner
from dulwich.repo import Repo as DulwichRepo

from vost.cli import main


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

    r = runner.invoke(main, ["tag", "--repo", p, "set", "v1"])
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
            "branch", "--repo", repo_with_data, "set", "feature",
        ])
        assert r.exit_code == 0, r.output
        refs_before = _get_refs(repo_with_data)

        # Dry-run restore: additive — local-only branch not deleted,
        # so already in sync
        r = runner.invoke(main, ["restore", "--repo", repo_with_data, "-n", remote])
        assert r.exit_code == 0, r.output
        assert "already in sync" in r.output

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


class TestRestoreIsAdditive:
    def test_local_only_branch_survives(self, runner, repo_with_data, tmp_path):
        """Restore is additive — local-only refs are NOT deleted."""
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Create a local-only branch
        r = runner.invoke(main, [
            "branch", "--repo", repo_with_data, "set", "local-only",
        ])
        assert r.exit_code == 0, r.output
        assert "refs/heads/local-only" in _get_refs(repo_with_data)

        # Restore — local-only branch should survive
        r = runner.invoke(main, ["restore", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        local_refs = _get_refs(repo_with_data)
        assert "refs/heads/local-only" in local_refs


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


# ---------------------------------------------------------------------------
# Bundle tests
# ---------------------------------------------------------------------------

class TestBundleExport:
    def test_backup_to_bundle(self, runner, repo_with_data, tmp_path):
        bundle = str(tmp_path / "backup.bundle")

        r = runner.invoke(main, ["backup", "--repo", repo_with_data, bundle])
        assert r.exit_code == 0, r.output

        import os
        assert os.path.exists(bundle)
        assert os.path.getsize(bundle) > 0

    def test_backup_to_bundle_dry_run(self, runner, repo_with_data, tmp_path):
        bundle = str(tmp_path / "backup.bundle")

        r = runner.invoke(main, ["backup", "--repo", repo_with_data, "-n", bundle])
        assert r.exit_code == 0, r.output
        assert "create" in r.output

        import os
        assert not os.path.exists(bundle)


class TestBundleImport:
    def test_restore_from_bundle(self, runner, repo_with_data, tmp_path):
        bundle = str(tmp_path / "backup.bundle")

        # Export to bundle
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, bundle])
        assert r.exit_code == 0, r.output
        original_refs = _get_refs(repo_with_data)

        # Create a new empty repo and restore into it
        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "main"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["restore", "--repo", dest, bundle])
        assert r.exit_code == 0, r.output

        dest_refs = _get_refs(dest)
        # All original refs should be present
        for ref in original_refs:
            assert ref in dest_refs
            assert dest_refs[ref] == original_refs[ref]

    def test_restore_from_bundle_dry_run(self, runner, repo_with_data, tmp_path):
        bundle = str(tmp_path / "backup.bundle")

        r = runner.invoke(main, ["backup", "--repo", repo_with_data, bundle])
        assert r.exit_code == 0, r.output

        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "tmp"])
        assert r.exit_code == 0, r.output
        refs_before = _get_refs(dest)

        r = runner.invoke(main, ["restore", "--repo", dest, "-n", bundle])
        assert r.exit_code == 0, r.output
        assert "create" in r.output

        # Dest should be unchanged
        refs_after = _get_refs(dest)
        assert refs_after == refs_before


class TestBundleRoundTrip:
    def test_backup_restore_roundtrip(self, runner, repo_with_data, tmp_path):
        bundle = str(tmp_path / "roundtrip.bundle")

        # Backup
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, bundle])
        assert r.exit_code == 0, r.output
        original_refs = _get_refs(repo_with_data)

        # Modify local: add a file
        newfile = tmp_path / "extra.txt"
        newfile.write_text("extra\n")
        r = runner.invoke(main, ["cp", "--repo", repo_with_data, str(newfile), ":extra.txt"])
        assert r.exit_code == 0, r.output
        assert _get_refs(repo_with_data) != original_refs

        # Restore from bundle — main should revert to original commit
        r = runner.invoke(main, ["restore", "--repo", repo_with_data, bundle])
        assert r.exit_code == 0, r.output

        restored_refs = _get_refs(repo_with_data)
        assert restored_refs["refs/heads/main"] == original_refs["refs/heads/main"]
        assert restored_refs["refs/tags/v1"] == original_refs["refs/tags/v1"]


class TestBundleWithRefs:
    def test_backup_with_ref_filter(self, runner, repo_with_data, tmp_path):
        """Backup with --ref only includes the specified refs."""
        bundle = str(tmp_path / "main-only.bundle")

        r = runner.invoke(main, [
            "backup", "--repo", repo_with_data,
            "--ref", "main", bundle,
        ])
        assert r.exit_code == 0, r.output

        # Import into a new repo — should only have main, not the tag
        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "tmp"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["restore", "--repo", dest, bundle])
        assert r.exit_code == 0, r.output

        dest_refs = _get_refs(dest)
        assert "refs/heads/main" in dest_refs
        assert "refs/tags/v1" not in dest_refs

    def test_restore_with_ref_filter(self, runner, repo_with_data, tmp_path):
        """Restore with --ref only imports the specified refs."""
        bundle = str(tmp_path / "full.bundle")

        r = runner.invoke(main, ["backup", "--repo", repo_with_data, bundle])
        assert r.exit_code == 0, r.output

        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "tmp"])
        assert r.exit_code == 0, r.output

        # Only restore the tag
        r = runner.invoke(main, [
            "restore", "--repo", dest, "--ref", "v1", bundle,
        ])
        assert r.exit_code == 0, r.output

        dest_refs = _get_refs(dest)
        assert "refs/tags/v1" in dest_refs
        # main from the bundle should NOT have been imported
        src_refs = _get_refs(repo_with_data)
        assert dest_refs.get("refs/heads/main") != src_refs["refs/heads/main"]

    def test_backup_multiple_refs(self, runner, repo_with_data, tmp_path):
        """Backup with multiple --ref flags."""
        bundle = str(tmp_path / "multi.bundle")

        r = runner.invoke(main, [
            "backup", "--repo", repo_with_data,
            "--ref", "main", "--ref", "v1", bundle,
        ])
        assert r.exit_code == 0, r.output

        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "tmp"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["restore", "--repo", dest, bundle])
        assert r.exit_code == 0, r.output

        dest_refs = _get_refs(dest)
        assert "refs/heads/main" in dest_refs
        assert "refs/tags/v1" in dest_refs


class TestBundleWithNotes:
    def test_notes_survive_bundle_roundtrip(self, runner, repo_with_data, tmp_path):
        # Set a note via CLI
        r = runner.invoke(main, [
            "note", "set", "--repo", repo_with_data, "my note text",
        ])
        assert r.exit_code == 0, r.output
        assert any(
            ref.startswith("refs/notes/") for ref in _get_refs(repo_with_data)
        )

        bundle = str(tmp_path / "notes.bundle")
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, bundle])
        assert r.exit_code == 0, r.output

        # Restore into a new repo
        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "main"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["restore", "--repo", dest, bundle])
        assert r.exit_code == 0, r.output

        dest_refs = _get_refs(dest)
        # Notes ref should exist
        assert any(ref.startswith("refs/notes/") for ref in dest_refs)


class TestBundleFormatOption:
    def test_format_flag_forces_bundle(self, runner, repo_with_data, tmp_path):
        """--format bundle forces bundle format even without .bundle extension."""
        outfile = str(tmp_path / "backup.dat")

        r = runner.invoke(main, [
            "backup", "--repo", repo_with_data, "--format", "bundle", outfile,
        ])
        assert r.exit_code == 0, r.output

        import os
        assert os.path.exists(outfile)

        # Should be importable as a bundle
        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "tmp"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, [
            "restore", "--repo", dest, "--format", "bundle", outfile,
        ])
        assert r.exit_code == 0, r.output

        src_refs = _get_refs(repo_with_data)
        dest_refs = _get_refs(dest)
        for ref in src_refs:
            assert ref in dest_refs


# ---------------------------------------------------------------------------
# Ref-scoped URL backup/restore tests
# ---------------------------------------------------------------------------

class TestBackupWithRefUrl:
    def test_backup_ref_to_remote(self, runner, repo_with_data, tmp_path):
        """Backup with --ref to a git repo only pushes specified refs."""
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        r = runner.invoke(main, [
            "backup", "--repo", repo_with_data,
            "--ref", "main", remote,
        ])
        assert r.exit_code == 0, r.output

        remote_refs = _get_refs(remote)
        assert "refs/heads/main" in remote_refs
        assert "refs/tags/v1" not in remote_refs

    def test_backup_ref_preserves_existing_remote_refs(
        self, runner, repo_with_data, tmp_path
    ):
        """--ref push doesn't delete existing remote refs."""
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Full backup first
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Add extra remote branch
        remote_dulwich = DulwichRepo(remote)
        main_sha = remote_dulwich.refs[b"refs/heads/main"]
        remote_dulwich.refs[b"refs/heads/extra"] = main_sha

        # Targeted backup — 'extra' should survive on remote
        r = runner.invoke(main, [
            "backup", "--repo", repo_with_data, "--ref", "main", remote,
        ])
        assert r.exit_code == 0, r.output

        remote_refs = _get_refs(remote)
        assert "refs/heads/extra" in remote_refs


class TestRestoreWithRefUrl:
    def test_restore_ref_from_remote(self, runner, repo_with_data, tmp_path):
        """Restore with --ref only pulls specified refs."""
        remote = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote, mkdir=True)

        # Backup everything to remote
        r = runner.invoke(main, ["backup", "--repo", repo_with_data, remote])
        assert r.exit_code == 0, r.output

        # Create empty dest
        dest = str(tmp_path / "dest.git")
        r = runner.invoke(main, ["init", "--repo", dest, "--branch", "tmp"])
        assert r.exit_code == 0, r.output

        # Restore only the tag
        r = runner.invoke(main, [
            "restore", "--repo", dest, "--ref", "v1", remote,
        ])
        assert r.exit_code == 0, r.output

        dest_refs = _get_refs(dest)
        assert "refs/tags/v1" in dest_refs

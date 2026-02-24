"""Tests for the GitStore backup/restore API (store.backup / store.restore)."""

import pytest
from dulwich.repo import Repo as DulwichRepo

from gitstore import GitStore, MirrorDiff, RefChange
from gitstore.mirror import _diff_refs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """A GitStore with a 'main' branch and one commit."""
    p = str(tmp_path / "src.git")
    s = GitStore.open(p)
    fs = s.branches["main"]
    with fs.batch(message="add hello") as b:
        b.write("hello.txt", b"hello world\n")
    return s


@pytest.fixture
def remote(tmp_path):
    """An empty bare dulwich repo suitable as a push/fetch target."""
    p = str(tmp_path / "remote.git")
    DulwichRepo.init_bare(p, mkdir=True)
    return p


def _get_refs(repo_path):
    """Return {ref_str: sha_str} excluding HEAD."""
    repo = DulwichRepo(repo_path)
    return {
        ref.decode(): sha.decode()
        for ref, sha in repo.get_refs().items()
        if ref != b"HEAD"
    }


# ---------------------------------------------------------------------------
# TestBackupAPI
# ---------------------------------------------------------------------------

class TestBackupAPI:
    def test_backup_returns_sync_diff(self, store, remote):
        diff = store.backup(remote)
        assert isinstance(diff, MirrorDiff)
        assert len(diff.add) > 0
        assert diff.total > 0

    def test_dry_run_does_not_modify_remote(self, store, remote):
        diff = store.backup(remote, dry_run=True)
        assert diff.total > 0
        # Remote should still be empty
        assert _get_refs(remote) == {}

    def test_backup_mirrors_refs(self, store, remote):
        store.backup(remote)
        local = _get_refs(store._repo.path.rstrip("/"))
        assert local == _get_refs(remote)

    def test_backup_then_in_sync(self, store, remote):
        store.backup(remote)
        diff = store.backup(remote, dry_run=True)
        assert diff.in_sync

    def test_backup_with_tag(self, store, remote):
        # Create a tag
        fs = store.branches["main"]
        store.tags["v1"] = fs
        store.backup(remote)
        remote_refs = _get_refs(remote)
        assert any("refs/tags/v1" in r for r in remote_refs)


# ---------------------------------------------------------------------------
# TestRestoreAPI
# ---------------------------------------------------------------------------

class TestRestoreAPI:
    def test_restore_returns_sync_diff(self, store, remote):
        store.backup(remote)
        # Modify local
        fs = store.branches["main"]
        with fs.batch(message="add new") as b:
            b.write("new.txt", b"new\n")
        diff = store.restore(remote)
        assert isinstance(diff, MirrorDiff)

    def test_dry_run_does_not_modify_local(self, store, remote):
        store.backup(remote)
        fs = store.branches["main"]
        with fs.batch(message="add new") as b:
            b.write("new.txt", b"new\n")
        refs_before = _get_refs(store._repo.path.rstrip("/"))
        diff = store.restore(remote, dry_run=True)
        assert diff.total > 0
        refs_after = _get_refs(store._repo.path.rstrip("/"))
        assert refs_after == refs_before

    def test_restore_reverts_changes(self, store, remote):
        store.backup(remote)
        original = _get_refs(store._repo.path.rstrip("/"))
        # Modify local
        fs = store.branches["main"]
        with fs.batch(message="add new") as b:
            b.write("new.txt", b"new\n")
        store.restore(remote)
        assert _get_refs(store._repo.path.rstrip("/")) == original


# ---------------------------------------------------------------------------
# TestMirrorDiffStructure
# ---------------------------------------------------------------------------

class TestMirrorDiffStructure:
    def test_empty_diff_is_in_sync(self):
        diff = MirrorDiff()
        assert diff.in_sync
        assert diff.total == 0

    def test_ref_change_fields(self):
        c = RefChange(ref="refs/heads/main", old_target="abc1234", new_target=None)
        assert c.ref == "refs/heads/main"
        assert c.old_target == "abc1234"
        assert c.new_target is None

    def test_total_counts_all_categories(self):
        diff = MirrorDiff(
            add=[RefChange(ref="a", new_target="1")],
            update=[RefChange(ref="b", old_target="3", new_target="2")],
            delete=[RefChange(ref="c", old_target="4"), RefChange(ref="d", old_target="5")],
        )
        assert diff.total == 4
        assert not diff.in_sync


class TestScpStyleUrl:
    def test_scp_style_with_user_raises(self, store):
        with pytest.raises(ValueError, match="scp-style URL not supported"):
            _diff_refs(store._repo._drepo,"git@github.com:org/repo.git", "push")

    def test_scp_style_without_user_raises(self, store):
        """host:path (no @) is also scp-style and must be rejected."""
        with pytest.raises(ValueError, match="scp-style URL not supported"):
            _diff_refs(store._repo._drepo,"github.com:org/repo.git", "push")

    def test_scp_style_suggests_ssh(self, store):
        with pytest.raises(ValueError, match="ssh:// format"):
            _diff_refs(store._repo._drepo,"git@github.com:org/repo.git", "pull")

    def test_ssh_url_not_rejected(self, store):
        """ssh:// URLs should not be caught by scp detection."""
        # Will fail at the network level, but must not be the scp guard
        try:
            _diff_refs(store._repo._drepo,"ssh://git@github.com/org/repo.git", "pull")
        except ValueError as exc:
            assert "scp-style" not in str(exc), f"scp guard fired on ssh:// URL: {exc}"
        except Exception:
            pass  # network error is expected

    def test_file_url_not_rejected(self, store, tmp_path):
        """file:// URLs should not be caught by scp detection."""
        target = str(tmp_path / "remote.git")
        # Should not raise ValueError — will auto-create for push
        _diff_refs(store._repo._drepo,f"file://{target}", "push")

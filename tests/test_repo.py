"""Tests for GitStore class and RefDict."""

import pytest

from gitstore import GitStore


class TestGitStoreOpen:
    def test_create_with_branch(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        assert "main" in repo.branches

    def test_create_bare_no_branch(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create=True)
        assert len(repo.branches) == 0

    def test_create_already_exists(self, tmp_path):
        GitStore.open(tmp_path / "test.git", create=True)
        with pytest.raises(FileExistsError):
            GitStore.open(tmp_path / "test.git", create=True)

    def test_open_existing(self, tmp_path):
        GitStore.open(tmp_path / "test.git", create="main")
        repo = GitStore.open(tmp_path / "test.git")
        assert "main" in repo.branches

    def test_open_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            GitStore.open(tmp_path / "nope.git")

    def test_author_email(self, tmp_path):
        repo = GitStore.open(
            tmp_path / "test.git",
            create="main",
            author="alice",
            email="a@b.com",
        )
        fs = repo.branches["main"]
        assert repo._signature.name == "alice"
        assert repo._signature.email == "a@b.com"


class TestRefDictBranches:
    def test_get(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        assert fs.branch == "main"

    def test_get_missing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        with pytest.raises(KeyError):
            repo.branches["nope"]

    def test_contains(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        assert "main" in repo.branches
        assert "nope" not in repo.branches

    def test_iter(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        assert list(repo.branches) == ["main"]

    def test_len(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        assert len(repo.branches) == 1

    def test_fork(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.branches["exp"] = fs
        assert "exp" in repo.branches
        assert repo.branches["exp"].hash == fs.hash

    def test_del(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        repo.branches["exp"] = repo.branches["main"]
        del repo.branches["exp"]
        assert "exp" not in repo.branches

    def test_del_missing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        with pytest.raises(KeyError):
            del repo.branches["nope"]


class TestRefDictTags:
    def test_tag_and_get(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        assert tag_fs.hash == fs.hash
        assert tag_fs.branch is None  # read-only

    def test_tag_missing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        with pytest.raises(KeyError):
            repo.tags["nope"]

    def test_del_tag(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        repo.tags["v1"] = repo.branches["main"]
        del repo.tags["v1"]
        assert "v1" not in repo.tags

    def test_iter_tags(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        repo.tags["v1"] = repo.branches["main"]
        repo.tags["v2"] = repo.branches["main"]
        assert sorted(repo.tags) == ["v1", "v2"]

    def test_tag_overwrite_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        with pytest.raises(KeyError):
            repo.tags["v1"] = fs

    def test_invalid_type_in_setitem(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        with pytest.raises(TypeError):
            repo.branches["x"] = "string"

    def test_cross_repo_assign_raises(self, tmp_path):
        repo_a = GitStore.open(tmp_path / "a.git", create="main")
        repo_b = GitStore.open(tmp_path / "b.git", create="main")
        fs_a = repo_a.branches["main"]
        with pytest.raises(ValueError):
            repo_b.branches["imported"] = fs_a

    def test_create_false_raises(self, tmp_path):
        with pytest.raises(ValueError):
            GitStore.open(tmp_path / "test.git", create=False)

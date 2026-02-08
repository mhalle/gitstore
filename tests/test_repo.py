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

    def test_same_path_assign_allowed(self, tmp_path):
        repo_a = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo_a.branches["main"]
        repo_b = GitStore.open(tmp_path / "test.git")
        repo_b.tags["v1"] = fs  # same repo path, different instance — should work
        assert "v1" in repo_b.tags

    def test_symlink_path_assign_allowed(self, tmp_path):
        repo_a = GitStore.open(tmp_path / "real.git", create="main")
        fs = repo_a.branches["main"]
        link = tmp_path / "link.git"
        try:
            link.symlink_to(tmp_path / "real.git")
        except OSError:
            pytest.skip("symlink not supported")
        repo_b = GitStore.open(link)
        repo_b.tags["v1"] = fs  # symlink to same repo — should work
        assert "v1" in repo_b.tags

    def test_create_false_raises(self, tmp_path):
        with pytest.raises(ValueError):
            GitStore.open(tmp_path / "test.git", create=False)

    def test_annotated_tag(self, tmp_path):
        import pygit2
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        # Create an annotated tag via pygit2
        raw = repo._repo
        raw.create_tag(
            "v-annotated",
            fs._commit_oid,
            pygit2.GIT_OBJECT_COMMIT,
            raw.default_signature,
            "release tag",
        )
        tag_fs = repo.tags["v-annotated"]
        assert tag_fs.hash == fs.hash
        assert tag_fs.branch is None


class TestBranchKeyword:
    def test_create_with_branch_kwarg(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create=True, branch="main")
        assert "main" in repo.branches

    def test_branch_without_create_raises(self, tmp_path):
        with pytest.raises(ValueError):
            GitStore.open(tmp_path / "test.git", branch="main")

    def test_branch_and_create_str_raises(self, tmp_path):
        with pytest.raises(ValueError):
            GitStore.open(tmp_path / "test.git", create="main", branch="dev")


class TestRefDictMapping:
    def test_get_existing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches.get("main")
        assert fs is not None
        assert fs.branch == "main"

    def test_get_missing_default(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        assert repo.branches.get("nope") is None
        assert repo.branches.get("nope", 42) == 42

    def test_keys(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        assert list(repo.branches.keys()) == ["main"]

    def test_values(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        vals = list(repo.branches.values())
        assert len(vals) == 1
        assert vals[0].branch == "main"

    def test_items(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        items = list(repo.branches.items())
        assert len(items) == 1
        assert items[0][0] == "main"
        assert items[0][1].branch == "main"

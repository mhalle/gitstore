"""Tests for GitStore class and RefDict."""

import pytest

from gitstore import GitStore
from gitstore.repo import _Repository


class TestGitStoreOpen:
    def test_create_with_branch(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert "main" in repo.branches

    def test_create_with_custom_branch(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", branch="dev")
        assert "dev" in repo.branches

    def test_create_bare_no_branch(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", branch=None)
        assert len(repo.branches) == 0

    def test_open_existing(self, tmp_path):
        GitStore.open(tmp_path / "test.git")
        repo = GitStore.open(tmp_path / "test.git", create=False)
        assert "main" in repo.branches

    def test_open_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            GitStore.open(tmp_path / "nope.git", create=False)

    def test_idempotent(self, tmp_path):
        repo1 = GitStore.open(tmp_path / "test.git")
        repo2 = GitStore.open(tmp_path / "test.git")
        assert "main" in repo2.branches

    def test_author_email(self, tmp_path):
        repo = GitStore.open(
            tmp_path / "test.git",
            author="alice",
            email="a@b.com",
        )
        fs = repo.branches["main"]
        assert repo._signature.name == "alice"
        assert repo._signature.email == "a@b.com"


class TestRefDictBranches:
    def test_get(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        assert fs.branch == "main"

    def test_get_missing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        with pytest.raises(KeyError):
            repo.branches["nope"]

    def test_contains(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert "main" in repo.branches
        assert "nope" not in repo.branches

    def test_iter(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert list(repo.branches) == ["main"]

    def test_len(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert len(repo.branches) == 1

    def test_fork(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        repo.branches["exp"] = fs
        assert "exp" in repo.branches
        assert repo.branches["exp"].commit_hash == fs.commit_hash

    def test_del(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        repo.branches["exp"] = repo.branches["main"]
        del repo.branches["exp"]
        assert "exp" not in repo.branches

    def test_del_missing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        with pytest.raises(KeyError):
            del repo.branches["nope"]


class TestRefDictTags:
    def test_tag_and_get(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        tag_fs = repo.tags["v1"]
        assert tag_fs.commit_hash == fs.commit_hash
        assert tag_fs.branch is None  # read-only

    def test_tag_missing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        with pytest.raises(KeyError):
            repo.tags["nope"]

    def test_del_tag(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        repo.tags["v1"] = repo.branches["main"]
        del repo.tags["v1"]
        assert "v1" not in repo.tags

    def test_iter_tags(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        repo.tags["v1"] = repo.branches["main"]
        repo.tags["v2"] = repo.branches["main"]
        assert sorted(repo.tags) == ["v1", "v2"]

    def test_tag_overwrite_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        repo.tags["v1"] = fs
        with pytest.raises(KeyError):
            repo.tags["v1"] = fs

    def test_invalid_type_in_setitem(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        with pytest.raises(TypeError):
            repo.branches["x"] = "string"

    def test_cross_repo_assign_raises(self, tmp_path):
        repo_a = GitStore.open(tmp_path / "a.git")
        repo_b = GitStore.open(tmp_path / "b.git")
        fs_a = repo_a.branches["main"]
        with pytest.raises(ValueError):
            repo_b.branches["imported"] = fs_a

    def test_same_path_assign_allowed(self, tmp_path):
        repo_a = GitStore.open(tmp_path / "test.git")
        fs = repo_a.branches["main"]
        repo_b = GitStore.open(tmp_path / "test.git", create=False)
        repo_b.tags["v1"] = fs  # same repo path, different instance — should work
        assert "v1" in repo_b.tags

    def test_symlink_path_assign_allowed(self, tmp_path):
        repo_a = GitStore.open(tmp_path / "real.git")
        fs = repo_a.branches["main"]
        link = tmp_path / "link.git"
        try:
            link.symlink_to(tmp_path / "real.git")
        except OSError:
            pytest.skip("symlink not supported")
        repo_b = GitStore.open(link, create=False)
        repo_b.tags["v1"] = fs  # symlink to same repo — should work
        assert "v1" in repo_b.tags

    def test_path_trailing_slash_on_directory(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert repo._repo.path.endswith("/")

    def test_path_no_trailing_slash_on_file(self, tmp_path):
        """Non-directory path (e.g. SQLite) must not get a trailing slash."""
        fake_file = tmp_path / "repo.sqlite"
        fake_file.write_bytes(b"")

        class _FakeRepo:
            path = str(fake_file)

        r = _Repository(_FakeRepo())
        assert not r.path.endswith("/")
        assert r.path == str(fake_file)

    def test_create_false_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            GitStore.open(tmp_path / "test.git", create=False)

    def test_non_commit_tag_raises(self, tmp_path):
        """A tag pointing to a non-commit object should raise ValueError."""
        repo = GitStore.open(tmp_path / "test.git")
        # Create a lightweight tag pointing directly to a tree (not a commit)
        fs = repo.branches["main"]
        raw = repo._repo
        raw.references.create("refs/tags/bad", fs._tree_oid)
        with pytest.raises(ValueError, match="does not point to a commit"):
            repo.tags["bad"]

    def test_annotated_tag(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        # Create an annotated tag via compat layer
        raw = repo._repo
        raw.create_tag(
            "v-annotated",
            fs._commit_oid,
            1,  # GIT_OBJECT_COMMIT
            repo._signature,
            "release tag",
        )
        tag_fs = repo.tags["v-annotated"]
        assert tag_fs.commit_hash == fs.commit_hash
        assert tag_fs.branch is None


class TestRefDictMapping:
    def test_get_existing(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches.get("main")
        assert fs is not None
        assert fs.branch == "main"

    def test_get_missing_default(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert repo.branches.get("nope") is None
        assert repo.branches.get("nope", 42) == 42

    def test_keys(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert list(repo.branches.keys()) == ["main"]

    def test_values(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        vals = list(repo.branches.values())
        assert len(vals) == 1
        assert vals[0].branch == "main"

    def test_items(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        items = list(repo.branches.items())
        assert len(items) == 1
        assert items[0][0] == "main"
        assert items[0][1].branch == "main"


class TestRefDictDefault:
    def test_default_read(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        assert repo.branches.default == "main"

    def test_default_custom(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", branch="data")
        assert repo.branches.default == "data"

    def test_default_set(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        repo.branches["dev"] = fs
        repo.branches.default = "dev"
        assert repo.branches.default == "dev"

    def test_default_set_nonexistent(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        with pytest.raises(KeyError):
            repo.branches.default = "nope"

    def test_default_dangling(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", branch=None)
        assert repo.branches.default is None

    def test_default_on_tags_raises(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        with pytest.raises(ValueError):
            repo.tags.default

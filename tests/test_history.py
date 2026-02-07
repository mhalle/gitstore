"""Tests for FS history (parent, log)."""

import pytest

from gitstore import GitStore


@pytest.fixture
def repo_with_history(tmp_path):
    repo = GitStore.open(tmp_path / "test.git", create="main")
    fs = repo.branches["main"]  # init commit
    fs = fs.write("a.txt", b"a")
    fs = fs.write("b.txt", b"b")
    return repo, fs


class TestParent:
    def test_root_parent_is_none(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        assert fs.parent is None

    def test_parent_chain(self, repo_with_history):
        _, fs = repo_with_history
        # fs is 3rd commit (init, write a, write b)
        p1 = fs.parent
        assert p1 is not None
        assert "a.txt" in p1.message

        p2 = p1.parent
        assert p2 is not None
        assert "Initialize" in p2.message

        assert p2.parent is None


class TestLog:
    def test_log_length(self, repo_with_history):
        _, fs = repo_with_history
        commits = list(fs.log())
        assert len(commits) == 3  # init + 2 writes

    def test_log_order(self, repo_with_history):
        _, fs = repo_with_history
        commits = list(fs.log())
        # Most recent first
        assert "b.txt" in commits[0].message
        assert "a.txt" in commits[1].message
        assert "Initialize" in commits[2].message

    def test_log_each_is_fs(self, repo_with_history):
        _, fs = repo_with_history
        for entry in fs.log():
            assert hasattr(entry, "hash")
            assert hasattr(entry, "read")

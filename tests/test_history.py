"""Tests for FS history (parent, log)."""

from datetime import datetime, timezone

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

    def test_log_no_args_unchanged(self, repo_with_history):
        _, fs = repo_with_history
        commits = list(fs.log())
        assert len(commits) == 3

    def test_log_with_path(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a1")
        fs = fs.write("b.txt", b"b1")
        fs = fs.write("a.txt", b"a2")
        commits = list(fs.log("a.txt"))
        assert len(commits) == 2
        assert "a.txt" in commits[0].message
        assert "a.txt" in commits[1].message

    def test_log_path_added_and_removed(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        fs = fs.write("x.txt", b"data")
        fs = fs.remove("x.txt")
        commits = list(fs.log("x.txt"))
        assert len(commits) == 2

    def test_log_path_no_matches(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a")
        commits = list(fs.log("nonexistent"))
        assert commits == []


class TestCommitMetadata:
    def test_time_is_datetime(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        assert isinstance(fs.time, datetime)
        assert fs.time.tzinfo is not None

    def test_author_name(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main", author="alice")
        fs = repo.branches["main"]
        assert fs.author_name == "alice"

    def test_author_email(self, tmp_path):
        repo = GitStore.open(
            tmp_path / "test.git", create="main", email="alice@example.com"
        )
        fs = repo.branches["main"]
        assert fs.author_email == "alice@example.com"

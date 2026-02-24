"""Tests for FS history (parent, log)."""

from datetime import datetime, timezone

import pytest

from gitstore import GitStore


@pytest.fixture
def repo_with_history(tmp_path):
    repo = GitStore.open(tmp_path / "test.git")
    fs = repo.branches["main"]  # init commit
    fs = fs.write("a.txt", b"a")
    fs = fs.write("b.txt", b"b")
    return repo, fs


class TestParent:
    def test_root_parent_is_none(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
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


class TestBack:
    def test_back_zero(self, repo_with_history):
        _, fs = repo_with_history
        assert fs.back(0).commit_hash == fs.commit_hash

    def test_back_one(self, repo_with_history):
        _, fs = repo_with_history
        assert fs.back(1).commit_hash == fs.parent.commit_hash

    def test_back_n(self, repo_with_history):
        _, fs = repo_with_history
        assert fs.back(2).commit_hash == fs.parent.parent.commit_hash

    def test_back_too_far(self, repo_with_history):
        _, fs = repo_with_history
        with pytest.raises(ValueError, match="history too short"):
            fs.back(100)

    def test_back_negative(self, repo_with_history):
        _, fs = repo_with_history
        with pytest.raises(ValueError, match="n >= 0"):
            fs.back(-1)


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
            assert hasattr(entry, "commit_hash")
            assert hasattr(entry, "read")

    def test_log_no_args_unchanged(self, repo_with_history):
        _, fs = repo_with_history
        commits = list(fs.log())
        assert len(commits) == 3

    def test_log_with_path(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a1")
        fs = fs.write("b.txt", b"b1")
        fs = fs.write("a.txt", b"a2")
        commits = list(fs.log("a.txt"))
        assert len(commits) == 2
        assert "a.txt" in commits[0].message
        assert "a.txt" in commits[1].message

    def test_log_path_added_and_removed(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("x.txt", b"data")
        fs = fs.remove("x.txt")
        commits = list(fs.log("x.txt"))
        assert len(commits) == 2

    def test_log_path_no_matches(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a")
        commits = list(fs.log("nonexistent"))
        assert commits == []

    def test_log_at_kwarg(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a1")
        fs = fs.write("b.txt", b"b1")
        fs = fs.write("a.txt", b"a2")
        commits = list(fs.log(path="a.txt"))
        assert len(commits) == 2

    def test_log_match(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        # write() auto-generates "+ <path>" messages (new format)
        fs = fs.write("deploy-v1.txt", b"a")   # "+ deploy-v1.txt"
        fs = fs.write("fixbug.txt", b"b")       # "+ fixbug.txt"
        fs = fs.write("deploy-v2.txt", b"c")   # "+ deploy-v2.txt"
        commits = list(fs.log(match="+ deploy*"))
        assert len(commits) == 2
        assert all("deploy" in c.message for c in commits)

    def test_log_match_no_results(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a")
        commits = list(fs.log(match="zzz*"))
        assert commits == []

    def test_log_at_and_match(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a")    # "Write a.txt"
        fs = fs.write("b.txt", b"b")    # "Write b.txt"
        fs = fs.write("a.txt", b"a2")   # "Write a.txt"
        # at="a.txt" gives 2 commits, match narrows to the one with "b" not in message
        # Actually both a.txt commits have "Write a.txt" — let's use a different approach
        # Use at + match where match filters out the Initialize commit
        commits_at = list(fs.log(path="a.txt"))
        assert len(commits_at) == 2
        commits_both = list(fs.log(path="a.txt", match="*a.txt"))
        assert len(commits_both) == 2
        # Now filter for something that won't match
        commits_none = list(fs.log(path="a.txt", match="*b.txt"))
        assert len(commits_none) == 0


class TestLogNaiveDatetime:
    """Fix 2: log(before=...) accepts naive datetimes without TypeError."""

    def test_naive_datetime_before(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a")
        # Naive datetime (no tzinfo) — should work, not raise TypeError
        future = datetime(2099, 1, 1)
        commits = list(fs.log(before=future))
        assert len(commits) == 2  # init + write

    def test_naive_datetime_past(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a")
        # Naive datetime in the past — should filter out all commits
        past = datetime(2000, 1, 1)
        commits = list(fs.log(before=past))
        assert len(commits) == 0

    def test_aware_datetime_still_works(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"a")
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        commits = list(fs.log(before=future))
        assert len(commits) == 2


class TestCommitMetadata:
    def test_time_is_datetime(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        assert isinstance(fs.time, datetime)
        assert fs.time.tzinfo is not None

    def test_author_name(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", author="alice")
        fs = repo.branches["main"]
        assert fs.author_name == "alice"

    def test_author_email(self, tmp_path):
        repo = GitStore.open(
            tmp_path / "test.git", email="alice@example.com"
        )
        fs = repo.branches["main"]
        assert fs.author_email == "alice@example.com"

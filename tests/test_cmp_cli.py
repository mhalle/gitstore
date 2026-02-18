"""Tests for the gitstore cmp CLI command."""

import os
import pytest
from click.testing import CliRunner

from gitstore.cli import main
from gitstore.repo import GitStore


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def repo_path(tmp_path):
    return str(tmp_path / "test.git")


@pytest.fixture
def repo(tmp_path):
    """Create a repo with two files (same + different content) and return (repo_path, tmp_path)."""
    p = str(tmp_path / "test.git")
    store = GitStore.open(p, branch="main")
    fs = store.branches["main"]
    fs = fs.write("file_a.txt", b"hello world\n")
    fs = fs.write("file_b.txt", b"hello world\n")  # same content as a
    fs.write("file_c.txt", b"different content\n")  # different
    return p, tmp_path


# ---------------------------------------------------------------------------
# TestCmpRepoRepo
# ---------------------------------------------------------------------------

class TestCmpRepoRepo:
    def test_same_content_exit_0(self, runner, repo):
        rp, _ = repo
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", ":file_b.txt"])
        assert result.exit_code == 0

    def test_different_content_exit_1(self, runner, repo):
        rp, _ = repo
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", ":file_c.txt"])
        assert result.exit_code == 1

    def test_same_file_exit_0(self, runner, repo):
        rp, _ = repo
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", ":file_a.txt"])
        assert result.exit_code == 0

    def test_cross_branch(self, runner, repo):
        rp, _ = repo
        # Create a dev branch with different content for file_a.txt
        store = GitStore.open(rp, create=False)
        store.branches["dev"] = store.branches["main"]
        fs = store.branches["dev"]
        fs.write("file_a.txt", b"changed on dev\n")

        # Same file, different branches → different
        result = runner.invoke(main, ["cmp", "--repo", rp, "main:file_a.txt", "dev:file_a.txt"])
        assert result.exit_code == 1

        # file_b on main == file_a on main (same content)
        result = runner.invoke(main, ["cmp", "--repo", rp, "main:file_a.txt", "main:file_b.txt"])
        assert result.exit_code == 0

    def test_ancestor_syntax(self, runner, repo):
        rp, _ = repo
        # Write a second version of file_a
        store = GitStore.open(rp, create=False)
        fs = store.branches["main"]
        fs.write("file_a.txt", b"updated content\n")

        # Current vs one-back should differ
        result = runner.invoke(main, ["cmp", "--repo", rp, "main~1:file_a.txt", "main:file_a.txt"])
        assert result.exit_code == 1

        # file_b unchanged — current should equal one-back
        result = runner.invoke(main, ["cmp", "--repo", rp, "main~1:file_b.txt", "main:file_b.txt"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestCmpRepoLocal
# ---------------------------------------------------------------------------

class TestCmpRepoLocal:
    def test_same_content(self, runner, repo):
        rp, tmp = repo
        local = tmp / "local.txt"
        local.write_bytes(b"hello world\n")
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", str(local)])
        assert result.exit_code == 0

    def test_different_content(self, runner, repo):
        rp, tmp = repo
        local = tmp / "local.txt"
        local.write_bytes(b"something else\n")
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", str(local)])
        assert result.exit_code == 1

    def test_local_first_repo_second(self, runner, repo):
        rp, tmp = repo
        local = tmp / "local.txt"
        local.write_bytes(b"hello world\n")
        result = runner.invoke(main, ["cmp", "--repo", rp, str(local), ":file_a.txt"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestCmpLocalLocal
# ---------------------------------------------------------------------------

class TestCmpLocalLocal:
    def test_same_content(self, runner, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"same data\n")
        b.write_bytes(b"same data\n")
        # No --repo needed for local-only compare, but we still need a repo
        # because of the command group structure. Actually, let's verify
        # that local-only works without a repo at all.
        result = runner.invoke(main, ["cmp", str(a), str(b)])
        assert result.exit_code == 0

    def test_different_content(self, runner, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"data 1\n")
        b.write_bytes(b"data 2\n")
        result = runner.invoke(main, ["cmp", str(a), str(b)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# TestCmpVerbose
# ---------------------------------------------------------------------------

class TestCmpVerbose:
    def test_verbose_prints_hashes_to_stderr(self, runner, repo):
        rp, _ = repo
        result = runner.invoke(main, ["-v", "cmp", "--repo", rp,
                                      ":file_a.txt", ":file_c.txt"])
        assert result.exit_code == 1
        # Verbose output goes to stderr — CliRunner captures stderr in output
        # when mix_stderr=True (the default)
        assert "file_a.txt" in result.output
        assert "file_c.txt" in result.output
        # Should contain 40-char hex hashes
        lines = [l for l in result.output.strip().splitlines() if "file_" in l]
        assert len(lines) == 2
        for line in lines:
            h = line.split()[0]
            assert len(h) == 40
            int(h, 16)  # valid hex

    def test_verbose_same_files(self, runner, repo):
        rp, _ = repo
        result = runner.invoke(main, ["-v", "cmp", "--repo", rp,
                                      ":file_a.txt", ":file_b.txt"])
        assert result.exit_code == 0
        lines = [l for l in result.output.strip().splitlines() if "file_" in l]
        assert len(lines) == 2
        h1 = lines[0].split()[0]
        h2 = lines[1].split()[0]
        assert h1 == h2


# ---------------------------------------------------------------------------
# TestCmpErrors
# ---------------------------------------------------------------------------

class TestCmpErrors:
    def test_missing_repo_file(self, runner, repo):
        rp, _ = repo
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", ":nonexistent.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_local_file(self, runner, repo):
        rp, _ = repo
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", "/tmp/no_such_file_xyz.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_directory_arg_local(self, runner, repo, tmp_path):
        rp, _ = repo
        d = tmp_path / "mydir"
        d.mkdir()
        result = runner.invoke(main, ["cmp", "--repo", rp, ":file_a.txt", str(d)])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()


# ---------------------------------------------------------------------------
# TestCmpSnapshotFilters
# ---------------------------------------------------------------------------

class TestCmpSnapshotFilters:
    def test_back_filter(self, runner, repo):
        rp, _ = repo
        # Write a second version
        store = GitStore.open(rp, create=False)
        fs = store.branches["main"]
        fs.write("file_a.txt", b"v2 content\n")

        # --back 1 should get original content, which matches file_b
        result = runner.invoke(main, ["cmp", "--repo", rp,
                                      ":file_a.txt", ":file_b.txt", "--back", "1"])
        assert result.exit_code == 0

        # Without --back, file_a is now different from file_b
        result = runner.invoke(main, ["cmp", "--repo", rp,
                                      ":file_a.txt", ":file_b.txt"])
        assert result.exit_code == 1

    def test_ref_filter(self, runner, repo):
        rp, _ = repo
        # Create a tag
        store = GitStore.open(rp, create=False)
        store.tags["v1"] = store.branches["main"]
        # Modify main
        fs = store.branches["main"]
        fs.write("file_a.txt", b"post-tag content\n")

        # --ref v1 should get original content
        result = runner.invoke(main, ["cmp", "--repo", rp,
                                      ":file_a.txt", ":file_b.txt", "--ref", "v1"])
        assert result.exit_code == 0

"""Tests for HEAD / default-branch management."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from gitstore.cli import main
from gitstore.repo import GitStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# _compat helpers
# ---------------------------------------------------------------------------

class TestGetSetHeadBranch:
    def test_new_repo_head_matches_branch(self, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="data")
        assert store._repo.get_head_branch() == "data"

    def test_new_repo_default_main(self, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="main")
        assert store._repo.get_head_branch() == "main"

    def test_get_head_branch_dangling(self, tmp_path):
        """A repo whose HEAD points to a non-existent branch returns None."""
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="main")
        # Point HEAD at a branch that doesn't exist
        store._repo.set_head_branch("nonexistent")
        assert store._repo.get_head_branch() is None

    def test_set_head_branch(self, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="main")
        # Create a second branch
        store.branches["dev"] = store.branches["main"]
        store._repo.set_head_branch("dev")
        assert store._repo.get_head_branch() == "dev"

    def test_bare_repo_no_branch(self, tmp_path):
        """A repo created with branch=None has dangling HEAD."""
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch=None)
        # dulwich default HEAD -> refs/heads/master, which doesn't exist
        assert store._repo.get_head_branch() is None


# ---------------------------------------------------------------------------
# CLI: branch default
# ---------------------------------------------------------------------------

class TestBranchDefault:
    def test_read_default(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        GitStore.open(p, branch="main")
        result = runner.invoke(main, ["branch", "default", "-r", p])
        assert result.exit_code == 0
        assert result.output.strip() == "main"

    def test_read_custom_default(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        GitStore.open(p, branch="data")
        result = runner.invoke(main, ["branch", "default", "-r", p])
        assert result.exit_code == 0
        assert result.output.strip() == "data"

    def test_set_default(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="main")
        store.branches["dev"] = store.branches["main"]
        result = runner.invoke(main, ["branch", "default", "-r", p, "-b", "dev"])
        assert result.exit_code == 0
        # Verify it was set
        result = runner.invoke(main, ["branch", "default", "-r", p])
        assert result.output.strip() == "dev"

    def test_set_nonexistent(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        GitStore.open(p, branch="main")
        result = runner.invoke(main, ["branch", "default", "-r", p, "-b", "nope"])
        assert result.exit_code != 0
        assert "Branch not found" in result.output

    def test_read_dangling(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch=None)
        result = runner.invoke(main, ["branch", "default", "-r", p])
        assert result.exit_code != 0
        assert "HEAD does not point" in result.output


# ---------------------------------------------------------------------------
# CLI: commands use HEAD default
# ---------------------------------------------------------------------------

class TestCLIUsesHeadDefault:
    def test_ls_uses_head(self, runner, tmp_path):
        """ls without -b uses the repo's default branch (set via HEAD)."""
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="data")
        fs = store.branches["data"]
        fs.write("hello.txt", b"hi")
        # ls without -b should use "data" (from HEAD)
        result = runner.invoke(main, ["ls", "-r", p])
        assert result.exit_code == 0
        assert "hello.txt" in result.output

    def test_cat_uses_head(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="data")
        fs = store.branches["data"]
        fs.write("hello.txt", b"content here")
        result = runner.invoke(main, ["cat", "-r", p, ":hello.txt"])
        assert result.exit_code == 0
        assert "content here" in result.output

    def test_log_uses_head(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="data")
        fs = store.branches["data"]
        fs.write("hello.txt", b"hi")
        result = runner.invoke(main, ["log", "-r", p])
        assert result.exit_code == 0
        # Should show at least the init commit
        assert "Initialize data" in result.output or "hello.txt" in result.output

    def test_write_uses_head(self, runner, tmp_path):
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="data")
        result = runner.invoke(main, ["write", "-r", p, ":newfile.txt"],
                               input="new content")
        assert result.exit_code == 0
        # Verify it went to "data" branch
        store2 = GitStore.open(p, create=False)
        fs = store2.branches["data"]
        assert fs.read("newfile.txt") == b"new content"

    def test_branch_set_uses_head(self, runner, tmp_path):
        """branch set without --ref uses the default branch."""
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="data")
        fs = store.branches["data"]
        fs.write("hello.txt", b"hi")
        result = runner.invoke(main, ["branch", "set", "copy", "-r", p])
        assert result.exit_code == 0
        store2 = GitStore.open(p, create=False)
        assert "copy" in store2.branches
        assert store2.branches["copy"].read("hello.txt") == b"hi"

    def test_tag_set_uses_head(self, runner, tmp_path):
        """tag set without --ref uses the default branch."""
        p = str(tmp_path / "test.git")
        store = GitStore.open(p, branch="data")
        fs = store.branches["data"]
        fs.write("hello.txt", b"hi")
        result = runner.invoke(main, ["tag", "set", "v1", "-r", p])
        assert result.exit_code == 0
        store2 = GitStore.open(p, create=False)
        assert "v1" in store2.tags

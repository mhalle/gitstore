"""Tests for the gitstore CLI."""

import pytest
from click.testing import CliRunner

from gitstore.cli import main


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
def initialized_repo(tmp_path, runner):
    """Create a repo with a 'main' branch and return its path."""
    p = str(tmp_path / "test.git")
    result = runner.invoke(main, [p, "init", "--branch", "main"])
    assert result.exit_code == 0, result.output
    return p


@pytest.fixture
def repo_with_files(tmp_path, runner):
    """Repo with hello.txt and data/data.bin on 'main'."""
    p = str(tmp_path / "test.git")
    r = runner.invoke(main, [p, "init", "--branch", "main"])
    assert r.exit_code == 0, r.output

    hello = tmp_path / "hello.txt"
    hello.write_text("hello world\n")
    r = runner.invoke(main, [p, "cp", str(hello), ":hello.txt"])
    assert r.exit_code == 0, r.output

    data_dir = tmp_path / "datadir"
    data_dir.mkdir()
    (data_dir / "data.bin").write_bytes(b"\x00\x01\x02")
    r = runner.invoke(main, [p, "cptree", str(data_dir), ":data"])
    assert r.exit_code == 0, r.output

    return p


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_repo(self, runner, repo_path):
        result = runner.invoke(main, [repo_path, "init"])
        assert result.exit_code == 0
        assert "Initialized" in result.output
        # Default branch is main
        result = runner.invoke(main, [repo_path, "branch", "list"])
        assert "main" in result.output

    def test_creates_repo_with_custom_branch(self, runner, repo_path):
        result = runner.invoke(main, [repo_path, "init", "--branch", "trunk"])
        assert result.exit_code == 0
        result = runner.invoke(main, [repo_path, "branch", "list"])
        assert "trunk" in result.output

    def test_already_exists_error(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "init"])
        assert result.exit_code != 0
        assert "already exists" in result.output


# ---------------------------------------------------------------------------
# TestCp
# ---------------------------------------------------------------------------

class TestCp:
    def test_disk_to_repo(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("content")
        result = runner.invoke(main, [initialized_repo, "cp", str(f), ":file.txt"])
        assert result.exit_code == 0, result.output

        # Verify via ls
        result = runner.invoke(main, [initialized_repo, "ls"])
        assert "file.txt" in result.output

    def test_repo_to_disk(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, [repo_with_files, "cp", ":hello.txt", str(dest)])
        assert result.exit_code == 0
        assert dest.read_text() == "hello world\n"

    def test_repo_to_disk_directory_dest(self, runner, repo_with_files, tmp_path):
        dest_dir = tmp_path / "outdir"
        dest_dir.mkdir()
        result = runner.invoke(main, [repo_with_files, "cp", ":hello.txt", str(dest_dir)])
        assert result.exit_code == 0
        assert (dest_dir / "hello.txt").read_text() == "hello world\n"

    def test_no_colon_error(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = runner.invoke(main, [initialized_repo, "cp", str(f), "no_colon"])
        assert result.exit_code != 0
        assert "repo path" in result.output.lower() or "':'" in result.output

    def test_both_colon_error(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "cp", ":a", ":b"])
        assert result.exit_code != 0
        assert "local path" in result.output.lower() or "Both" in result.output

    def test_custom_message(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "msg.txt"
        f.write_text("data")
        result = runner.invoke(main, [initialized_repo, "cp", str(f), ":msg.txt", "-m", "my custom msg"])
        assert result.exit_code == 0

        result = runner.invoke(main, [initialized_repo, "log"])
        assert "my custom msg" in result.output

    def test_missing_local_file(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "cp", "/nonexistent", ":dest.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_repo_file(self, runner, initialized_repo, tmp_path):
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, [initialized_repo, "cp", ":missing.txt", str(dest)])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_directory_error_suggests_cptree(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out"
        result = runner.invoke(main, [repo_with_files, "cp", ":data", str(dest)])
        assert result.exit_code != 0
        assert "cptree" in result.output.lower()

    def test_local_directory_error_suggests_cptree(self, runner, initialized_repo, tmp_path):
        d = tmp_path / "somedir"
        d.mkdir()
        result = runner.invoke(main, [initialized_repo, "cp", str(d), ":dest"])
        assert result.exit_code != 0
        assert "cptree" in result.output.lower()

    def test_custom_branch(self, runner, initialized_repo, tmp_path):
        # Create a dev branch
        runner.invoke(main, [initialized_repo, "branch", "create", "dev", "main"])
        f = tmp_path / "dev.txt"
        f.write_text("dev content")
        result = runner.invoke(main, [initialized_repo, "cp", str(f), ":dev.txt", "-b", "dev"])
        assert result.exit_code == 0

        # File should be on dev, not main
        result = runner.invoke(main, [initialized_repo, "ls", "-b", "dev"])
        assert "dev.txt" in result.output
        result = runner.invoke(main, [initialized_repo, "ls", "-b", "main"])
        assert "dev.txt" not in result.output


# ---------------------------------------------------------------------------
# TestCptree
# ---------------------------------------------------------------------------

class TestCptree:
    def test_disk_to_repo(self, runner, initialized_repo, tmp_path):
        src = tmp_path / "treesrc"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        sub = src / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("bbb")

        result = runner.invoke(main, [initialized_repo, "cptree", str(src), ":stuff"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, [initialized_repo, "ls", ":stuff"])
        assert "a.txt" in result.output
        assert "sub" in result.output

    def test_repo_to_disk(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "export"
        result = runner.invoke(main, [repo_with_files, "cptree", ":data", str(dest)])
        assert result.exit_code == 0
        assert (dest / "data.bin").read_bytes() == b"\x00\x01\x02"

    def test_root_export(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "full_export"
        result = runner.invoke(main, [repo_with_files, "cptree", ":", str(dest)])
        assert result.exit_code == 0
        assert (dest / "hello.txt").exists()
        assert (dest / "data" / "data.bin").exists()

    def test_trailing_slashes(self, runner, initialized_repo, tmp_path):
        src = tmp_path / "slashsrc"
        src.mkdir()
        (src / "f.txt").write_text("f")
        # Trailing slash should be stripped
        result = runner.invoke(main, [initialized_repo, "cptree", str(src), ":dir/"])
        assert result.exit_code == 0
        result = runner.invoke(main, [initialized_repo, "ls", ":dir"])
        assert "f.txt" in result.output

    def test_disk_to_repo_root(self, runner, initialized_repo, tmp_path):
        """cptree ./dir : should import files at the repo root."""
        src = tmp_path / "rootsrc"
        src.mkdir()
        (src / "r.txt").write_text("root file")
        result = runner.invoke(main, [initialized_repo, "cptree", str(src), ":"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, [initialized_repo, "ls"])
        assert "r.txt" in result.output

    def test_empty_dir_error(self, runner, initialized_repo, tmp_path):
        src = tmp_path / "empty"
        src.mkdir()
        result = runner.invoke(main, [initialized_repo, "cptree", str(src), ":empty"])
        assert result.exit_code != 0
        assert "No files" in result.output


# ---------------------------------------------------------------------------
# TestLs
# ---------------------------------------------------------------------------

class TestLs:
    def test_root(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "ls"])
        assert result.exit_code == 0
        assert "hello.txt" in result.output
        assert "data" in result.output

    def test_subdir(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "ls", ":data"])
        assert result.exit_code == 0
        assert "data.bin" in result.output

    def test_missing_path(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "ls", ":nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_no_colon_error(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "ls", "no_colon"])
        assert result.exit_code != 0
        assert "':'" in result.output


# ---------------------------------------------------------------------------
# TestCat
# ---------------------------------------------------------------------------

class TestCat:
    def test_file_contents(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "cat", ":hello.txt"])
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_missing_file(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "cat", ":nope.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_directory_error(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "cat", ":data"])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()


# ---------------------------------------------------------------------------
# TestRm
# ---------------------------------------------------------------------------

class TestRm:
    def test_removes_file(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "rm", ":hello.txt"])
        assert result.exit_code == 0

        result = runner.invoke(main, [repo_with_files, "ls"])
        assert "hello.txt" not in result.output

    def test_missing_file_error(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "rm", ":nonexistent.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_custom_message(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "rm", ":hello.txt", "-m", "bye bye"])
        assert result.exit_code == 0

        result = runner.invoke(main, [repo_with_files, "log"])
        assert "bye bye" in result.output


# ---------------------------------------------------------------------------
# TestLog
# ---------------------------------------------------------------------------

class TestLog:
    def test_all_commits(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "log"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        # At least: init + write hello.txt + write data tree
        assert len(lines) >= 3

    def test_path_filter(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "log", ":hello.txt"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) >= 1

    def test_nonexistent_path_empty(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "log", ":nonexistent.txt"])
        assert result.exit_code == 0
        assert result.output.strip() == ""


# ---------------------------------------------------------------------------
# TestBranch
# ---------------------------------------------------------------------------

class TestBranch:
    def test_list_default(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "branch"])
        assert result.exit_code == 0
        assert "main" in result.output

    def test_list_explicit(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "branch", "list"])
        assert result.exit_code == 0
        assert "main" in result.output

    def test_create(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "branch", "create", "dev", "main"])
        assert result.exit_code == 0
        assert "Created" in result.output

        result = runner.invoke(main, [initialized_repo, "branch", "list"])
        assert "dev" in result.output

    def test_duplicate_error(self, runner, initialized_repo):
        runner.invoke(main, [initialized_repo, "branch", "create", "dup", "main"])
        result = runner.invoke(main, [initialized_repo, "branch", "create", "dup", "main"])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_create_from_tag(self, runner, initialized_repo):
        runner.invoke(main, [initialized_repo, "tag", "create", "v1", "main"])
        result = runner.invoke(main, [initialized_repo, "branch", "create", "from-tag", "v1"])
        assert result.exit_code == 0

    def test_unknown_ref_error(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "branch", "create", "bad", "nonexistent"])
        assert result.exit_code != 0
        assert "Unknown ref" in result.output

    def test_delete(self, runner, initialized_repo):
        runner.invoke(main, [initialized_repo, "branch", "create", "todel", "main"])
        result = runner.invoke(main, [initialized_repo, "branch", "delete", "todel"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_delete_missing(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "branch", "delete", "ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_at_flag(self, runner, repo_with_files):
        result = runner.invoke(main, [
            repo_with_files, "branch", "create", "at-test", "main",
            "--at", "hello.txt"
        ])
        assert result.exit_code == 0

    def test_at_nonexistent_path(self, runner, initialized_repo):
        result = runner.invoke(main, [
            initialized_repo, "branch", "create", "bad-at", "main",
            "--at", "nonexistent.txt"
        ])
        assert result.exit_code != 0
        assert "No commits" in result.output


# ---------------------------------------------------------------------------
# TestTag
# ---------------------------------------------------------------------------

class TestTag:
    def test_list(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "tag", "list"])
        assert result.exit_code == 0

    def test_create(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "tag", "create", "v1", "main"])
        assert result.exit_code == 0
        assert "Created" in result.output

    def test_duplicate_error(self, runner, initialized_repo):
        runner.invoke(main, [initialized_repo, "tag", "create", "v1", "main"])
        result = runner.invoke(main, [initialized_repo, "tag", "create", "v1", "main"])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_delete(self, runner, initialized_repo):
        runner.invoke(main, [initialized_repo, "tag", "create", "v2", "main"])
        result = runner.invoke(main, [initialized_repo, "tag", "delete", "v2"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_delete_missing(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "tag", "delete", "ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_list_shows_all(self, runner, initialized_repo):
        runner.invoke(main, [initialized_repo, "tag", "create", "alpha", "main"])
        runner.invoke(main, [initialized_repo, "tag", "create", "beta", "main"])
        result = runner.invoke(main, [initialized_repo, "tag", "list"])
        assert "alpha" in result.output
        assert "beta" in result.output

    def test_at_flag(self, runner, repo_with_files):
        result = runner.invoke(main, [
            repo_with_files, "tag", "create", "v-at", "main",
            "--at", "hello.txt"
        ])
        assert result.exit_code == 0

    def test_create_from_commit_hash(self, runner, repo_with_files):
        # Get commit hash from log
        result = runner.invoke(main, [repo_with_files, "log"])
        first_line = result.output.strip().split("\n")[0]
        short_hash = first_line.split()[0]

        # Get the full hash via the library
        from gitstore import GitStore
        store = GitStore.open(repo_with_files)
        fs = store.branches["main"]
        full_hash = fs.hash

        result = runner.invoke(main, [
            repo_with_files, "tag", "create", "from-hash", full_hash
        ])
        assert result.exit_code == 0

    def test_default_invocation_lists(self, runner, initialized_repo):
        runner.invoke(main, [initialized_repo, "tag", "create", "t1", "main"])
        result = runner.invoke(main, [initialized_repo, "tag"])
        assert "t1" in result.output


# ---------------------------------------------------------------------------
# TestErrorPaths
# ---------------------------------------------------------------------------

class TestPathNormalization:
    def test_cp_leading_slash_normalized(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "norm.txt"
        f.write_text("data")
        result = runner.invoke(main, [initialized_repo, "cp", str(f), ":/foo"])
        assert result.exit_code == 0
        result = runner.invoke(main, [initialized_repo, "ls"])
        assert "foo" in result.output

    def test_cp_dotdot_rejected(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "bad.txt"
        f.write_text("data")
        result = runner.invoke(main, [initialized_repo, "cp", str(f), ":../escape"])
        assert result.exit_code != 0
        assert "Invalid" in result.output or "invalid" in result.output.lower()

    def test_cp_empty_repo_path_rejected(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("data")
        result = runner.invoke(main, [initialized_repo, "cp", str(f), ":"])
        assert result.exit_code != 0
        assert "empty" in result.output.lower()

    def test_rm_leading_slash_normalized(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "rm", ":/hello.txt"])
        assert result.exit_code == 0
        result = runner.invoke(main, [repo_with_files, "ls"])
        assert "hello.txt" not in result.output

    def test_rm_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "rm", ":../escape"])
        assert result.exit_code != 0

    def test_cptree_repo_to_disk_leading_slash(self, runner, repo_with_files, tmp_path):
        """cptree :/data ./out should export data/* directly under ./out/."""
        dest = tmp_path / "out"
        result = runner.invoke(main, [repo_with_files, "cptree", ":/data", str(dest)])
        assert result.exit_code == 0
        # Should be out/data.bin, NOT out/data/data.bin
        assert (dest / "data.bin").exists()
        assert not (dest / "data" / "data.bin").exists()

    def test_ls_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "ls", ":../x"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_cat_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "cat", ":../x"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_cat_empty_path_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "cat", ":"])
        assert result.exit_code != 0
        assert "empty" in result.output.lower()

    def test_cp_repo_to_disk_dotdot_rejected(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, [repo_with_files, "cp", ":../x", str(dest)])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_log_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, [repo_with_files, "log", ":../x"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_log_bare_colon_shows_all(self, runner, repo_with_files):
        """Bare ':' in log should behave like no path filter."""
        result_bare = runner.invoke(main, [repo_with_files, "log", ":"])
        result_none = runner.invoke(main, [repo_with_files, "log"])
        assert result_bare.exit_code == 0
        assert result_bare.output == result_none.output

    def test_ls_bare_colon_shows_root(self, runner, repo_with_files):
        """Bare ':' in ls should list root."""
        result_bare = runner.invoke(main, [repo_with_files, "ls", ":"])
        result_none = runner.invoke(main, [repo_with_files, "ls"])
        assert result_bare.exit_code == 0
        assert result_bare.output == result_none.output


class TestResolveRef:
    def test_non_commit_hash_rejected(self, runner, repo_with_files):
        """Passing a tree/blob hash should produce a clear error."""
        import pygit2
        from gitstore import GitStore
        store = GitStore.open(repo_with_files)
        fs = store.branches["main"]
        # Get the tree OID (not a commit)
        tree_oid = str(fs._tree_oid)
        result = runner.invoke(main, [
            repo_with_files, "tag", "create", "bad-ref", tree_oid
        ])
        assert result.exit_code != 0
        assert "not a commit" in result.output.lower()


class TestErrorPaths:
    def test_missing_repo(self, runner, tmp_path):
        bad_path = str(tmp_path / "nope.git")
        result = runner.invoke(main, [bad_path, "ls"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_branch(self, runner, initialized_repo):
        result = runner.invoke(main, [initialized_repo, "ls", "-b", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

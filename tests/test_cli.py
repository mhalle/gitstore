"""Tests for the gitstore CLI."""

import io
import os
import time
import zipfile

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
    result = runner.invoke(main, ["init", "--repo", p, "--branch", "main"])
    assert result.exit_code == 0, result.output
    return p


@pytest.fixture
def repo_with_files(tmp_path, runner):
    """Repo with hello.txt and data/data.bin on 'main'."""
    p = str(tmp_path / "test.git")
    r = runner.invoke(main, ["init", "--repo", p, "--branch", "main"])
    assert r.exit_code == 0, r.output

    hello = tmp_path / "hello.txt"
    hello.write_text("hello world\n")
    r = runner.invoke(main, ["cp", "--repo", p, str(hello), ":hello.txt"])
    assert r.exit_code == 0, r.output

    data_dir = tmp_path / "datadir"
    data_dir.mkdir()
    (data_dir / "data.bin").write_bytes(b"\x00\x01\x02")
    r = runner.invoke(main, ["cp", "--repo", p, str(data_dir) + "/", ":data"])
    assert r.exit_code == 0, r.output

    return p


@pytest.fixture
def repo_with_tree(tmp_path, runner):
    """Repo with a deeper tree for glob/recursive tests.

    Tree:
        readme.txt, setup.py, .hidden,
        src/main.py, src/util.py, src/sub/deep.txt,
        docs/guide.md, docs/api.md
    """
    p = str(tmp_path / "tree.git")
    r = runner.invoke(main, ["init", "--repo", p, "--branch", "main"])
    assert r.exit_code == 0, r.output

    # Create files on disk
    root = tmp_path / "treefiles"
    root.mkdir()
    (root / "readme.txt").write_text("readme")
    (root / "setup.py").write_text("setup")
    (root / ".hidden").write_text("hidden")

    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text("main")
    (src / "util.py").write_text("util")
    sub = src / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("deep")

    docs = root / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("guide")
    (docs / "api.md").write_text("api")

    # Copy entire tree into repo root (trailing / = contents mode)
    r = runner.invoke(main, ["cp", "--repo", p, str(root) + "/", ":"])
    assert r.exit_code == 0, r.output

    return p


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_repo(self, runner, repo_path):
        result = runner.invoke(main, ["init", "--repo", repo_path])
        assert result.exit_code == 0
        result = runner.invoke(main, ["branch", "--repo", repo_path, "list"])
        assert "main" in result.output

    def test_creates_repo_with_custom_branch(self, runner, repo_path):
        result = runner.invoke(main, ["init", "--repo", repo_path, "--branch", "trunk"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["branch", "--repo", repo_path, "list"])
        assert "trunk" in result.output

    def test_already_exists_error(self, runner, initialized_repo):
        result = runner.invoke(main, ["init", "--repo", initialized_repo])
        assert result.exit_code != 0
        assert "already exists" in result.output


# ---------------------------------------------------------------------------
# TestDestroy
# ---------------------------------------------------------------------------

class TestDestroy:
    def test_destroy_empty(self, runner, initialized_repo):
        result = runner.invoke(main, ["destroy", "--repo", initialized_repo])
        assert result.exit_code == 0
        import os
        assert not os.path.exists(initialized_repo)

    def test_destroy_nonempty_requires_force(self, runner, repo_with_files):
        result = runner.invoke(main, ["destroy", "--repo", repo_with_files])
        assert result.exit_code != 0
        assert "not empty" in result.output.lower()
        import os
        assert os.path.exists(repo_with_files)

    def test_destroy_nonempty_with_force(self, runner, repo_with_files):
        result = runner.invoke(main, ["destroy", "--repo", repo_with_files, "-f"])
        assert result.exit_code == 0
        import os
        assert not os.path.exists(repo_with_files)

    def test_destroy_missing_repo(self, runner, tmp_path):
        bad_path = str(tmp_path / "nope.git")
        result = runner.invoke(main, ["destroy", "--repo", bad_path])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# TestCp
# ---------------------------------------------------------------------------

class TestCp:
    def test_disk_to_repo(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("content")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":file.txt"])
        assert result.exit_code == 0, result.output

        # Verify via ls
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "file.txt" in result.output

    def test_repo_to_disk(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":hello.txt", str(dest)])
        assert result.exit_code == 0
        assert dest.read_text() == "hello world\n"

    def test_repo_to_disk_directory_dest(self, runner, repo_with_files, tmp_path):
        dest_dir = tmp_path / "outdir"
        dest_dir.mkdir()
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":hello.txt", str(dest_dir)])
        assert result.exit_code == 0
        assert (dest_dir / "hello.txt").read_text() == "hello world\n"

    def test_no_colon_error(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), "no_colon"])
        assert result.exit_code != 0
        assert "repo path" in result.output.lower() or "':'" in result.output

    def test_both_colon_error(self, runner, initialized_repo):
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, ":a", ":b"])
        assert result.exit_code != 0
        assert "local path" in result.output.lower() or "Both" in result.output

    def test_custom_message(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "msg.txt"
        f.write_text("data")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":msg.txt", "-m", "my custom msg"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "my custom msg" in result.output

    def test_mode_755(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "script.sh"
        f.write_text("#!/bin/sh\necho hi")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":script.sh", "--mode", "755"
        ])
        assert result.exit_code == 0, result.output
        # Verify mode via library
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        entry = tree["script.sh"]
        assert entry.filemode == 0o100755

    def test_mode_644_explicit(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("text")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":plain.txt", "--mode", "644"
        ])
        assert result.exit_code == 0, result.output
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        entry = tree["plain.txt"]
        assert entry.filemode == 0o100644

    def test_mode_default_is_644(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "default.txt"
        f.write_text("text")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":default.txt"
        ])
        assert result.exit_code == 0, result.output
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        entry = tree["default.txt"]
        assert entry.filemode == 0o100644

    def test_missing_local_file(self, runner, initialized_repo):
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, "/nonexistent", ":dest.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_repo_file(self, runner, initialized_repo, tmp_path):
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, ":missing.txt", str(dest)])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_directory_copies_recursively(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out"
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":data", str(dest)])
        assert result.exit_code == 0, result.output
        assert (dest / "data" / "data.bin").exists()

    def test_local_directory_copies_recursively(self, runner, initialized_repo, tmp_path):
        d = tmp_path / "somedir"
        d.mkdir()
        (d / "f.txt").write_text("content")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(d), ":dest"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":dest/somedir"])
        assert "f.txt" in result.output

    def test_multi_disk_to_repo(self, runner, initialized_repo, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f1), str(f2), ":stuff"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":stuff"])
        assert "a.txt" in result.output
        assert "b.txt" in result.output

    def test_multi_repo_to_disk(self, runner, repo_with_files, tmp_path):
        # Add a second file
        f = tmp_path / "second.txt"
        f.write_text("second")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":second.txt"])

        dest = tmp_path / "out"
        dest.mkdir()
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":hello.txt", ":second.txt", str(dest)
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "hello.txt").read_text() == "hello world\n"
        assert (dest / "second.txt").read_text() == "second"

    def test_multi_repo_to_disk_creates_dir(self, runner, repo_with_files, tmp_path):
        f = tmp_path / "second.txt"
        f.write_text("second")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":second.txt"])

        dest = tmp_path / "newdir"
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":hello.txt", ":second.txt", str(dest)
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "hello.txt").exists()
        assert (dest / "second.txt").exists()

    def test_multi_mixed_types_error(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":repo.txt", ":dest"
        ])
        assert result.exit_code != 0
        assert "same type" in result.output.lower()

    def test_single_arg_error(self, runner, initialized_repo):
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, ":only"])
        assert result.exit_code != 0
        assert "at least two" in result.output.lower()

    def test_custom_branch(self, runner, initialized_repo, tmp_path):
        # Create a dev branch
        runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "dev", "--from", "main"])
        f = tmp_path / "dev.txt"
        f.write_text("dev content")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":dev.txt", "-b", "dev"])
        assert result.exit_code == 0

        # File should be on dev, not main
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, "-b", "dev"])
        assert "dev.txt" in result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, "-b", "main"])
        assert "dev.txt" not in result.output

    def test_single_file_into_existing_repo_dir(self, runner, repo_with_files, tmp_path):
        """cp file.txt :data — data is an existing directory, file goes inside."""
        f = tmp_path / "new.txt"
        f.write_text("new content")
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":data"])
        assert result.exit_code == 0, result.output
        # File placed inside :data/, not overwriting it
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":data/new.txt"])
        assert result.exit_code == 0
        assert result.output == "new content"
        # Original directory contents still intact
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":data/data.bin"])
        assert result.exit_code == 0

    def test_single_repo_file_into_existing_local_dir(self, runner, repo_with_files, tmp_path):
        """cp :hello.txt existing_dir/ — file goes inside the local dir."""
        dest = tmp_path / "outdir"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":hello.txt", str(dest)])
        assert result.exit_code == 0, result.output
        assert (dest / "hello.txt").read_text() == "hello world\n"


# ---------------------------------------------------------------------------
# TestCpDirectories
# ---------------------------------------------------------------------------

class TestCpDirectories:
    def test_disk_dir_to_repo(self, runner, initialized_repo, tmp_path):
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "a.txt").write_text("aaa")
        (d / "b.txt").write_text("bbb")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(d), ":dest"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":dest/mydir"])
        assert "a.txt" in result.output
        assert "b.txt" in result.output

    def test_disk_dir_trailing_slash(self, runner, initialized_repo, tmp_path):
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "a.txt").write_text("aaa")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(d) + "/", ":dest"])
        assert result.exit_code == 0, result.output
        # Contents mode: a.txt directly under dest, no mydir
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":dest"])
        assert "a.txt" in result.output

    def test_repo_dir_to_disk(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":data", str(dest)])
        assert result.exit_code == 0, result.output
        assert (dest / "data" / "data.bin").exists()
        assert (dest / "data" / "data.bin").read_bytes() == b"\x00\x01\x02"

    def test_repo_dir_trailing_slash(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":data/", str(dest)])
        assert result.exit_code == 0, result.output
        # Contents mode: data.bin directly in out
        assert (dest / "data.bin").exists()

    def test_mixed_file_and_dir(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("file")
        d = tmp_path / "subdir"
        d.mkdir()
        (d / "nested.txt").write_text("nested")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), str(d), ":dest"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dest/file.txt"])
        assert result.output == "file"
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dest/subdir/nested.txt"])
        assert result.output == "nested"


# ---------------------------------------------------------------------------
# TestCpGlob
# ---------------------------------------------------------------------------

class TestCpGlob:
    def test_disk_glob_to_repo(self, runner, initialized_repo, tmp_path):
        d = tmp_path / "gdir"
        d.mkdir()
        (d / "a.txt").write_text("aaa")
        (d / "b.txt").write_text("bbb")
        (d / "c.md").write_text("ccc")
        (d / ".hidden").write_text("hid")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(d / "*.txt"), ":out"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":out"])
        assert "a.txt" in result.output
        assert "b.txt" in result.output
        assert "c.md" not in result.output
        assert ".hidden" not in result.output

    def test_repo_glob_to_disk(self, runner, repo_with_files, tmp_path):
        # Add more files to repo
        f1 = tmp_path / "x.txt"
        f1.write_text("xxx")
        f2 = tmp_path / "y.md"
        f2.write_text("yyy")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f1), ":x.txt"])
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f2), ":y.md"])

        dest = tmp_path / "out"
        dest.mkdir()
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":*.txt", str(dest)
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "x.txt").exists()
        assert (dest / "hello.txt").exists()
        assert not (dest / "y.md").exists()

    def test_glob_no_dotfiles(self, runner, initialized_repo, tmp_path):
        d = tmp_path / "dots"
        d.mkdir()
        (d / ".env").write_text("secret")
        (d / "app.txt").write_text("app")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(d / "*"), ":out"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":out"])
        assert "app.txt" in result.output
        assert ".env" not in result.output


# ---------------------------------------------------------------------------
# TestCpDryRun
# ---------------------------------------------------------------------------

class TestCpDryRun:
    def test_dry_run_disk_to_repo(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "dr.txt"
        f.write_text("data")
        # Single file: dest is the exact path
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "-n", str(f), ":dest"
        ])
        assert result.exit_code == 0, result.output
        assert "dr.txt" in result.output
        assert "-> :dest" in result.output
        # Nothing written
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "dr.txt" not in result.output

    def test_dry_run_repo_to_disk(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "drout"
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, "-n", ":hello.txt", str(dest)
        ])
        assert result.exit_code == 0, result.output
        assert "hello.txt" in result.output
        assert not dest.exists()

    def test_dry_run_dir(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "drout"
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, "--dry-run", ":data", str(dest)
        ])
        assert result.exit_code == 0, result.output
        assert "data.bin" in result.output
        assert "+ " in result.output  # categorized output
        assert not dest.exists()


# ---------------------------------------------------------------------------
# TestCpDelete
# ---------------------------------------------------------------------------

class TestCpDelete:
    def test_delete_disk_to_repo(self, runner, repo_with_files, tmp_path):
        """--delete removes repo files not in source."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "new.txt").write_text("new")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files,
            str(src) + "/", ":data", "--delete",
        ])
        assert result.exit_code == 0, result.output
        # data.bin should be gone, new.txt should exist
        result2 = runner.invoke(main, ["ls", "--repo", repo_with_files, ":data"])
        assert "new.txt" in result2.output
        assert "data.bin" not in result2.output

    def test_delete_repo_to_disk(self, runner, repo_with_files, tmp_path):
        """--delete removes local files not in source."""
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "extra.txt").write_text("extra")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files,
            ":data/", str(dest), "--delete",
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "data.bin").exists()
        assert not (dest / "extra.txt").exists()

    def test_delete_single_file_error(self, runner, repo_with_files, tmp_path):
        """--delete errors with single file source."""
        f = tmp_path / "single.txt"
        f.write_text("data")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files,
            str(f), ":dest", "--delete",
        ])
        assert result.exit_code != 0
        assert "Cannot use --delete" in result.output

    def test_delete_dry_run(self, runner, repo_with_files, tmp_path):
        """--delete --dry-run shows categorized actions."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "new.txt").write_text("new")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files,
            "-n", "--delete", str(src) + "/", ":data",
        ])
        assert result.exit_code == 0, result.output
        assert "+" in result.output  # add
        assert "-" in result.output  # delete


# ---------------------------------------------------------------------------
# TestCptree
# ---------------------------------------------------------------------------

class TestCpTree:
    """Tests for cp with directory tree operations (formerly cptree)."""

    def test_disk_dir_contents_to_repo(self, runner, initialized_repo, tmp_path):
        """cp dir/ :stuff copies contents into :stuff."""
        src = tmp_path / "treesrc"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        sub = src / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("bbb")

        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(src) + "/", ":stuff"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":stuff"])
        assert "a.txt" in result.output
        assert "sub" in result.output

    def test_repo_dir_contents_to_disk(self, runner, repo_with_files, tmp_path):
        """cp :data/ dest exports contents of :data into dest."""
        dest = tmp_path / "export"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":data/", str(dest)])
        assert result.exit_code == 0
        assert (dest / "data.bin").read_bytes() == b"\x00\x01\x02"

    def test_root_export(self, runner, repo_with_files, tmp_path):
        """cp :/ dest exports everything into dest."""
        dest = tmp_path / "full_export"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":/", str(dest)])
        assert result.exit_code == 0
        assert (dest / "hello.txt").exists()
        assert (dest / "data" / "data.bin").exists()

    def test_disk_dir_contents_to_repo_root(self, runner, initialized_repo, tmp_path):
        """cp dir/ : imports contents at repo root."""
        src = tmp_path / "rootsrc"
        src.mkdir()
        (src / "r.txt").write_text("root file")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(src) + "/", ":"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "r.txt" in result.output


# ---------------------------------------------------------------------------
# TestSymlinks
# ---------------------------------------------------------------------------

class TestSymlinks:
    def test_cp_repo_to_disk_symlink(self, runner, initialized_repo, tmp_path):
        """cp repo→disk creates a symlink on disk for symlink entries."""
        import os
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        dest = tmp_path / "out_link.txt"
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, ":link.txt", str(dest)])
        assert result.exit_code == 0, result.output
        assert dest.is_symlink()
        assert os.readlink(dest) == "target.txt"

    def test_cp_dir_disk_to_repo_preserves_symlinks(self, runner, initialized_repo, tmp_path):
        """cp dir/ :stuff preserves file symlinks by default."""
        import os
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK

        src = tmp_path / "treesrc"
        src.mkdir()
        (src / "real.txt").write_text("hello")
        os.symlink("real.txt", src / "link.txt")

        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(src) + "/", ":stuff"])
        assert result.exit_code == 0, result.output

        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.readlink("stuff/link.txt") == "real.txt"
        from gitstore.tree import _entry_at_path
        entry = _entry_at_path(store._repo, fs._tree_oid, "stuff/link.txt")
        assert entry is not None
        assert entry[1] == GIT_FILEMODE_LINK

    def test_cp_dir_disk_to_repo_symlink_to_dir(self, runner, initialized_repo, tmp_path):
        """cp dir/ :stuff preserves symlinked directories as symlink entries."""
        import os
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK

        src = tmp_path / "treesrc"
        src.mkdir()
        real_dir = src / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("inside")
        os.symlink("real_dir", src / "link_dir")

        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(src) + "/", ":stuff"])
        assert result.exit_code == 0, result.output

        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.readlink("stuff/link_dir") == "real_dir"
        from gitstore.tree import _entry_at_path
        entry = _entry_at_path(store._repo, fs._tree_oid, "stuff/link_dir")
        assert entry is not None
        assert entry[1] == GIT_FILEMODE_LINK

    def test_cp_dir_disk_to_repo_follow_symlinks(self, runner, initialized_repo, tmp_path):
        """cp dir/ :stuff --follow-symlinks dereferences file symlinks."""
        import os
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK

        src = tmp_path / "treesrc"
        src.mkdir()
        (src / "real.txt").write_text("hello")
        os.symlink("real.txt", src / "link.txt")

        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(src) + "/", ":stuff", "--follow-symlinks"
        ])
        assert result.exit_code == 0, result.output

        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        # Should be a regular file, not a symlink
        assert fs.read("stuff/link.txt") == b"hello"
        from gitstore.tree import _entry_at_path
        entry = _entry_at_path(store._repo, fs._tree_oid, "stuff/link.txt")
        assert entry is not None
        assert entry[1] != GIT_FILEMODE_LINK

    def test_cp_dir_disk_to_repo_follow_symlinks_dir(self, runner, initialized_repo, tmp_path):
        """cp dir/ :stuff --follow-symlinks follows symlinked directories."""
        import os
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK

        src = tmp_path / "treesrc"
        src.mkdir()
        real_dir = src / "real_dir"
        real_dir.mkdir()
        (real_dir / "a.txt").write_text("aaa")
        (real_dir / "b.txt").write_text("bbb")
        os.symlink("real_dir", src / "link_dir")

        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(src) + "/", ":stuff", "--follow-symlinks"
        ])
        assert result.exit_code == 0, result.output

        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        # The symlinked dir's contents should be stored as regular files
        assert fs.read("stuff/link_dir/a.txt") == b"aaa"
        assert fs.read("stuff/link_dir/b.txt") == b"bbb"
        # It should NOT be a symlink entry
        from gitstore.tree import _entry_at_path
        entry = _entry_at_path(store._repo, fs._tree_oid, "stuff/link_dir")
        assert entry is not None
        assert entry[1] != GIT_FILEMODE_LINK

    def test_cp_dir_disk_to_repo_follow_symlinks_cycle(self, runner, initialized_repo, tmp_path):
        """cp dir/ :stuff --follow-symlinks handles symlink cycles without infinite loop."""
        import os

        src = tmp_path / "treesrc"
        src.mkdir()
        (src / "file.txt").write_text("ok")
        subdir = src / "sub"
        subdir.mkdir()
        (subdir / "inner.txt").write_text("inner")
        # Create a cycle: sub/loop -> .. (points back to src)
        os.symlink(str(src), subdir / "loop")

        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(src) + "/", ":cyc", "--follow-symlinks"
        ])
        assert result.exit_code == 0, result.output

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.read("cyc/file.txt") == b"ok"
        assert fs.read("cyc/sub/inner.txt") == b"inner"

    def test_cp_dir_repo_to_disk_symlink(self, runner, initialized_repo, tmp_path):
        """cp :dir/ dest creates symlinks on disk for symlink entries."""
        import os
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("dir/target.txt", b"content")
        fs.write_symlink("dir/link.txt", "target.txt")

        dest = tmp_path / "export"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, ":dir/", str(dest)])
        assert result.exit_code == 0, result.output
        assert (dest / "link.txt").is_symlink()
        assert os.readlink(dest / "link.txt") == "target.txt"

    def test_cp_dir_roundtrip_symlinks(self, runner, initialized_repo, tmp_path):
        """cp dir/ :rt then cp :rt/ dest preserves symlinks."""
        import os

        # Create disk tree with symlinks
        src = tmp_path / "treesrc"
        src.mkdir()
        (src / "real.txt").write_text("hello")
        os.symlink("real.txt", src / "link.txt")

        # Disk → repo
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(src) + "/", ":rt"])
        assert result.exit_code == 0, result.output

        # Repo → disk
        dest = tmp_path / "export"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, ":rt/", str(dest)])
        assert result.exit_code == 0, result.output
        assert (dest / "link.txt").is_symlink()
        assert os.readlink(dest / "link.txt") == "real.txt"
        assert (dest / "real.txt").read_text() == "hello"


# ---------------------------------------------------------------------------
# TestLs
# ---------------------------------------------------------------------------

class TestLs:
    def test_root(self, runner, repo_with_files):
        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert result.exit_code == 0
        assert "hello.txt" in result.output
        assert "data" in result.output

    def test_subdir(self, runner, repo_with_files):
        result = runner.invoke(main, ["ls", "--repo", repo_with_files, ":data"])
        assert result.exit_code == 0
        assert "data.bin" in result.output

    def test_missing_path(self, runner, repo_with_files):
        result = runner.invoke(main, ["ls", "--repo", repo_with_files, ":nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_without_colon(self, runner, repo_with_files):
        result = runner.invoke(main, ["ls", "--repo", repo_with_files, "data"])
        assert result.exit_code == 0
        assert "data.bin" in result.output


# ---------------------------------------------------------------------------
# TestLsRecursive
# ---------------------------------------------------------------------------

class TestLsRecursive:
    def test_root_lists_all_files(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_tree])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert ".hidden" in lines
        assert "readme.txt" in lines
        assert "setup.py" in lines
        assert "src/main.py" in lines
        assert "src/util.py" in lines
        assert "src/sub/deep.txt" in lines
        assert "docs/guide.md" in lines
        assert "docs/api.md" in lines
        assert lines == sorted(lines)

    def test_subdir(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_tree, ":src"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "src/main.py" in lines
        assert "src/util.py" in lines
        assert "src/sub/deep.txt" in lines
        # root files not present
        assert "readme.txt" not in lines

    def test_nonexistent_error(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_tree, ":nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_file_not_a_directory(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_tree, ":readme.txt"])
        assert result.exit_code != 0
        assert "not a directory" in result.output.lower()

    def test_empty_branch(self, runner, tmp_path):
        p = str(tmp_path / "empty.git")
        r = runner.invoke(main, ["init", "--repo", p, "--branch", "main"])
        assert r.exit_code == 0
        result = runner.invoke(main, ["ls", "-R", "--repo", p])
        assert result.exit_code == 0
        assert result.output.strip() == ""


# ---------------------------------------------------------------------------
# TestLsGlob
# ---------------------------------------------------------------------------

class TestLsGlob:
    def test_star_txt_root(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "*.txt"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "readme.txt" in lines
        # nested files not matched by single-level glob
        assert "src/sub/deep.txt" not in lines

    def test_src_star_py(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "src/*.py"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "src/main.py" in lines
        assert "src/util.py" in lines

    def test_no_matches_silent(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "*.zzz"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_colon_prefix_stripped(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, ":*.txt"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "readme.txt" in lines

    def test_star_excludes_dotfiles(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "*"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert ".hidden" not in lines

    def test_dot_star_matches_dotfiles(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, ".*"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert ".hidden" in lines

    def test_question_mark(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "docs/???.md"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "docs/api.md" in lines
        # "guide.md" has 5 chars before .md, so ??? won't match
        assert "docs/guide.md" not in lines

    def test_docs_star(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "docs/*"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "docs/guide.md" in lines
        assert "docs/api.md" in lines


# ---------------------------------------------------------------------------
# TestLsGlobRecursive
# ---------------------------------------------------------------------------

class TestLsGlobRecursive:
    def test_glob_recursive_expands_dirs(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_tree, "src/*"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        # Direct file matches
        assert "src/main.py" in lines
        assert "src/util.py" in lines
        # src/sub is a dir match — should be expanded recursively
        assert "src/sub/deep.txt" in lines


# ---------------------------------------------------------------------------
# TestLsMultiArg
# ---------------------------------------------------------------------------

class TestLsMultiArg:
    def test_multiple_dirs(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, ":src", ":docs"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "main.py" in lines
        assert "util.py" in lines
        assert "guide.md" in lines
        assert "api.md" in lines

    def test_multiple_globs(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "*.txt", "*.py"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "readme.txt" in lines
        assert "setup.py" in lines

    def test_dedup_overlapping_globs(self, runner, repo_with_tree):
        """Overlapping patterns should not produce duplicate lines."""
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "*.txt", "readme.*"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert lines.count("readme.txt") == 1

    def test_dedup_recursive_overlap(self, runner, repo_with_tree):
        """Overlapping -R dirs should not produce duplicate lines."""
        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_tree, ":src", ":src"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert lines.count("src/main.py") == 1

    def test_mix_glob_and_plain(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, "*.txt", ":docs"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert "readme.txt" in lines
        assert "guide.md" in lines
        assert "api.md" in lines

    def test_error_stops_early(self, runner, repo_with_tree):
        """An invalid path still raises an error."""
        result = runner.invoke(main, ["ls", "--repo", repo_with_tree, ":src", ":nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# TestCat
# ---------------------------------------------------------------------------

class TestCat:
    def test_file_contents(self, runner, repo_with_files):
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":hello.txt"])
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_missing_file(self, runner, repo_with_files):
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":nope.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_without_colon(self, runner, repo_with_files):
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, "hello.txt"])
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_directory_error(self, runner, repo_with_files):
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":data"])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()


# ---------------------------------------------------------------------------
# TestRm
# ---------------------------------------------------------------------------

class TestRm:
    def test_removes_file(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":hello.txt"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "hello.txt" not in result.output

    def test_missing_file_error(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":nonexistent.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_directory_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":data"])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()

    def test_without_colon(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, "hello.txt"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "hello.txt" not in result.output

    def test_custom_message(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":hello.txt", "-m", "bye bye"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["log", "--repo", repo_with_files])
        assert "bye bye" in result.output


# ---------------------------------------------------------------------------
# TestWrite
# ---------------------------------------------------------------------------

class TestWrite:
    def test_write_from_stdin(self, runner, initialized_repo):
        result = runner.invoke(main, ["write", "--repo", initialized_repo, "file.txt"], input=b"hello world\n")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, "file.txt"])
        assert result.exit_code == 0
        assert result.output == "hello world\n"

    def test_write_overwrites_existing(self, runner, repo_with_files):
        result = runner.invoke(main, ["write", "--repo", repo_with_files, "hello.txt"], input=b"new content\n")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["cat", "--repo", repo_with_files, "hello.txt"])
        assert result.exit_code == 0
        assert result.output == "new content\n"

    def test_write_custom_message(self, runner, initialized_repo):
        result = runner.invoke(main, ["write", "--repo", initialized_repo, "file.txt", "-m", "my msg"], input=b"data")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "my msg" in result.output

    def test_write_colon_prefix_optional(self, runner, initialized_repo):
        result = runner.invoke(main, ["write", "--repo", initialized_repo, ":file.txt"], input=b"abc")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, "file.txt"])
        assert result.exit_code == 0
        assert result.output == "abc"


# ---------------------------------------------------------------------------
# TestLog
# ---------------------------------------------------------------------------

class TestLog:
    def test_all_commits(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        # At least: init + write hello.txt + write data tree
        assert len(lines) >= 3

    def test_path_filter(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--path", "hello.txt"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) >= 1

    def test_at_without_colon(self, runner, repo_with_files):
        """--path should work without a leading ':'."""
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--path", "hello.txt"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) >= 1

    def test_nonexistent_path_empty(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--path", "nonexistent.txt"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_match_exact(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])
        result = runner.invoke(main, ["log", "--repo", initialized_repo, "--match", "deploy v1"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "deploy v1" in lines[0]

    def test_match_wildcard(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v2"])
        f.write_text("c")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])
        result = runner.invoke(main, ["log", "--repo", initialized_repo, "--match", "deploy*"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 2
        assert all("deploy" in line for line in lines)

    def test_match_no_results(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--match", "zzz-no-match*"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_match_and_at(self, runner, initialized_repo, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a")
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f1), ":a.txt", "-m", "deploy a"])
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "deploy b"])
        f1.write_text("a2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f1), ":a.txt", "-m", "fix a"])
        result = runner.invoke(main, ["log", "--repo", initialized_repo, "--path", "a.txt", "--match", "deploy*"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "deploy a" in lines[0]

    def test_json_format(self, runner, repo_with_files):
        import json
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 3
        entry = data[0]
        assert "hash" in entry
        assert "message" in entry
        assert "time" in entry
        assert "author_name" in entry
        assert "author_email" in entry
        assert len(entry["hash"]) == 40

    def test_jsonl_format(self, runner, repo_with_files):
        import json
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--format", "jsonl"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) >= 3
        for line in lines:
            entry = json.loads(line)
            assert "hash" in entry
            assert "message" in entry


# ---------------------------------------------------------------------------
# TestBranch
# ---------------------------------------------------------------------------

class TestBranch:
    def test_list_default(self, runner, initialized_repo):
        result = runner.invoke(main, ["branch", "--repo", initialized_repo])
        assert result.exit_code == 0
        assert "main" in result.output

    def test_list_explicit(self, runner, initialized_repo):
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "list"])
        assert result.exit_code == 0
        assert "main" in result.output

    def test_create(self, runner, initialized_repo):
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "dev", "--from", "main"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "list"])
        assert "dev" in result.output

    def test_duplicate_error(self, runner, initialized_repo):
        runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "dup", "--from", "main"])
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "dup", "--from", "main"])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_create_from_tag(self, runner, initialized_repo):
        runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "v1", "--from", "main"])
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "from-tag", "--from", "v1"])
        assert result.exit_code == 0

    def test_unknown_ref_error(self, runner, initialized_repo):
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "bad", "--from", "nonexistent"])
        assert result.exit_code != 0
        assert "Unknown ref" in result.output

    def test_delete(self, runner, initialized_repo):
        runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "todel", "--from", "main"])
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "delete", "todel"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "list"])
        assert "todel" not in result.output

    def test_delete_missing(self, runner, initialized_repo):
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "delete", "ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_at_flag(self, runner, repo_with_files):
        result = runner.invoke(main, [
            "branch", "--repo", repo_with_files, "create", "at-test",
            "--from", "main", "--path", "hello.txt"
        ])
        assert result.exit_code == 0

    def test_at_nonexistent_path(self, runner, initialized_repo):
        result = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "create", "bad-at",
            "--from", "main", "--path", "nonexistent.txt"
        ])
        assert result.exit_code != 0
        assert "No matching commits" in result.output

    def test_create_empty(self, runner, initialized_repo):
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "create", "empty"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["branch", "--repo", initialized_repo, "list"])
        assert "empty" in result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, "-b", "empty"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_at_without_from_error(self, runner, initialized_repo):
        result = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "create", "bad", "--path", "x.txt"
        ])
        assert result.exit_code != 0
        assert "require --from" in result.output

    def test_at_dotdot_rejected(self, runner, initialized_repo):
        result = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "create", "bad",
            "--from", "main", "--path", "../escape"
        ])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_hash(self, runner, repo_with_files):
        from gitstore import GitStore
        store = GitStore.open(repo_with_files, create=False)
        expected = store.branches["main"].hash
        result = runner.invoke(main, ["branch", "--repo", repo_with_files, "hash", "main"])
        assert result.exit_code == 0
        out = result.output.strip()
        assert len(out) == 40
        assert out == expected

    def test_hash_back(self, runner, repo_with_files):
        from gitstore import GitStore
        store = GitStore.open(repo_with_files, create=False)
        expected = store.branches["main"].parent.hash
        result = runner.invoke(main, [
            "branch", "--repo", repo_with_files, "hash", "main", "--back", "1"
        ])
        assert result.exit_code == 0
        assert result.output.strip() == expected

    def test_hash_back_too_far(self, runner, initialized_repo):
        result = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "hash", "main", "--back", "100"
        ])
        assert result.exit_code != 0
        assert "history too short" in result.output.lower()

    def test_hash_path(self, runner, repo_with_files):
        from gitstore import GitStore
        store = GitStore.open(repo_with_files, create=False)
        fs = store.branches["main"]
        expected = next(fs.log(path="hello.txt")).hash
        result = runner.invoke(main, [
            "branch", "--repo", repo_with_files, "hash", "main", "--path", "hello.txt"
        ])
        assert result.exit_code == 0
        assert result.output.strip() == expected

    def test_hash_nonexistent(self, runner, initialized_repo):
        result = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "hash", "ghost"
        ])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# TestTag
# ---------------------------------------------------------------------------

class TestTag:
    def test_list(self, runner, initialized_repo):
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert result.exit_code == 0

    def test_create(self, runner, initialized_repo):
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "v1", "--from", "main"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert "v1" in result.output

    def test_duplicate_error(self, runner, initialized_repo):
        runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "v1", "--from", "main"])
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "v1", "--from", "main"])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_delete(self, runner, initialized_repo):
        runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "v2", "--from", "main"])
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "delete", "v2"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert "v2" not in result.output

    def test_delete_missing(self, runner, initialized_repo):
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "delete", "ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_list_shows_all(self, runner, initialized_repo):
        runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "alpha", "--from", "main"])
        runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "beta", "--from", "main"])
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert "alpha" in result.output
        assert "beta" in result.output

    def test_at_flag(self, runner, repo_with_files):
        result = runner.invoke(main, [
            "tag", "--repo", repo_with_files, "create", "v-at", "--from", "main",
            "--path", "hello.txt"
        ])
        assert result.exit_code == 0

    def test_create_from_commit_hash(self, runner, repo_with_files):
        # Get commit hash from log
        result = runner.invoke(main, ["log", "--repo", repo_with_files])
        first_line = result.output.strip().split("\n")[0]
        short_hash = first_line.split()[0]

        # Get the full hash via the library
        from gitstore import GitStore
        store = GitStore.open(repo_with_files, create=False)
        fs = store.branches["main"]
        full_hash = fs.hash

        result = runner.invoke(main, [
            "tag", "--repo", repo_with_files, "create", "from-hash", "--from", full_hash
        ])
        assert result.exit_code == 0

    def test_default_invocation_lists(self, runner, initialized_repo):
        runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "t1", "--from", "main"])
        result = runner.invoke(main, ["tag", "--repo", initialized_repo])
        assert "t1" in result.output

    def test_hash(self, runner, initialized_repo):
        runner.invoke(main, ["tag", "--repo", initialized_repo, "create", "v1", "--from", "main"])
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        expected = store.tags["v1"].hash
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "hash", "v1"])
        assert result.exit_code == 0
        out = result.output.strip()
        assert len(out) == 40
        assert out == expected

    def test_hash_nonexistent(self, runner, initialized_repo):
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "hash", "ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# TestTagOption (--tag / --force-tag on write commands)
# ---------------------------------------------------------------------------

class TestTagOption:
    def test_write_tag(self, runner, initialized_repo):
        result = runner.invoke(
            main, ["write", "--repo", initialized_repo, ":hello.txt", "--tag", "v1"],
            input=b"hello",
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert "v1" in result.output

    def test_rm_tag(self, runner, repo_with_files):
        result = runner.invoke(
            main, ["rm", "--repo", repo_with_files, ":hello.txt", "--tag", "after-rm"],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["tag", "--repo", repo_with_files, "list"])
        assert "after-rm" in result.output

    def test_cp_tag(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data")
        result = runner.invoke(
            main, ["cp", "--repo", initialized_repo, str(f), ":", "--tag", "cp-v1"],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert "cp-v1" in result.output

    def test_unzip_tag(self, runner, initialized_repo, tmp_path):
        zpath = tmp_path / "test.zip"
        with zipfile.ZipFile(str(zpath), "w") as zf:
            zf.writestr("a.txt", "aaa")
        result = runner.invoke(
            main, ["unzip", "--repo", initialized_repo, str(zpath), "--tag", "zip-v1"],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert "zip-v1" in result.output

    def test_duplicate_tag_error(self, runner, initialized_repo):
        runner.invoke(
            main, ["write", "--repo", initialized_repo, ":a.txt", "--tag", "dup"],
            input=b"one",
        )
        result = runner.invoke(
            main, ["write", "--repo", initialized_repo, ":b.txt", "--tag", "dup"],
            input=b"two",
        )
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_force_tag_overwrites(self, runner, initialized_repo):
        runner.invoke(
            main, ["write", "--repo", initialized_repo, ":a.txt", "--tag", "rel"],
            input=b"one",
        )
        result = runner.invoke(
            main, ["write", "--repo", initialized_repo, ":b.txt", "--tag", "rel", "--force-tag"],
            input=b"two",
        )
        assert result.exit_code == 0, result.output
        # Tag should point at the second commit
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.tags["rel"]
        assert fs.read("b.txt") == b"two"

    def test_sync_tag(self, runner, initialized_repo, tmp_path):
        d = tmp_path / "syncdir"
        d.mkdir()
        (d / "x.txt").write_text("x")
        result = runner.invoke(
            main, ["sync", "--repo", initialized_repo, str(d), ":", "--tag", "sync-v1"],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["tag", "--repo", initialized_repo, "list"])
        assert "sync-v1" in result.output

    def test_cp_tag_rejected_repo_to_disk(self, runner, repo_with_files, tmp_path):
        result = runner.invoke(
            main, ["cp", "--repo", repo_with_files, ":hello.txt", str(tmp_path / "out.txt"), "--tag", "nope"],
        )
        assert result.exit_code != 0
        assert "only applies when writing to repo" in result.output.lower()

    def test_sync_tag_rejected_repo_to_disk(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out"
        dest.mkdir()
        result = runner.invoke(
            main, ["sync", "--repo", repo_with_files, ":", str(dest), "--tag", "nope"],
        )
        assert result.exit_code != 0
        assert "only applies when writing to repo" in result.output.lower()


# ---------------------------------------------------------------------------
# TestErrorPaths
# ---------------------------------------------------------------------------

class TestPathNormalization:
    def test_cp_leading_slash_normalized(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "norm.txt"
        f.write_text("data")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":/foo"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "foo" in result.output

    def test_cp_dotdot_rejected(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "bad.txt"
        f.write_text("data")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":../escape"])
        assert result.exit_code != 0
        assert "Invalid" in result.output or "invalid" in result.output.lower()

    def test_cp_bare_colon_copies_to_root(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "rootfile.txt"
        f.write_text("data")
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "rootfile.txt" in result.output

    def test_rm_leading_slash_normalized(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":/hello.txt"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "hello.txt" not in result.output

    def test_rm_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":../escape"])
        assert result.exit_code != 0

    def test_cp_dir_contents_leading_slash(self, runner, repo_with_files, tmp_path):
        """cp :/data/ ./out should export data/* directly under ./out/."""
        dest = tmp_path / "out"
        dest.mkdir()
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":/data/", str(dest)])
        assert result.exit_code == 0
        # Should be out/data.bin, NOT out/data/data.bin
        assert (dest / "data.bin").exists()
        assert not (dest / "data" / "data.bin").exists()

    def test_ls_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, ["ls", "--repo", repo_with_files, ":../x"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_cat_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":../x"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_cat_empty_path_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":"])
        assert result.exit_code != 0
        assert "empty" in result.output.lower()

    def test_cp_repo_to_disk_dotdot_rejected(self, runner, repo_with_files, tmp_path):
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":../x", str(dest)])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_at_dotdot_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--path", "../x"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    def test_ls_bare_colon_shows_root(self, runner, repo_with_files):
        """Bare ':' in ls should list root."""
        result_bare = runner.invoke(main, ["ls", "--repo", repo_with_files, ":"])
        result_none = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert result_bare.exit_code == 0
        assert result_bare.output == result_none.output


class TestResolveRef:
    def test_non_commit_hash_rejected(self, runner, repo_with_files):
        """Passing a tree/blob hash should produce a clear error."""
        from gitstore import GitStore
        store = GitStore.open(repo_with_files, create=False)
        fs = store.branches["main"]
        # Get the tree OID (not a commit)
        tree_oid = str(fs._tree_oid)
        result = runner.invoke(main, [
            "tag", "--repo", repo_with_files, "create", "bad-ref", "--from", tree_oid
        ])
        assert result.exit_code != 0
        assert "not a commit" in result.output.lower()


class TestErrorPaths:
    def test_missing_repo(self, runner, tmp_path):
        bad_path = str(tmp_path / "nope.git")
        result = runner.invoke(main, ["ls", "--repo", bad_path])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_branch(self, runner, initialized_repo):
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, "-b", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_repo_error(self, runner):
        """Running a command with no --repo and no GITSTORE_REPO should fail."""
        result = runner.invoke(main, ["ls"])
        assert result.exit_code != 0
        assert "GITSTORE_REPO" in result.output

    def test_env_var_fallback(self, runner, initialized_repo):
        """GITSTORE_REPO env var should work as fallback for --repo."""
        result = runner.invoke(main, ["ls"], env={"GITSTORE_REPO": initialized_repo})
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestZip
# ---------------------------------------------------------------------------

class TestZip:
    def test_zip_basic(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "hello.txt" in names
            assert "data/data.bin" in names

    def test_zip_contents(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            assert zf.read("hello.txt") == b"hello world\n"
            assert zf.read("data/data.bin") == b"\x00\x01\x02"

    def test_zip_with_at(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out, "--path", "a.txt"])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "a.txt" in names
            # b.txt was added after a.txt, so the snapshot at a.txt shouldn't have it
            assert "b.txt" not in names

    def test_zip_with_match(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out, "--match", "deploy*"])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            assert zf.read("a.txt") == b"v1"

    def test_zip_stdout(self, runner, repo_with_files):
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, "-"])
        assert result.exit_code == 0, result.output
        zf = zipfile.ZipFile(io.BytesIO(result.output_bytes))
        names = zf.namelist()
        assert "hello.txt" in names
        assert zf.read("hello.txt") == b"hello world\n"

    def test_zip_preserves_executable(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh\necho hi")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":run.sh", "--mode", "755"
        ])
        assert result.exit_code == 0, result.output

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            info = zf.getinfo("run.sh")
            unix_mode = info.external_attr >> 16
            assert unix_mode & 0o111  # executable bit set

    def test_zip_no_match_error(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, out, "--match", "zzz-no-match*"])
        assert result.exit_code != 0
        assert "No matching commits" in result.output

    def test_zip_preserves_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in the repo are exported as symlinks in the zip."""
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            info = zf.getinfo("link.txt")
            unix_mode = info.external_attr >> 16
            assert (unix_mode & 0o170000) == 0o120000
            assert zf.read("link.txt") == b"target.txt"

    def test_zip_create_system_unix(self, runner, initialized_repo, tmp_path):
        """Zip entries have create_system=3 (Unix) for correct external_attr."""
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("file.txt", b"data")
        fs.write_symlink("link.txt", "file.txt")

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            for info in zf.infolist():
                assert info.create_system == 3, f"{info.filename}: create_system={info.create_system}"


# ---------------------------------------------------------------------------
# TestUnzip
# ---------------------------------------------------------------------------

class TestUnzip:
    def test_unzip_basic(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("file1.txt", "hello")
            zf.writestr("file2.txt", "world")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "file1.txt" in result.output
        assert "file2.txt" in result.output

    def test_unzip_contents(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("greet.txt", "hi there")
        runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":greet.txt"])
        assert result.exit_code == 0
        assert "hi there" in result.output

    def test_unzip_custom_message(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("msg.txt", "data")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath, "-m", "bulk import"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "bulk import" in result.output

    def test_unzip_nested(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("dir/sub/deep.txt", "nested content")
            zf.writestr("top.txt", "top level")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":dir/sub"])
        assert "deep.txt" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/sub/deep.txt"])
        assert "nested content" in result.output

    def test_unzip_preserves_executable(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            info = zipfile.ZipInfo("script.sh")
            info.external_attr = 0o100755 << 16
            zf.writestr(info, "#!/bin/sh\necho hi")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        assert tree["script.sh"].filemode == 0o100755

    def test_unzip_roundtrip_permissions(self, runner, initialized_repo, tmp_path):
        """Zip then unzip preserves executable bit."""
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":run.sh", "--mode", "755"])
        f2 = tmp_path / "data.txt"
        f2.write_text("plain")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":data.txt"])

        # Zip it
        archive = str(tmp_path / "archive.zip")
        runner.invoke(main, ["zip", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["unzip", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        from gitstore import GitStore
        store = GitStore.open(p2, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        assert tree["run.sh"].filemode == 0o100755
        assert tree["data.txt"].filemode == 0o100644

    def test_unzip_invalid_zip(self, runner, initialized_repo, tmp_path):
        bad = tmp_path / "notazip.bin"
        bad.write_bytes(b"this is not a zip")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, str(bad)])
        assert result.exit_code != 0
        assert "Not a valid zip" in result.output

    def test_unzip_empty_zip(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "empty.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            pass  # no files
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code != 0
        assert "no files" in result.output.lower()

    def test_unzip_imports_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in a zip are imported as symlinks in the repo."""
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("target.txt", "content")
            info = zipfile.ZipInfo("link.txt")
            info.external_attr = 0o120000 << 16
            zf.writestr(info, "target.txt")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output

        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        assert tree["link.txt"].filemode == GIT_FILEMODE_LINK
        assert fs.readlink("link.txt") == "target.txt"

    def test_unzip_roundtrip_symlinks(self, runner, initialized_repo, tmp_path):
        """Zip then unzip preserves symlinks."""
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        # Zip it
        archive = str(tmp_path / "archive.zip")
        runner.invoke(main, ["zip", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["unzip", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        store2 = GitStore.open(p2, create=False)
        fs2 = store2.branches["main"]
        assert fs2.readlink("link.txt") == "target.txt"
        tree = store2._repo[fs2._tree_oid]
        assert tree["link.txt"].filemode == GIT_FILEMODE_LINK
        assert tree["target.txt"].filemode == 0o100644

    def test_unzip_leading_dot_slash(self, runner, initialized_repo, tmp_path):
        """Zip entries with leading ./ are accepted and normalized."""
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("./dir/file.txt", "hello")
            zf.writestr("./top.txt", "top")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/file.txt"])
        assert "hello" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":top.txt"])
        assert "top" in result.output


# ---------------------------------------------------------------------------
# TestTar
# ---------------------------------------------------------------------------

class TestTar:
    def test_tar_basic(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "hello.txt" in names
            assert "data/data.bin" in names

    def test_tar_contents(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            assert tf.extractfile("hello.txt").read() == b"hello world\n"
            assert tf.extractfile("data/data.bin").read() == b"\x00\x01\x02"

    def test_tar_gz(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar.gz")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        import gzip
        with open(out, "rb") as f:
            # gzip magic bytes
            assert f.read(2) == b"\x1f\x8b"
        import tarfile
        with tarfile.open(out, "r:gz") as tf:
            names = tf.getnames()
            assert "hello.txt" in names

    def test_tar_with_at(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out, "--path", "a.txt"])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "a.txt" in names
            assert "b.txt" not in names

    def test_tar_with_match(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out, "--match", "deploy*"])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            assert tf.extractfile("a.txt").read() == b"v1"

    def test_tar_stdout(self, runner, repo_with_files):
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, "-"])
        assert result.exit_code == 0, result.output
        import tarfile
        tf = tarfile.open(fileobj=io.BytesIO(result.output_bytes), mode="r:")
        names = tf.getnames()
        assert "hello.txt" in names
        assert tf.extractfile("hello.txt").read() == b"hello world\n"
        tf.close()

    def test_tar_preserves_executable(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh\necho hi")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":run.sh", "--mode", "755"
        ])
        assert result.exit_code == 0, result.output

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            info = tf.getmember("run.sh")
            assert info.mode & 0o111  # executable bit set

    def test_tar_no_match_error(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out, "--match", "zzz-no-match*"])
        assert result.exit_code != 0
        assert "No matching commits" in result.output

    def test_tar_preserves_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in the repo are exported as symlinks in the tar."""
        import tarfile
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r") as tf:
            member = tf.getmember("link.txt")
            assert member.issym()
            assert member.linkname == "target.txt"


# ---------------------------------------------------------------------------
# TestUntar
# ---------------------------------------------------------------------------

class TestUntar:
    def test_untar_basic(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="file1.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            data2 = b"world"
            info2 = tarfile.TarInfo(name="file2.txt")
            info2.size = len(data2)
            tf.addfile(info2, io.BytesIO(data2))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "file1.txt" in result.output
        assert "file2.txt" in result.output

    def test_untar_contents(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"hi there"
            info = tarfile.TarInfo(name="greet.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":greet.txt"])
        assert result.exit_code == 0
        assert "hi there" in result.output

    def test_untar_custom_message(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"data"
            info = tarfile.TarInfo(name="msg.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath, "-m", "bulk import"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "bulk import" in result.output

    def test_untar_nested(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"nested content"
            info = tarfile.TarInfo(name="dir/sub/deep.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            data2 = b"top level"
            info2 = tarfile.TarInfo(name="top.txt")
            info2.size = len(data2)
            tf.addfile(info2, io.BytesIO(data2))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":dir/sub"])
        assert "deep.txt" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/sub/deep.txt"])
        assert "nested content" in result.output

    def test_untar_preserves_executable(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"#!/bin/sh\necho hi"
            info = tarfile.TarInfo(name="script.sh")
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        assert tree["script.sh"].filemode == 0o100755

    def test_untar_roundtrip_permissions(self, runner, initialized_repo, tmp_path):
        """Tar then untar preserves executable bit."""
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":run.sh", "--mode", "755"])
        f2 = tmp_path / "data.txt"
        f2.write_text("plain")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":data.txt"])

        # Tar it
        archive = str(tmp_path / "archive.tar")
        runner.invoke(main, ["tar", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["untar", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        from gitstore import GitStore
        store = GitStore.open(p2, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        assert tree["run.sh"].filemode == 0o100755
        assert tree["data.txt"].filemode == 0o100644

    def test_untar_invalid_archive(self, runner, initialized_repo, tmp_path):
        bad = tmp_path / "notatar.bin"
        bad.write_bytes(b"this is not a tar")
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, str(bad)])
        assert result.exit_code != 0
        assert "Not a valid tar" in result.output

    def test_untar_empty_archive(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "empty.tar")
        with tarfile.open(tpath, "w") as tf:
            pass  # no files
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code != 0
        assert "no files" in result.output.lower()

    def test_untar_stdin(self, runner, initialized_repo, tmp_path):
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:") as tf:
            data = b"from stdin"
            info = tarfile.TarInfo(name="piped.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, "-"], input=buf.getvalue())
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":piped.txt"])
        assert "from stdin" in result.output

    def test_untar_gz(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar.gz")
        with tarfile.open(tpath, "w:gz") as tf:
            data = b"compressed"
            info = tarfile.TarInfo(name="comp.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":comp.txt"])
        assert "compressed" in result.output

    def test_untar_imports_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in a tar are imported as symlinks in the repo."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            # regular file
            data = b"content"
            info = tarfile.TarInfo(name="target.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            # symlink
            info = tarfile.TarInfo(name="link.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "target.txt"
            tf.addfile(info)
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output

        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        assert tree["link.txt"].filemode == GIT_FILEMODE_LINK
        assert fs.readlink("link.txt") == "target.txt"

    def test_untar_roundtrip_symlinks(self, runner, initialized_repo, tmp_path):
        """Tar then untar preserves symlinks."""
        import tarfile
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        # Tar it
        archive = str(tmp_path / "archive.tar")
        runner.invoke(main, ["tar", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["untar", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        store2 = GitStore.open(p2, create=False)
        fs2 = store2.branches["main"]
        assert fs2.readlink("link.txt") == "target.txt"
        tree = store2._repo[fs2._tree_oid]
        assert tree["link.txt"].filemode == GIT_FILEMODE_LINK
        assert tree["target.txt"].filemode == 0o100644

    def test_untar_leading_dot_slash(self, runner, initialized_repo, tmp_path):
        """Tar entries with leading ./ are accepted and normalized."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="./dir/file.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            data2 = b"top"
            info2 = tarfile.TarInfo(name="./top.txt")
            info2.size = len(data2)
            tf.addfile(info2, io.BytesIO(data2))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/file.txt"])
        assert "hello" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":top.txt"])
        assert "top" in result.output

    def test_untar_hard_link(self, runner, initialized_repo, tmp_path):
        """Hard links in tar are materialized as regular files."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"shared content"
            info = tarfile.TarInfo(name="original.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            # Hard link pointing to original.txt
            link_info = tarfile.TarInfo(name="hardlink.txt")
            link_info.type = tarfile.LNKTYPE
            link_info.linkname = "original.txt"
            tf.addfile(link_info)
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":hardlink.txt"])
        assert result.exit_code == 0
        assert "shared content" in result.output

    def test_untar_hard_link_preserves_exec_from_target(self, runner, initialized_repo, tmp_path):
        """Hard link inherits executable bit from the original target member."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"#!/bin/sh\necho hi"
            info = tarfile.TarInfo(name="script.sh")
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
            # Hard link with mode=0 (common in real tars)
            link_info = tarfile.TarInfo(name="link.sh")
            link_info.type = tarfile.LNKTYPE
            link_info.linkname = "script.sh"
            link_info.mode = 0
            tf.addfile(link_info)
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        tree = store._repo[fs._tree_oid]
        assert tree["link.sh"].filemode == 0o100755

    def test_untar_hard_link_stdin_skip_warning(self, runner, initialized_repo, tmp_path):
        """Hard links that can't be resolved in streaming mode are skipped with a warning."""
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:") as tf:
            # Hard link BEFORE the target — unresolvable in streaming mode
            link_info = tarfile.TarInfo(name="link.txt")
            link_info.type = tarfile.LNKTYPE
            link_info.linkname = "original.txt"
            tf.addfile(link_info)
            data = b"content"
            info = tarfile.TarInfo(name="original.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, "-"], input=buf.getvalue())
        assert result.exit_code == 0, result.output
        # The regular file should be imported
        result2 = runner.invoke(main, ["cat", "--repo", initialized_repo, ":original.txt"])
        assert result2.exit_code == 0
        assert "content" in result2.output
        # The hard link should NOT exist (skipped)
        result3 = runner.invoke(main, ["cat", "--repo", initialized_repo, ":link.txt"])
        assert result3.exit_code != 0


# ---------------------------------------------------------------------------
# TestNonUtf8Symlink
# ---------------------------------------------------------------------------

class TestNonUtf8Symlink:
    def test_zip_export_non_utf8_symlink(self, runner, initialized_repo, tmp_path):
        """Non-UTF-8 symlink targets produce a clear error on zip export."""
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        # Write a symlink with non-UTF-8 target bytes directly via pygit2
        repo = store._repo
        bad_target = b"caf\xe9"  # not valid UTF-8
        blob_oid = repo.create_blob(bad_target)
        from gitstore.tree import rebuild_tree
        new_tree = rebuild_tree(repo, fs._tree_oid, {"bad-link": (blob_oid, GIT_FILEMODE_LINK)}, set())
        sig = store._signature
        commit_oid = repo.create_commit(
            "refs/heads/main", sig, sig, "add bad symlink", new_tree, [fs._commit_oid],
        )
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out])
        assert result.exit_code != 0
        assert "not valid UTF-8" in result.output

    def test_tar_export_non_utf8_symlink(self, runner, initialized_repo, tmp_path):
        """Non-UTF-8 symlink targets produce a clear error on tar export."""
        from gitstore import GitStore
        from gitstore.tree import GIT_FILEMODE_LINK
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        repo = store._repo
        bad_target = b"caf\xe9"
        blob_oid = repo.create_blob(bad_target)
        from gitstore.tree import rebuild_tree
        new_tree = rebuild_tree(repo, fs._tree_oid, {"bad-link": (blob_oid, GIT_FILEMODE_LINK)}, set())
        sig = store._signature
        commit_oid = repo.create_commit(
            "refs/heads/main", sig, sig, "add bad symlink", new_tree, [fs._commit_oid],
        )
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out])
        assert result.exit_code != 0
        assert "not valid UTF-8" in result.output


# ---------------------------------------------------------------------------
# TestHash
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TestBefore
# ---------------------------------------------------------------------------

class TestBefore:
    """Tests for the --before date filter."""

    def test_log_before(self, runner, initialized_repo, tmp_path):
        """--before excludes commits after the cutoff."""
        import time
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "first"])
        time.sleep(1.1)
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "second"])

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        entries = list(fs.log())
        # cutoff = time of "first" commit (second entry, since log is newest-first)
        cutoff = entries[1].time

        result = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert "second" not in result.output
        assert "first" in result.output

    def test_log_before_date_only(self, runner, repo_with_files):
        """Date-only --before: 2099-01-01 includes all; 2000-01-01 includes none."""
        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--before", "2099-01-01"
        ])
        assert result.exit_code == 0
        all_lines = result.output.strip().split("\n")
        assert len(all_lines) >= 3  # init + hello.txt + data

        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--before", "2000-01-01"
        ])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_log_before_with_path(self, runner, initialized_repo, tmp_path):
        """--before and --path combined."""
        import time
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time  # time of "add a" commit

        time.sleep(1.1)
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "update a"])

        result = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--path", "a.txt", "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "add a" in lines[0]

    def test_log_before_with_match(self, runner, initialized_repo, tmp_path):
        """--before and --match combined."""
        import time
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time

        time.sleep(1.1)
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v2"])

        result = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--match", "deploy*", "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "deploy v1" in lines[0]

    def test_zip_before(self, runner, initialized_repo, tmp_path):
        """--before exports the correct snapshot."""
        import time
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time

        time.sleep(1.1)
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, [
            "zip", "--repo", initialized_repo, out, "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "a.txt" in names
            assert "b.txt" not in names

    def test_tar_before(self, runner, initialized_repo, tmp_path):
        """--before exports the correct snapshot."""
        import tarfile
        import time
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])

        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time

        time.sleep(1.1)
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, [
            "tar", "--repo", initialized_repo, out, "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "a.txt" in names
            assert "b.txt" not in names

    def test_before_invalid_date(self, runner, repo_with_files, tmp_path):
        """Invalid --before value produces a clear error."""
        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--before", "not-a-date"
        ])
        assert result.exit_code != 0
        assert "Invalid date" in result.output

    def test_before_no_matching_commits(self, runner, repo_with_files, tmp_path):
        """--before with a very old date produces error for zip/tar."""
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, [
            "zip", "--repo", repo_with_files, out, "--before", "2000-01-01"
        ])
        assert result.exit_code != 0
        assert "No matching commits" in result.output


# ---------------------------------------------------------------------------
# TestHash
# ---------------------------------------------------------------------------

class TestHash:
    """Tests for the --ref option on read commands."""

    @staticmethod
    def _get_commit_hash(repo_path):
        """Get the full commit hash of HEAD on main."""
        from gitstore import GitStore
        store = GitStore.open(repo_path, create=False)
        fs = store.branches["main"]
        return fs.hash

    @staticmethod
    def _get_parent_hash(repo_path):
        """Get the full commit hash of HEAD~1 on main."""
        from gitstore import GitStore
        store = GitStore.open(repo_path, create=False)
        fs = store.branches["main"]
        return fs.parent.hash

    def test_cat_by_hash(self, runner, repo_with_files):
        commit_hash = self._get_commit_hash(repo_with_files)
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "hello.txt", "--ref", commit_hash
        ])
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_ls_by_hash(self, runner, repo_with_files):
        commit_hash = self._get_commit_hash(repo_with_files)
        result = runner.invoke(main, [
            "ls", "--repo", repo_with_files, "--ref", commit_hash
        ])
        assert result.exit_code == 0
        assert "hello.txt" in result.output
        assert "data" in result.output

    def test_cat_by_tag(self, runner, repo_with_files):
        # Create a tag first
        runner.invoke(main, ["tag", "--repo", repo_with_files, "create", "v1.0", "--from", "main"])
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "hello.txt", "--ref", "v1.0"
        ])
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_cat_by_short_hash(self, runner, repo_with_files):
        commit_hash = self._get_commit_hash(repo_with_files)
        short = commit_hash[:7]
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "hello.txt", "--ref", short
        ])
        # pygit2 resolves short hashes, so this should succeed
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_cp_repo_to_disk_by_hash(self, runner, repo_with_files, tmp_path):
        commit_hash = self._get_commit_hash(repo_with_files)
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":hello.txt", str(dest),
            "--ref", commit_hash
        ])
        assert result.exit_code == 0
        assert dest.read_text() == "hello world\n"

    def test_cp_dir_repo_to_disk_by_hash(self, runner, repo_with_files, tmp_path):
        commit_hash = self._get_commit_hash(repo_with_files)
        dest = tmp_path / "export"
        dest.mkdir()
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":data/", str(dest),
            "--ref", commit_hash
        ])
        assert result.exit_code == 0
        assert (dest / "data.bin").read_bytes() == b"\x00\x01\x02"

    def test_zip_by_hash(self, runner, repo_with_files, tmp_path):
        # Get hash of the commit that added hello.txt (parent of HEAD)
        parent_hash = self._get_parent_hash(repo_with_files)
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, [
            "zip", "--repo", repo_with_files, out, "--ref", parent_hash
        ])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "hello.txt" in names
            # data/ tree was added after hello.txt, so shouldn't be here
            assert "data/data.bin" not in names

    def test_tar_by_hash(self, runner, repo_with_files, tmp_path):
        import tarfile
        parent_hash = self._get_parent_hash(repo_with_files)
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, [
            "tar", "--repo", repo_with_files, out, "--ref", parent_hash
        ])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "hello.txt" in names
            assert "data/data.bin" not in names

    def test_log_by_hash(self, runner, repo_with_files):
        parent_hash = self._get_parent_hash(repo_with_files)
        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--ref", parent_hash
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        # Parent commit + init commit = at least 2, but NOT the latest commit
        assert len(lines) >= 2
        # The latest commit hash should not appear
        head_hash = self._get_commit_hash(repo_with_files)
        assert head_hash[:7] not in result.output

    def test_hash_overrides_branch(self, runner, repo_with_files):
        # Create a dev branch with different content
        runner.invoke(main, ["branch", "--repo", repo_with_files, "create", "dev", "--from", "main"])
        commit_hash = self._get_commit_hash(repo_with_files)
        # Use --branch dev but --ref pointing to main's commit
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "hello.txt",
            "-b", "dev", "--ref", commit_hash
        ])
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_hash_invalid_ref(self, runner, repo_with_files):
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "hello.txt",
            "--ref", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        ])
        assert result.exit_code != 0
        assert "Unknown ref" in result.output

    def test_cp_disk_to_repo_with_hash_error(self, runner, repo_with_files, tmp_path):
        commit_hash = self._get_commit_hash(repo_with_files)
        f = tmp_path / "new.txt"
        f.write_text("data")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, str(f), ":new.txt",
            "--ref", commit_hash
        ])
        assert result.exit_code != 0
        assert "only apply when reading from repo" in result.output


# ---------------------------------------------------------------------------
# TestArchive
# ---------------------------------------------------------------------------

class TestArchive:
    def test_archive_zip(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["archive", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "hello.txt" in names
            assert "data/data.bin" in names
            assert zf.read("hello.txt") == b"hello world\n"

    def test_archive_tar_gz(self, runner, repo_with_files, tmp_path):
        import tarfile
        out = str(tmp_path / "archive.tar.gz")
        result = runner.invoke(main, ["archive", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r:gz") as tf:
            names = tf.getnames()
            assert "hello.txt" in names
            assert "data/data.bin" in names

    def test_archive_format_override(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.dat")
        result = runner.invoke(main, [
            "archive", "--repo", repo_with_files, out, "--format", "zip"
        ])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            assert "hello.txt" in zf.namelist()

    def test_archive_stdout_requires_format(self, runner, repo_with_files):
        result = runner.invoke(main, ["archive", "--repo", repo_with_files, "-"])
        assert result.exit_code != 0
        assert "--format" in result.output

    def test_archive_unknown_extension(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.xyz")
        result = runner.invoke(main, ["archive", "--repo", repo_with_files, out])
        assert result.exit_code != 0
        assert "Cannot detect" in result.output

    def test_archive_stdout_with_format(self, runner, repo_with_files):
        result = runner.invoke(main, [
            "archive", "--repo", repo_with_files, "-", "--format", "zip"
        ])
        assert result.exit_code == 0
        zf = zipfile.ZipFile(io.BytesIO(result.output_bytes))
        assert "hello.txt" in zf.namelist()

    def test_archive_tar(self, runner, repo_with_files, tmp_path):
        import tarfile
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["archive", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "hello.txt" in names


# ---------------------------------------------------------------------------
# TestUnarchive
# ---------------------------------------------------------------------------

class TestUnarchive:
    def test_unarchive_zip(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "data.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("file1.txt", "hello")
        result = runner.invoke(main, ["unarchive", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":file1.txt"])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_unarchive_tar(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "data.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"world"
            info = tarfile.TarInfo(name="file2.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["unarchive", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":file2.txt"])
        assert result.exit_code == 0
        assert "world" in result.output

    def test_unarchive_stdin_requires_format(self, runner, initialized_repo):
        result = runner.invoke(main, ["unarchive", "--repo", initialized_repo])
        assert result.exit_code != 0
        assert "--format" in result.output

    def test_unarchive_stdin_dash_requires_format(self, runner, initialized_repo):
        result = runner.invoke(main, ["unarchive", "--repo", initialized_repo, "-"])
        assert result.exit_code != 0
        assert "--format" in result.output

    def test_unarchive_format_override(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "data.bin")
        with tarfile.open(tpath, "w") as tf:
            data = b"content"
            info = tarfile.TarInfo(name="fromtar.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, [
            "unarchive", "--repo", initialized_repo, tpath, "--format", "tar"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":fromtar.txt"])
        assert result.exit_code == 0
        assert "content" in result.output

    def test_unarchive_unknown_extension(self, runner, initialized_repo, tmp_path):
        p = tmp_path / "data.xyz"
        p.write_bytes(b"not an archive")
        result = runner.invoke(main, [
            "unarchive", "--repo", initialized_repo, str(p)
        ])
        assert result.exit_code != 0
        assert "Cannot detect" in result.output

    def test_unarchive_zip_from_stdin(self, runner, initialized_repo):
        """unarchive --format zip - reads zip from stdin."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("stdin_file.txt", "from stdin")
        zip_bytes = buf.getvalue()

        result = runner.invoke(
            main,
            ["unarchive", "--repo", initialized_repo, "--format", "zip", "-"],
            input=zip_bytes,
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":stdin_file.txt"])
        assert result.exit_code == 0
        assert "from stdin" in result.output

    def test_unarchive_custom_message(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "data.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("msg.txt", "data")
        result = runner.invoke(main, [
            "unarchive", "--repo", initialized_repo, zpath, "-m", "bulk import"
        ])
        assert result.exit_code == 0
        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "bulk import" in result.output


# ---------------------------------------------------------------------------
# cp --ignore-errors
# ---------------------------------------------------------------------------

class TestCpIgnoreErrors:
    def test_ignore_errors_prints_stderr(self, runner, repo_with_files, tmp_path):
        """Bad file + --ignore-errors -> stderr output, non-zero exit."""
        repo = repo_with_files
        good = tmp_path / "good.txt"
        good.write_text("good")
        bad = str(tmp_path / "nonexistent.txt")
        result = runner.invoke(main, [
            "cp", "--repo", repo,
            str(good), bad, ":dest",
            "--ignore-errors",
        ])
        assert result.exit_code != 0
        assert "ERROR" in result.output


# ---------------------------------------------------------------------------
# TestSync
# ---------------------------------------------------------------------------

class TestSync:
    def test_sync_1arg_disk_to_repo(self, runner, initialized_repo, tmp_path):
        """sync ./dir syncs local dir to repo root."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, str(src),
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "a.txt" in r.output
        assert "b.txt" in r.output

    def test_sync_2arg_disk_to_repo(self, runner, initialized_repo, tmp_path):
        """sync ./dir :dest syncs to a repo sub-path."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.txt").write_text("xxx")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, str(src), ":data",
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["ls", "--repo", initialized_repo, ":data"])
        assert "x.txt" in r.output

    def test_sync_2arg_repo_to_disk(self, runner, repo_with_files, tmp_path):
        """sync :data ./out syncs repo path to disk."""
        dest = tmp_path / "out"
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, ":data", str(dest),
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "data.bin").exists()

    def test_sync_deletes_extra_files(self, runner, repo_with_files, tmp_path):
        """Sync deletes files in dest not present in source."""
        # First sync repo data to disk
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "extra.txt").write_text("extra")
        (dest / "data.bin").write_bytes(b"\x00\x01\x02")
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, ":data", str(dest),
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "data.bin").exists()
        assert not (dest / "extra.txt").exists()

    def test_sync_dry_run(self, runner, initialized_repo, tmp_path):
        """-n shows plan without writing."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "new.txt").write_text("new")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", str(src),
        ])
        assert result.exit_code == 0, result.output
        assert "+" in result.output  # add action
        # Verify nothing was actually written
        r = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "new.txt" not in r.output

    def test_sync_both_local_error(self, runner, initialized_repo, tmp_path):
        """sync a b (no colon on either) errors."""
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "a", "b",
        ])
        assert result.exit_code != 0
        assert "Neither argument is a repo path" in result.output

    def test_sync_both_repo_error(self, runner, initialized_repo):
        """sync :a :b errors."""
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, ":a", ":b",
        ])
        assert result.exit_code != 0
        assert "Both arguments are repo paths" in result.output

    def test_sync_1arg_repo_error(self, runner, initialized_repo):
        """sync :path errors (1-arg must be local)."""
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, ":path",
        ])
        assert result.exit_code != 0
        assert "must be a local path" in result.output

    def test_sync_ignore_errors(self, runner, repo_with_files, tmp_path):
        """--ignore-errors works."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "good.txt").write_text("good")
        # Create an unreadable file
        bad = src / "bad.txt"
        bad.write_text("bad")
        import os
        os.chmod(str(bad), 0o000)
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, str(src), ":dest",
            "--ignore-errors",
        ])
        # Restore permissions for cleanup
        os.chmod(str(bad), 0o644)
        # good.txt should have been written
        r = runner.invoke(main, ["ls", "--repo", repo_with_files, ":dest"])
        assert "good.txt" in r.output

    def test_sync_custom_message(self, runner, initialized_repo, tmp_path):
        """-m sets commit message."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("data")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo,
            "-m", "custom sync message", str(src),
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "custom sync message" in r.output


class TestChecksumMode:
    """Tests for the mtime-based (default) vs checksum change detection."""

    def test_sync_skips_unchanged_files_default_mode(self, runner, initialized_repo, tmp_path):
        """Default mode: sync dir to repo, touch nothing, sync again → no updates."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        # Initial sync
        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Second sync with no changes — dry-run should show nothing
        r = runner.invoke(main, ["sync", "--repo", initialized_repo, "-n", str(src)])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output  # no updates
        assert "+" not in r.output  # no adds
        assert "-" not in r.output  # no deletes

    def test_sync_detects_new_mtime(self, runner, initialized_repo, tmp_path):
        """Rewriting a file (new mtime) is detected in default mode."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("original")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Rewrite the file — mtime must land in a later second
        time.sleep(1.1)
        (src / "a.txt").write_text("changed")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, "-n", str(src)])
        assert r.exit_code == 0, r.output
        assert "~" in r.output  # update detected

    def test_cp_delete_skips_unchanged_default_mode(self, runner, initialized_repo, tmp_path):
        """cp --delete: unchanged files are skipped in default (mtime) mode."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.txt").write_text("xxx")

        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "--delete",
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output

        # Dry-run again with no changes
        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "--delete", "-n",
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output

    def test_checksum_detects_backdated_change(self, runner, initialized_repo, tmp_path):
        """--checksum catches content change even when mtime is backdated."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("original")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Change content but backdate the mtime to before the commit
        (src / "a.txt").write_text("sneaky change")
        old_time = 1000000000.0  # Sep 2001
        os.utime(src / "a.txt", (old_time, old_time))

        # Default mode (mtime): misses the change
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output  # mtime mode skips it

        # --checksum mode: catches it
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", "-c", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert "~" in r.output  # checksum mode catches it

    def test_checksum_dry_run_matches_real_run(self, runner, initialized_repo, tmp_path):
        """--checksum dry-run and real-run agree on what changes."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Modify one file — mtime must land in a later second
        time.sleep(1.1)
        (src / "a.txt").write_text("AAA")

        # Dry-run with --checksum
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", "-c", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert ":a.txt" in r.output
        assert "b.txt" not in r.output

        # Real run with --checksum
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-c", str(src),
        ])
        assert r.exit_code == 0, r.output

        # Verify: now a dry-run shows no changes
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", "-c", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output
        assert "+" not in r.output

    def test_default_mode_skips_old_mtime_file(self, runner, initialized_repo, tmp_path):
        """Document the tradeoff: a file with old mtime is skipped in default mode."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("original")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Write new content but backdate mtime
        (src / "a.txt").write_text("different content")
        old_time = 946684800.0  # Jan 1 2000
        os.utime(src / "a.txt", (old_time, old_time))

        # Default mode skips it (file appears unchanged)
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, str(src),
        ])
        assert r.exit_code == 0, r.output

        # Verify the repo still has the original content
        r = runner.invoke(main, ["cat", "--repo", initialized_repo, "a.txt"])
        assert r.output == "original"

    def test_round_trip_preserves_mtime(self, runner, initialized_repo, tmp_path):
        """After repo→disk, files get commit mtime so disk→repo skips them."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        # Sync disk → repo
        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Sync repo → disk (different directory)
        dest = tmp_path / "dest"
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, ":", str(dest),
        ])
        assert r.exit_code == 0, r.output
        assert (dest / "a.txt").read_text() == "aaa"

        # Now sync that dest back to repo — should detect no changes
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", str(dest),
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output  # no updates
        assert "+" not in r.output  # no adds


# ---------------------------------------------------------------------------
# Repo-side /./  pivot
# ---------------------------------------------------------------------------

class TestCpRepoPivot:
    """CLI tests for repo→disk /./  pivot."""

    def test_cp_repo_pivot_dir(self, runner, initialized_repo, tmp_path):
        """cp :base/./sub/dir ./dest preserves sub/dir structure."""
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("base/sub/mydir/x.txt", b"xxx")
        fs.write("base/sub/mydir/y.txt", b"yyy")

        dest = tmp_path / "pivotout"
        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo,
            ":base/./sub/mydir", str(dest),
        ])
        assert r.exit_code == 0, r.output
        assert (dest / "sub" / "mydir" / "x.txt").read_text() == "xxx"
        assert (dest / "sub" / "mydir" / "y.txt").read_text() == "yyy"

    def test_cp_repo_pivot_dry_run(self, runner, initialized_repo, tmp_path):
        """cp -n :base/./sub/file.txt ./dest shows pivot structure."""
        from gitstore import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs.write("base/sub/file.txt", b"hello")

        dest = tmp_path / "pivotout"
        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "-n",
            ":base/./sub/file.txt", str(dest),
        ])
        assert r.exit_code == 0, r.output
        assert "file.txt" in r.output

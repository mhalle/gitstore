"""Tests for the gitstore CLI — cp command and related operations."""

import os

import pytest
from click.testing import CliRunner

from gitstore.cli import main


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

    def test_both_colon_repo_to_repo(self, runner, repo_with_files):
        """Both src and dest being repo paths is now valid (repo→repo copy)."""
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, ":hello.txt", ":backup/"])
        assert result.exit_code == 0, result.output
        # Verify the file was copied
        result = runner.invoke(main, ["ls", "--repo", repo_with_files, ":backup"])
        assert "hello.txt" in result.output

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
        assert "mixed" in result.output.lower() or "same type" in result.output.lower()

    def test_single_arg_error(self, runner, initialized_repo):
        result = runner.invoke(main, ["cp", "--repo", initialized_repo, ":only"])
        assert result.exit_code != 0
        assert "at least two" in result.output.lower()

    def test_custom_branch(self, runner, initialized_repo, tmp_path):
        # Create a dev branch
        runner.invoke(main, ["branch", "--repo", initialized_repo, "fork", "dev"])
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

    def test_back(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("old")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":f.txt"])
        f.write_text("new")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":f.txt"])
        # cp from --back 1 should get the old content
        dest = tmp_path / "out.txt"
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "--back", "1", ":f.txt", str(dest)
        ])
        assert result.exit_code == 0, result.output
        assert dest.read_text() == "old"


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


class TestSymlinks:
    def test_cp_repo_to_disk_symlink(self, runner, initialized_repo, tmp_path):
        """cp repo→disk creates a symlink on disk for symlink entries."""
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


class TestNonUtf8Symlink:
    def test_zip_export_non_utf8_symlink(self, runner, initialized_repo, tmp_path):
        """Non-UTF-8 symlink targets produce a clear error on zip export."""
        import zipfile
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

    def test_ls_single_file(self, runner, repo_with_files):
        result = runner.invoke(main, ["ls", "--repo", repo_with_files, ":hello.txt"])
        assert result.exit_code == 0
        assert result.output.strip() == "hello.txt"

    def test_ls_single_file_recursive(self, runner, repo_with_files):
        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_files, ":hello.txt"])
        assert result.exit_code == 0
        assert result.output.strip() == "hello.txt"


class TestExcludeCLI:
    def test_cp_exclude(self, runner, initialized_repo, tmp_path):
        """--exclude '*.pyc' skips .pyc files."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")

        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo,
            "--exclude", "*.pyc",
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "app.pyc" not in r.output

    def test_cp_exclude_multiple(self, runner, initialized_repo, tmp_path):
        """Multiple --exclude patterns all apply."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")
        (src / "debug.log").write_text("log")

        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo,
            "--exclude", "*.pyc",
            "--exclude", "*.log",
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "app.pyc" not in r.output
        assert "debug.log" not in r.output

    def test_cp_exclude_from(self, runner, initialized_repo, tmp_path):
        """--exclude-from reads patterns from file."""
        pfile = tmp_path / "excludes.txt"
        pfile.write_text("*.pyc\n*.log\n")

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")
        (src / "debug.log").write_text("log")

        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo,
            "--exclude-from", str(pfile),
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "app.pyc" not in r.output
        assert "debug.log" not in r.output

    def test_cp_exclude_repo_to_disk_error(self, runner, repo_with_files, tmp_path):
        """--exclude on repo->disk errors."""
        dest = tmp_path / "out"
        r = runner.invoke(main, [
            "cp", "--repo", repo_with_files,
            "--exclude", "*.txt",
            ":hello.txt", str(dest),
        ])
        assert r.exit_code != 0
        assert "--exclude" in r.output

    def test_sync_exclude(self, runner, initialized_repo, tmp_path):
        """--exclude on sync command."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")

        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo,
            "--exclude", "*.pyc",
            str(src),
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "app.pyc" not in r.output

    def test_sync_gitignore(self, runner, initialized_repo, tmp_path):
        """--gitignore reads .gitignore from source tree."""
        src = tmp_path / "src"
        src.mkdir()
        (src / ".gitignore").write_text("*.pyc\n__pycache__/\n")
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")
        cache = src / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-312.pyc").write_text("compiled")

        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo,
            "--gitignore",
            str(src),
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "app.pyc" not in r.output
        assert "__pycache__" not in r.output
        # .gitignore itself should be excluded
        assert ".gitignore" not in r.output

    def test_sync_gitignore_from_repo_error(self, runner, repo_with_files, tmp_path):
        """--gitignore with repo->disk errors."""
        dest = tmp_path / "out"
        r = runner.invoke(main, [
            "sync", "--repo", repo_with_files,
            "--gitignore",
            ":data", str(dest),
        ])
        assert r.exit_code != 0
        assert "--gitignore" in r.output

    def test_sync_exclude_from_repo_error(self, runner, repo_with_files, tmp_path):
        """--exclude with repo->disk sync errors."""
        dest = tmp_path / "out"
        r = runner.invoke(main, [
            "sync", "--repo", repo_with_files,
            "--exclude", "*.txt",
            ":data", str(dest),
        ])
        assert r.exit_code != 0
        assert "--exclude" in r.output

    def test_cp_exclude_with_delete(self, runner, initialized_repo, tmp_path):
        """--exclude + --delete: excluded files not copied, existing files remain."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")
        (src / "lib.py").write_text("lib")

        # First copy without exclude
        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo,
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output

        # Now sync with exclude and delete — excluded files not in enumeration,
        # so they're treated as "not in source" and get deleted
        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "--delete",
            "--exclude", "*.pyc",
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "lib.py" in r.output
        assert "app.pyc" not in r.output

    def test_sync_gitignore_dry_run(self, runner, initialized_repo, tmp_path):
        """--gitignore works with dry-run."""
        src = tmp_path / "src"
        src.mkdir()
        (src / ".gitignore").write_text("*.pyc\n")
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")

        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n",
            "--gitignore",
            str(src),
        ])
        assert r.exit_code == 0, r.output
        assert "app.py" in r.output
        assert "app.pyc" not in r.output
        assert ".gitignore" not in r.output

    def test_cp_exclude_single_file(self, runner, initialized_repo, tmp_path):
        """--exclude applies to single-file cp too."""
        f = tmp_path / "app.pyc"
        f.write_text("compiled")

        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo,
            "--exclude", "*.pyc",
            str(f), ":",
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.pyc" not in r.output

    def test_cp_exclude_glob_source(self, runner, initialized_repo, tmp_path):
        """--exclude filters files from glob-expanded sources."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("code")
        (src / "app.pyc").write_text("compiled")
        (src / "lib.py").write_text("lib")

        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo,
            "--exclude", "*.pyc",
            str(src) + "/*", ":",
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "lib.py" in r.output
        assert "app.pyc" not in r.output

    def test_sync_gitignore_nested(self, runner, initialized_repo, tmp_path):
        """Nested .gitignore is scoped to its subdirectory."""
        src = tmp_path / "src"
        src.mkdir()
        (src / ".gitignore").write_text("*.log\n")
        (src / "app.py").write_text("code")
        (src / "root.log").write_text("log")

        sub = src / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.tmp\n")
        (sub / "mod.py").write_text("code")
        (sub / "cache.tmp").write_text("tmp")
        (sub / "sub.log").write_text("log")

        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo,
            "--gitignore",
            str(src),
        ])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["ls", "--repo", initialized_repo, "-R"])
        assert "app.py" in r.output
        assert "sub/mod.py" in r.output
        # Root .gitignore excludes *.log everywhere
        assert "root.log" not in r.output
        assert "sub.log" not in r.output
        # Sub .gitignore excludes *.tmp only in sub/
        assert "cache.tmp" not in r.output
        # .gitignore files excluded
        assert ".gitignore" not in r.output


# ---------------------------------------------------------------------------
# Cross-ref and repo→repo tests
# ---------------------------------------------------------------------------

class TestCpRefPath:
    """Tests for ref:path syntax in cp command."""

    def test_repo_to_repo_same_branch(self, runner, repo_with_files):
        """cp :src :dest on same branch."""
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":hello.txt", ":backup/"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":backup/hello.txt"])
        assert result.exit_code == 0
        assert result.output == "hello world\n"

    def test_repo_to_repo_cross_branch(self, runner, repo_with_files):
        """cp main:file dev: copies from main to dev."""
        # Create dev branch
        runner.invoke(main, ["branch", "--repo", repo_with_files, "fork", "dev"])
        # Write something unique to dev
        result = runner.invoke(main, [
            "write", "--repo", repo_with_files, "-b", "dev", ":dev-only.txt"
        ], input="dev content")
        assert result.exit_code == 0, result.output
        # Copy file from main to dev
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, "main:hello.txt", "dev:"
        ])
        assert result.exit_code == 0, result.output
        # Verify it's on dev
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "-b", "dev", ":hello.txt"
        ])
        assert result.exit_code == 0
        assert result.output == "hello world\n"
        # dev-only.txt still there
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "-b", "dev", ":dev-only.txt"
        ])
        assert result.exit_code == 0
        assert result.output == "dev content"

    def test_repo_to_repo_contents_mode(self, runner, repo_with_files):
        """cp :data/ :backup/ copies contents of data into backup."""
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":data/", ":backup/"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":backup/data.bin"])
        assert result.exit_code == 0

    def test_repo_to_repo_dry_run(self, runner, repo_with_files):
        """cp -n :hello.txt :backup/ shows plan without writing."""
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":hello.txt", ":backup/", "-n"
        ])
        assert result.exit_code == 0, result.output
        assert "+" in result.output
        assert "hello.txt" in result.output
        # Verify nothing was written
        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "backup" not in result.output

    def test_repo_to_repo_delete(self, runner, repo_with_files):
        """cp --delete :src/ :dest/ removes files in dest not in src."""
        # First, copy data/ to backup/
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":data/", ":backup/"
        ])
        assert result.exit_code == 0, result.output
        # Add an extra file to backup
        result = runner.invoke(main, [
            "write", "--repo", repo_with_files, ":backup/extra.txt"
        ], input="extra")
        assert result.exit_code == 0
        # Now cp with --delete: should remove extra.txt
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":data/", ":backup/", "--delete"
        ])
        assert result.exit_code == 0, result.output
        # Verify extra.txt is gone
        result = runner.invoke(main, ["ls", "--repo", repo_with_files, ":backup"])
        assert "extra.txt" not in result.output
        assert "data.bin" in result.output

    def test_repo_to_repo_ignore_existing(self, runner, repo_with_files):
        """cp --ignore-existing :src :dest skips existing files."""
        # Write a file to backup
        result = runner.invoke(main, [
            "write", "--repo", repo_with_files, ":backup/hello.txt"
        ], input="original")
        assert result.exit_code == 0
        # Copy from root with --ignore-existing
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, ":hello.txt", ":backup/",
            "--ignore-existing"
        ])
        assert result.exit_code == 0, result.output
        # Verify original content preserved
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":backup/hello.txt"])
        assert result.output == "original"

    def test_cp_from_tag(self, runner, repo_with_files, tmp_path):
        """cp v1:file.txt ./out reads from tag."""
        # Create a tag
        result = runner.invoke(main, ["tag", "--repo", repo_with_files, "fork", "v1"])
        assert result.exit_code == 0, result.output
        # Copy from tag to disk
        out = tmp_path / "out.txt"
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, "v1:hello.txt", str(out)
        ])
        assert result.exit_code == 0, result.output
        assert out.read_text() == "hello world\n"

    def test_cp_dest_to_explicit_branch(self, runner, repo_with_files, tmp_path):
        """cp file.txt dev: writes to explicit branch."""
        # Create dev branch
        runner.invoke(main, ["branch", "--repo", repo_with_files, "fork", "dev"])
        f = tmp_path / "new.txt"
        f.write_text("new content")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, str(f), "dev:new.txt"
        ])
        assert result.exit_code == 0, result.output
        # Verify on dev
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "-b", "dev", ":new.txt"
        ])
        assert result.exit_code == 0
        assert result.output == "new content"
        # Not on main
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, ":new.txt"
        ])
        assert result.exit_code != 0

    def test_cp_write_to_tag_error(self, runner, repo_with_files, tmp_path):
        """Writing to a tag should error."""
        runner.invoke(main, ["tag", "--repo", repo_with_files, "fork", "v1"])
        f = tmp_path / "x.txt"
        f.write_text("x")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, str(f), "v1:x.txt"
        ])
        assert result.exit_code != 0
        assert "tag" in result.output.lower()

    def test_cp_write_to_ancestor_error(self, runner, repo_with_files, tmp_path):
        """Writing to ref~N should error."""
        f = tmp_path / "x.txt"
        f.write_text("x")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, str(f), "main~1:x.txt"
        ])
        assert result.exit_code != 0
        assert "historical" in result.output.lower()

    def test_cp_explicit_ref_with_flag_ref_error(self, runner, repo_with_files):
        """cp main:file ./dest --ref main is an error."""
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, "main:hello.txt", "./out", "--ref", "main"
        ])
        assert result.exit_code != 0
        assert "--ref" in result.output

    def test_cp_explicit_ref_with_branch_error(self, runner, repo_with_files, tmp_path):
        """cp file.txt main: -b dev is an error."""
        f = tmp_path / "x.txt"
        f.write_text("x")
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, str(f), "main:", "-b", "main"
        ])
        assert result.exit_code != 0
        assert "-b" in result.output or "--branch" in result.output

    def test_cp_repo_to_disk_with_back(self, runner, repo_with_files, tmp_path):
        """cp main:hello.txt ./dest --back 1 reads from one commit back."""
        f = tmp_path / "hello.txt"
        f.write_text("updated")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":hello.txt"])
        dest = tmp_path / "out"
        dest.mkdir()
        result = runner.invoke(main, [
            "cp", "--repo", repo_with_files, "main:hello.txt", str(dest), "--back", "1"
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "hello.txt").read_text() == "hello world\n"

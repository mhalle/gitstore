"""Tests for the copy module (copy_to_repo, copy_from_repo, dry_run)."""

import os

import pytest

from gitstore import GitStore, copy_to_repo, copy_from_repo
from gitstore.copy import copy_to_repo_dry_run, copy_from_repo_dry_run


@pytest.fixture
def store_and_fs(tmp_path):
    """Create a store with some files in the repo."""
    repo = GitStore.open(tmp_path / "test.git", create="main")
    fs = repo.branches["main"]
    fs = fs.write("existing.txt", b"exists")
    fs = fs.write("dir/a.txt", b"aaa")
    fs = fs.write("dir/b.txt", b"bbb")
    fs = fs.write("dir/.dotfile", b"dot")
    fs = fs.write("other/c.txt", b"ccc")
    return repo, fs, tmp_path


class TestCopyToRepoFile:
    def test_single_file(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "hello.txt"
        f.write_text("hello")
        new_fs = copy_to_repo(fs, [str(f)], "dest")
        assert new_fs.read("dest/hello.txt") == b"hello"

    def test_multiple_files(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")
        new_fs = copy_to_repo(fs, [str(f1), str(f2)], "out")
        assert new_fs.read("out/a.txt") == b"aaa"
        assert new_fs.read("out/b.txt") == b"bbb"

    def test_file_not_found(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            copy_to_repo(fs, [str(tmp_path / "nope.txt")], "dest")


class TestCopyToRepoDir:
    def test_directory_name_preserved(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "x.txt").write_text("xxx")
        (d / "y.txt").write_text("yyy")
        new_fs = copy_to_repo(fs, [str(d)], "dest")
        assert new_fs.read("dest/mydir/x.txt") == b"xxx"
        assert new_fs.read("dest/mydir/y.txt") == b"yyy"

    def test_directory_trailing_slash_contents(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "x.txt").write_text("xxx")
        new_fs = copy_to_repo(fs, [str(d) + "/"], "dest")
        # Contents mode: no "mydir" prefix
        assert new_fs.read("dest/x.txt") == b"xxx"


class TestCopyToRepoGlob:
    def test_glob_star(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "gdir"
        d.mkdir()
        (d / "a.txt").write_text("aaa")
        (d / "b.md").write_text("bbb")
        (d / ".hidden").write_text("hid")
        glob_pattern = str(d / "*.txt")
        new_fs = copy_to_repo(fs, [glob_pattern], "out")
        assert new_fs.read("out/a.txt") == b"aaa"
        assert not new_fs.exists("out/b.md")
        assert not new_fs.exists("out/.hidden")

    def test_glob_no_matches(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError, match="No matches"):
            copy_to_repo(fs, [str(tmp_path / "*.zzz")], "out")


class TestCopyFromRepoFile:
    def test_single_file(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["existing.txt"], str(out))
        assert (out / "existing.txt").read_text() == "exists"

    def test_file_not_found(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            copy_from_repo(fs, ["nope.txt"], str(tmp_path / "out"))


class TestCopyFromRepoDir:
    def test_directory_name_preserved(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["dir"], str(out))
        assert (out / "dir" / "a.txt").read_text() == "aaa"
        assert (out / "dir" / "b.txt").read_text() == "bbb"

    def test_directory_trailing_slash_contents(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["dir/"], str(out))
        assert (out / "a.txt").read_text() == "aaa"
        assert (out / "b.txt").read_text() == "bbb"
        # Dotfiles included (not a glob)
        assert (out / ".dotfile").read_text() == "dot"


class TestCopyFromRepoGlob:
    def test_glob_star(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["dir/*.txt"], str(out))
        assert (out / "a.txt").read_text() == "aaa"
        assert (out / "b.txt").read_text() == "bbb"
        # Dotfile excluded by glob
        assert not (out / ".dotfile").exists()


class TestDryRun:
    def test_to_repo_dry_run(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "dr.txt"
        f.write_text("data")
        pairs = copy_to_repo_dry_run(fs, [str(f)], "dest")
        assert len(pairs) == 1
        assert pairs[0][1] == "dest/dr.txt"
        # Original repo unchanged
        assert not fs.exists("dest/dr.txt")

    def test_from_repo_dry_run(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "drout"
        pairs = copy_from_repo_dry_run(fs, ["dir"], str(out))
        assert len(pairs) >= 2
        # Nothing written
        assert not out.exists()

    def test_to_repo_dry_run_dir(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "drd"
        d.mkdir()
        (d / "f.txt").write_text("f")
        pairs = copy_to_repo_dry_run(fs, [str(d)], "dest")
        repo_paths = [p[1] for p in pairs]
        assert "dest/drd/f.txt" in repo_paths


class TestMixed:
    def test_file_and_dir(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "single.txt"
        f.write_text("single")
        d = tmp_path / "mdir"
        d.mkdir()
        (d / "m.txt").write_text("mmm")
        new_fs = copy_to_repo(fs, [str(f), str(d)], "mix")
        assert new_fs.read("mix/single.txt") == b"single"
        assert new_fs.read("mix/mdir/m.txt") == b"mmm"

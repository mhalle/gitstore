"""Tests for the copy module (copy_to_repo, copy_from_repo, dry_run, ignore_existing, delete)."""

import os
from pathlib import Path

import pytest

from gitstore import GitStore, copy_to_repo, copy_from_repo, CopyPlan
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
        new_fs, _errs = copy_to_repo(fs, [str(f)], "dest")
        assert new_fs.read("dest/hello.txt") == b"hello"

    def test_multiple_files(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")
        new_fs, _errs = copy_to_repo(fs, [str(f1), str(f2)], "out")
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
        new_fs, _errs = copy_to_repo(fs, [str(d)], "dest")
        assert new_fs.read("dest/mydir/x.txt") == b"xxx"
        assert new_fs.read("dest/mydir/y.txt") == b"yyy"

    def test_directory_trailing_slash_contents(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "x.txt").write_text("xxx")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
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
        new_fs, _errs = copy_to_repo(fs, [glob_pattern], "out")
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
        plan = copy_to_repo_dry_run(fs, [str(f)], "dest")
        assert plan.total == 1
        assert "dr.txt" in plan.add
        # Original repo unchanged
        assert not fs.exists("dest/dr.txt")

    def test_from_repo_dry_run(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "drout"
        plan = copy_from_repo_dry_run(fs, ["dir"], str(out))
        assert plan.total >= 2
        # Nothing written
        assert not out.exists()

    def test_to_repo_dry_run_dir(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "drd"
        d.mkdir()
        (d / "f.txt").write_text("f")
        plan = copy_to_repo_dry_run(fs, [str(d)], "dest")
        assert "drd/f.txt" in plan.add

    def test_to_repo_dry_run_shows_updates(self, store_and_fs):
        """Dry run classifies existing files as updates."""
        _, fs, tmp_path = store_and_fs
        # existing.txt already in repo
        f = tmp_path / "existing.txt"
        f.write_text("new content")
        plan = copy_to_repo_dry_run(fs, [str(f)], "")
        assert "existing.txt" in plan.update
        assert plan.delete == []

    def test_from_repo_dry_run_shows_updates(self, store_and_fs):
        """Dry run classifies existing local files as updates."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "existing.txt").write_text("local")
        plan = copy_from_repo_dry_run(fs, ["existing.txt"], str(out))
        assert "existing.txt" in plan.update


class TestMixed:
    def test_file_and_dir(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "single.txt"
        f.write_text("single")
        d = tmp_path / "mdir"
        d.mkdir()
        (d / "m.txt").write_text("mmm")
        new_fs, _errs = copy_to_repo(fs, [str(f), str(d)], "mix")
        assert new_fs.read("mix/single.txt") == b"single"
        assert new_fs.read("mix/mdir/m.txt") == b"mmm"


# ---------------------------------------------------------------------------
# No-clobber tests
# ---------------------------------------------------------------------------

class TestIgnoreExisting:
    def test_ignore_existing_disk_to_repo(self, store_and_fs):
        """Existing repo file not overwritten with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "existing.txt"
        f.write_text("new content")
        new_fs, _errs = copy_to_repo(fs, [str(f)], "", ignore_existing=True)
        # Original content should be preserved
        assert new_fs.read("existing.txt") == b"exists"

    def test_ignore_existing_repo_to_disk(self, store_and_fs):
        """Existing local file not overwritten with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "existing.txt").write_text("local content")
        copy_from_repo(fs, ["existing.txt"], str(out), ignore_existing=True)
        assert (out / "existing.txt").read_text() == "local content"

    def test_ignore_existing_new_files_still_written_to_repo(self, store_and_fs):
        """Files not at dest are written even with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "brand_new.txt"
        f.write_text("new")
        new_fs, _errs = copy_to_repo(fs, [str(f)], "dest", ignore_existing=True)
        assert new_fs.read("dest/brand_new.txt") == b"new"

    def test_ignore_existing_new_files_still_written_from_repo(self, store_and_fs):
        """Files not at dest are written even with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["existing.txt"], str(out), ignore_existing=True)
        assert (out / "existing.txt").read_text() == "exists"

    def test_ignore_existing_dry_run_to_repo(self, store_and_fs):
        """Dry run shows only new files with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        # existing.txt already in repo
        f1 = tmp_path / "existing.txt"
        f1.write_text("new content")
        f2 = tmp_path / "brand_new.txt"
        f2.write_text("new")
        plan = copy_to_repo_dry_run(fs, [str(f1), str(f2)], "", ignore_existing=True)
        assert "brand_new.txt" in plan.add
        assert "existing.txt" not in plan.add
        assert plan.update == []

    def test_ignore_existing_dry_run_from_repo(self, store_and_fs):
        """Dry run shows only new files with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "existing.txt").write_text("local")
        plan = copy_from_repo_dry_run(
            fs, ["existing.txt", "dir/a.txt"], str(out), ignore_existing=True,
        )
        assert any("a.txt" in p for p in plan.add)
        assert "existing.txt" not in plan.add
        assert plan.update == []

    def test_ignore_existing_dir_to_repo(self, store_and_fs):
        """No-clobber with directory copy skips existing files."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "dir2"
        d.mkdir()
        (d / "a.txt").write_text("new aaa")
        (d / "new_file.txt").write_text("new")
        # dir/a.txt already exists in repo
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dir", ignore_existing=True)
        assert new_fs.read("dir/a.txt") == b"aaa"  # unchanged
        assert new_fs.read("dir/new_file.txt") == b"new"  # new file written


# ---------------------------------------------------------------------------
# Edge-case tests (content)
# ---------------------------------------------------------------------------

class TestCopyEdgeCases:
    def test_empty_file_to_repo(self, store_and_fs):
        """Empty file (0 bytes) copied to repo correctly."""
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        new_fs, _errs = copy_to_repo(fs, [str(f)], "dest")
        assert new_fs.read("dest/empty.txt") == b""

    def test_empty_file_from_repo(self, store_and_fs):
        """Empty file from repo copied to disk correctly."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("dest/empty.txt", b"")
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["dest/empty.txt"], str(out))
        assert (out / "empty.txt").read_bytes() == b""

    def test_binary_file_with_null_bytes(self, store_and_fs):
        """Binary file with all byte values 0-255."""
        _, fs, tmp_path = store_and_fs
        data = bytes(range(256))
        f = tmp_path / "bin.dat"
        f.write_bytes(data)
        new_fs, _errs = copy_to_repo(fs, [str(f)], "dest")
        assert new_fs.read("dest/bin.dat") == data

    def test_binary_file_from_repo(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        data = bytes(range(256))
        fs = fs.write("dest/bin.dat", data)
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["dest/bin.dat"], str(out))
        assert (out / "bin.dat").read_bytes() == data

    def test_unicode_filenames(self, store_and_fs):
        """Unicode filenames are preserved."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "unicode"
        d.mkdir()
        (d / "café.txt").write_text("coffee")
        (d / "日本語.txt").write_text("japanese")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.read("dest/café.txt") == b"coffee"
        assert new_fs.read("dest/日本語.txt") == b"japanese"

    def test_filenames_with_spaces(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "spaces"
        d.mkdir()
        (d / "my file.txt").write_text("spaces")
        sub = d / "sub dir"
        sub.mkdir()
        (sub / "inner.txt").write_text("nested")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.read("dest/my file.txt") == b"spaces"
        assert new_fs.read("dest/sub dir/inner.txt") == b"nested"

    def test_special_char_filenames(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "special"
        d.mkdir()
        (d / "file#1.txt").write_text("hash")
        (d / "file@2.txt").write_text("at")
        (d / "a=b.txt").write_text("equals")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.read("dest/file#1.txt") == b"hash"
        assert new_fs.read("dest/file@2.txt") == b"at"
        assert new_fs.read("dest/a=b.txt") == b"equals"

    def test_deep_nesting(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "deep"
        deep = d / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "f.txt").write_text("deep")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.read("dest/a/b/c/d/e/f.txt") == b"deep"


# ---------------------------------------------------------------------------
# Symlink edge-case tests
# ---------------------------------------------------------------------------

class TestCopySymlinks:
    def test_dir_symlink_preserved_to_repo(self, store_and_fs):
        """Directory symlink is preserved as a symlink entry in repo."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "withlink"
        d.mkdir()
        real = d / "real_dir"
        real.mkdir()
        (real / "file.txt").write_text("inside")
        (d / "link_dir").symlink_to("real_dir")

        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.readlink("dest/link_dir") == "real_dir"
        assert new_fs.read("dest/real_dir/file.txt") == b"inside"

    def test_file_symlink_preserved_to_repo(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "withlink"
        d.mkdir()
        (d / "target.txt").write_text("content")
        (d / "link.txt").symlink_to("target.txt")

        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.readlink("dest/link.txt") == "target.txt"

    def test_dangling_symlink_to_repo(self, store_and_fs):
        """Dangling symlinks are stored correctly."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "dangle"
        d.mkdir()
        (d / "broken").symlink_to("nonexistent_target")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.readlink("dest/broken") == "nonexistent_target"

    def test_absolute_symlink_target(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "abslink"
        d.mkdir()
        (d / "abs_link").symlink_to("/usr/bin/env")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.readlink("dest/abs_link") == "/usr/bin/env"

    def test_relative_symlink_with_dotdot(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "rellink"
        (d / "sub").mkdir(parents=True)
        (d / "sub" / "uplink").symlink_to("../sibling/file")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dest")
        assert new_fs.readlink("dest/sub/uplink") == "../sibling/file"

    def test_symlink_from_repo_to_disk(self, store_and_fs):
        """Symlinks in repo are recreated on disk."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write_symlink("links/mylink", "target.txt")
        fs = fs.write("links/target.txt", b"content")
        out = tmp_path / "output"
        out.mkdir()
        copy_from_repo(fs, ["links/"], str(out))
        assert (out / "mylink").is_symlink()
        assert os.readlink(out / "mylink") == "target.txt"


# ---------------------------------------------------------------------------
# Delete tests
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_disk_to_repo(self, store_and_fs):
        """delete=True removes repo files not in source."""
        _, fs, tmp_path = store_and_fs
        # repo already has dir/a.txt, dir/b.txt, dir/.dotfile
        d = tmp_path / "src"
        d.mkdir()
        (d / "a.txt").write_text("new aaa")
        # b.txt and .dotfile not in source → should be deleted
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dir", delete=True)
        assert new_fs.read("dir/a.txt") == b"new aaa"
        assert not new_fs.exists("dir/b.txt")
        assert not new_fs.exists("dir/.dotfile")

    def test_delete_repo_to_disk(self, store_and_fs):
        """delete=True removes local files not in source."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "existing.txt").write_text("local content")
        (out / "extra.txt").write_text("extra")
        copy_from_repo(fs, ["existing.txt"], str(out), delete=True)
        assert (out / "existing.txt").read_text() == "exists"
        assert not (out / "extra.txt").exists()

    def test_delete_skips_unchanged(self, store_and_fs):
        """delete=True does not rewrite unchanged files."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "src"
        d.mkdir()
        (d / "a.txt").write_bytes(b"aaa")
        (d / "b.txt").write_bytes(b"bbb")
        (d / ".dotfile").write_bytes(b"dot")
        # All content matches repo → should be no-op
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dir", delete=True)
        assert new_fs.hash == fs.hash  # no new commit

    def test_delete_with_ignore_existing(self, store_and_fs):
        """delete=True + ignore_existing=True: deletes extras, skips updates."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("data/keep.txt", b"keep")
        fs = fs.write("data/change.txt", b"old")
        fs = fs.write("data/extra.txt", b"extra")
        d = tmp_path / "src"
        d.mkdir()
        (d / "keep.txt").write_bytes(b"keep")
        (d / "change.txt").write_text("new")
        new_fs, _errs = copy_to_repo(
            fs, [str(d) + "/"], "data",
            delete=True, ignore_existing=True,
        )
        # extra.txt should be deleted
        assert not new_fs.exists("data/extra.txt")
        # change.txt should keep old content (ignore_existing skips updates)
        assert new_fs.read("data/change.txt") == b"old"
        # keep.txt unchanged
        assert new_fs.read("data/keep.txt") == b"keep"

    def test_delete_dry_run_plan(self, store_and_fs):
        """Dry run with delete=True returns categorized CopyPlan."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("data/keep.txt", b"keep")
        fs = fs.write("data/change.txt", b"old")
        fs = fs.write("data/extra.txt", b"extra")
        d = tmp_path / "src"
        d.mkdir()
        (d / "keep.txt").write_bytes(b"keep")
        (d / "change.txt").write_text("new")
        (d / "add.txt").write_text("added")
        plan = copy_to_repo_dry_run(fs, [str(d) + "/"], "data", delete=True)
        assert isinstance(plan, CopyPlan)
        assert "add.txt" in plan.add
        assert "change.txt" in plan.update
        assert "extra.txt" in plan.delete
        assert "keep.txt" not in plan.add + plan.update + plan.delete

    def test_delete_file_dir_conflict(self, store_and_fs):
        """delete=True handles file↔directory conflicts."""
        _, fs, tmp_path = store_and_fs
        # repo has dir/a.txt, dir/b.txt, etc.
        d = tmp_path / "src"
        d.mkdir()
        # Replace "dir" structure with completely different content
        (d / "new.txt").write_text("new")
        new_fs, _errs = copy_to_repo(fs, [str(d) + "/"], "dir", delete=True)
        assert new_fs.read("dir/new.txt") == b"new"
        assert not new_fs.exists("dir/a.txt")
        assert not new_fs.exists("dir/b.txt")

    def test_delete_from_repo_prunes_empty_dirs(self, store_and_fs):
        """delete=True from repo prunes empty directories after deletion."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        sub = out / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "old.txt").write_text("old")
        copy_from_repo(fs, ["existing.txt"], str(out), delete=True)
        assert (out / "existing.txt").read_text() == "exists"
        assert not (out / "sub").exists()

    def test_delete_from_repo_dry_run(self, store_and_fs):
        """Dry run with delete=True from repo returns CopyPlan."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "extra.txt").write_text("extra")
        plan = copy_from_repo_dry_run(fs, ["existing.txt"], str(out), delete=True)
        assert isinstance(plan, CopyPlan)
        assert "existing.txt" in plan.add
        assert "extra.txt" in plan.delete


# ---------------------------------------------------------------------------
# ignore_errors tests
# ---------------------------------------------------------------------------

class TestIgnoreErrors:
    def test_ignore_errors_bad_source_continues(self, store_and_fs):
        """One good source + one bad source: good one copied, error returned."""
        _, fs, tmp_path = store_and_fs
        good = tmp_path / "good.txt"
        good.write_text("good")
        bad = str(tmp_path / "nonexistent.txt")
        new_fs, errs = copy_to_repo(
            fs, [str(good), bad], "dest", ignore_errors=True,
        )
        assert new_fs.read("dest/good.txt") == b"good"
        assert len(errs) == 1
        assert "nonexistent" in errs[0].path

    def test_ignore_errors_unreadable_file_continues(self, store_and_fs):
        """chmod 000 a file; others still copied to repo."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "mixed"
        d.mkdir()
        (d / "ok.txt").write_text("ok")
        bad = d / "nope.txt"
        bad.write_text("secret")
        bad.chmod(0o000)
        try:
            new_fs, errs = copy_to_repo(
                fs, [str(d) + "/"], "dest", ignore_errors=True,
            )
            assert new_fs.read("dest/ok.txt") == b"ok"
            assert len(errs) == 1
            assert "nope.txt" in errs[0].path
        finally:
            bad.chmod(0o644)

    def test_ignore_errors_all_fail_raises(self, store_and_fs):
        """All sources bad -> RuntimeError even with ignore_errors=True."""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(RuntimeError, match="All files failed"):
            copy_to_repo(
                fs, [str(tmp_path / "nope1"), str(tmp_path / "nope2")],
                "dest", ignore_errors=True,
            )

    def test_ignore_errors_default_raises(self, store_and_fs):
        """Default behavior unchanged — immediate raise on bad source."""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            copy_to_repo(fs, [str(tmp_path / "nope.txt")], "dest")

    def test_ignore_errors_success_empty_errors(self, store_and_fs):
        """All succeed -> errors == []."""
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "ok.txt"
        f.write_text("ok")
        new_fs, errs = copy_to_repo(
            fs, [str(f)], "dest", ignore_errors=True,
        )
        assert errs == []
        assert new_fs.read("dest/ok.txt") == b"ok"

    def test_ignore_errors_from_repo_write_fail(self, store_and_fs):
        """Read-only dest dir; error returned for from_repo."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "readonly_out"
        out.mkdir()
        out.chmod(0o444)
        try:
            errs = copy_from_repo(
                fs, ["existing.txt"], str(out), ignore_errors=True,
            )
            assert len(errs) >= 1
        finally:
            out.chmod(0o755)

    def test_ignore_errors_from_repo_all_fail_raises(self, store_and_fs):
        """All sources bad from repo -> RuntimeError."""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(RuntimeError, match="All files failed"):
            copy_from_repo(
                fs, ["nonexistent1", "nonexistent2"],
                str(tmp_path / "out"), ignore_errors=True,
            )

    def test_ignore_errors_delete_phase(self, store_and_fs):
        """Delete fails (permission), error collected in from_repo."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "deltest"
        out.mkdir()
        # Create a file that can't be deleted (read-only parent)
        sub = out / "sub"
        sub.mkdir()
        (sub / "locked.txt").write_text("locked")
        sub.chmod(0o555)
        try:
            errs = copy_from_repo(
                fs, ["existing.txt"], str(out),
                delete=True, ignore_errors=True,
            )
            # The locked file should appear in errors
            assert any("locked" in e.path for e in errs)
            # The good file should still be written
            assert (out / "existing.txt").read_text() == "exists"
        finally:
            sub.chmod(0o755)

"""Tests for the copy module (copy_in, copy_out, dry_run, ignore_existing, delete)."""

import os
from pathlib import Path

import pytest

from gitstore import GitStore, ChangeReport, FileEntry
from gitstore.copy._resolve import _expand_disk_glob


def paths(entries):
    """Extract paths from FileEntry list for easier testing."""
    if entries is None:
        return set()
    return {e.path for e in entries}


@pytest.fixture
def store_and_fs(tmp_path):
    """Create a store with some files in the repo."""
    repo = GitStore.open(tmp_path / "test.git")
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
        new_fs = fs.copy_in([str(f)], "dest")
        assert new_fs.read("dest/hello.txt") == b"hello"

    def test_multiple_files(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")
        new_fs = fs.copy_in([str(f1), str(f2)], "out")
        assert new_fs.read("out/a.txt") == b"aaa"
        assert new_fs.read("out/b.txt") == b"bbb"

    def test_file_not_found(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            fs.copy_in([str(tmp_path / "nope.txt")], "dest")


class TestCopyToRepoDir:
    def test_directory_name_preserved(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "x.txt").write_text("xxx")
        (d / "y.txt").write_text("yyy")
        new_fs = fs.copy_in([str(d)], "dest")
        assert new_fs.read("dest/mydir/x.txt") == b"xxx"
        assert new_fs.read("dest/mydir/y.txt") == b"yyy"

    def test_directory_trailing_slash_contents(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "x.txt").write_text("xxx")
        new_fs = fs.copy_in([str(d) + "/"], "dest")
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
        new_fs = fs.copy_in([glob_pattern], "out")
        assert new_fs.read("out/a.txt") == b"aaa"
        assert not new_fs.exists("out/b.md")
        assert not new_fs.exists("out/.hidden")

    def test_glob_no_matches(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError, match="No matches"):
            fs.copy_in([str(tmp_path / "*.zzz")], "out")


class TestCopyFromRepoFile:
    def test_single_file(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["existing.txt"], str(out))
        assert (out / "existing.txt").read_text() == "exists"

    def test_file_not_found(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            fs.copy_out(["nope.txt"], str(tmp_path / "out"))


class TestCopyFromRepoDir:
    def test_directory_name_preserved(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["dir"], str(out))
        assert (out / "dir" / "a.txt").read_text() == "aaa"
        assert (out / "dir" / "b.txt").read_text() == "bbb"

    def test_directory_trailing_slash_contents(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["dir/"], str(out))
        assert (out / "a.txt").read_text() == "aaa"
        assert (out / "b.txt").read_text() == "bbb"
        # Dotfiles included (not a glob)
        assert (out / ".dotfile").read_text() == "dot"


class TestCopyFromRepoGlob:
    def test_glob_star(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["dir/*.txt"], str(out))
        assert (out / "a.txt").read_text() == "aaa"
        assert (out / "b.txt").read_text() == "bbb"
        # Dotfile excluded by glob
        assert not (out / ".dotfile").exists()


class TestDryRun:
    def test_to_repo_dry_run(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "dr.txt"
        f.write_text("data")
        plan = fs.copy_in([str(f)], "dest", dry_run=True).changes
        assert plan.total == 1
        assert "dr.txt" in paths(plan.add)
        # Original repo unchanged
        assert not fs.exists("dest/dr.txt")

    def test_from_repo_dry_run(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "drout"
        plan = fs.copy_out(["dir"], str(out), dry_run=True).changes
        assert plan.total >= 2
        # Nothing written
        assert not out.exists()

    def test_to_repo_dry_run_dir(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "drd"
        d.mkdir()
        (d / "f.txt").write_text("f")
        plan = fs.copy_in([str(d)], "dest", dry_run=True).changes
        assert "drd/f.txt" in paths(plan.add)

    def test_to_repo_dry_run_shows_updates(self, store_and_fs):
        """Dry run classifies existing files as updates."""
        _, fs, tmp_path = store_and_fs
        # existing.txt already in repo
        f = tmp_path / "existing.txt"
        f.write_text("new content")
        plan = fs.copy_in([str(f)], "", dry_run=True).changes
        assert "existing.txt" in paths(plan.update)
        assert len(plan.delete) == 0

    def test_from_repo_dry_run_shows_updates(self, store_and_fs):
        """Dry run classifies existing local files as updates."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "existing.txt").write_text("local")
        plan = fs.copy_out(["existing.txt"], str(out), dry_run=True).changes
        assert "existing.txt" in paths(plan.update)


class TestMixed:
    def test_file_and_dir(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "single.txt"
        f.write_text("single")
        d = tmp_path / "mdir"
        d.mkdir()
        (d / "m.txt").write_text("mmm")
        new_fs = fs.copy_in([str(f), str(d)], "mix")
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
        new_fs = fs.copy_in([str(f)], "", ignore_existing=True)
        # Original content should be preserved
        assert new_fs.read("existing.txt") == b"exists"

    def test_ignore_existing_repo_to_disk(self, store_and_fs):
        """Existing local file not overwritten with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "existing.txt").write_text("local content")
        fs.copy_out(["existing.txt"], str(out), ignore_existing=True)
        assert (out / "existing.txt").read_text() == "local content"

    def test_ignore_existing_new_files_still_written_to_repo(self, store_and_fs):
        """Files not at dest are written even with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "brand_new.txt"
        f.write_text("new")
        new_fs = fs.copy_in([str(f)], "dest", ignore_existing=True)
        assert new_fs.read("dest/brand_new.txt") == b"new"

    def test_ignore_existing_new_files_still_written_from_repo(self, store_and_fs):
        """Files not at dest are written even with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["existing.txt"], str(out), ignore_existing=True)
        assert (out / "existing.txt").read_text() == "exists"

    def test_ignore_existing_dry_run_to_repo(self, store_and_fs):
        """Dry run shows only new files with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        # existing.txt already in repo
        f1 = tmp_path / "existing.txt"
        f1.write_text("new content")
        f2 = tmp_path / "brand_new.txt"
        f2.write_text("new")
        plan = fs.copy_in([str(f1), str(f2)], "", ignore_existing=True, dry_run=True).changes
        assert "brand_new.txt" in paths(plan.add)
        assert "existing.txt" not in paths(plan.add)
        assert len(plan.update) == 0

    def test_ignore_existing_dry_run_from_repo(self, store_and_fs):
        """Dry run shows only new files with ignore_existing."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "existing.txt").write_text("local")
        result = fs.copy_out(
            ["existing.txt", "dir/a.txt"], str(out), ignore_existing=True,
            dry_run=True,
        )
        plan = result.changes
        assert any("a.txt" in p for p in paths(plan.add))
        assert "existing.txt" not in paths(plan.add)
        assert len(plan.update) == 0

    def test_ignore_existing_dir_to_repo(self, store_and_fs):
        """No-clobber with directory copy skips existing files."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "dir2"
        d.mkdir()
        (d / "a.txt").write_text("new aaa")
        (d / "new_file.txt").write_text("new")
        # dir/a.txt already exists in repo
        new_fs = fs.copy_in([str(d) + "/"], "dir", ignore_existing=True)
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
        new_fs = fs.copy_in([str(f)], "dest")
        assert new_fs.read("dest/empty.txt") == b""

    def test_empty_file_from_repo(self, store_and_fs):
        """Empty file from repo copied to disk correctly."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("dest/empty.txt", b"")
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["dest/empty.txt"], str(out))
        assert (out / "empty.txt").read_bytes() == b""

    def test_binary_file_with_null_bytes(self, store_and_fs):
        """Binary file with all byte values 0-255."""
        _, fs, tmp_path = store_and_fs
        data = bytes(range(256))
        f = tmp_path / "bin.dat"
        f.write_bytes(data)
        new_fs = fs.copy_in([str(f)], "dest")
        assert new_fs.read("dest/bin.dat") == data

    def test_binary_file_from_repo(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        data = bytes(range(256))
        fs = fs.write("dest/bin.dat", data)
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["dest/bin.dat"], str(out))
        assert (out / "bin.dat").read_bytes() == data

    def test_unicode_filenames(self, store_and_fs):
        """Unicode filenames are preserved."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "unicode"
        d.mkdir()
        (d / "café.txt").write_text("coffee")
        (d / "日本語.txt").write_text("japanese")
        new_fs = fs.copy_in([str(d) + "/"], "dest")
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
        new_fs = fs.copy_in([str(d) + "/"], "dest")
        assert new_fs.read("dest/my file.txt") == b"spaces"
        assert new_fs.read("dest/sub dir/inner.txt") == b"nested"

    def test_special_char_filenames(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "special"
        d.mkdir()
        (d / "file#1.txt").write_text("hash")
        (d / "file@2.txt").write_text("at")
        (d / "a=b.txt").write_text("equals")
        new_fs = fs.copy_in([str(d) + "/"], "dest")
        assert new_fs.read("dest/file#1.txt") == b"hash"
        assert new_fs.read("dest/file@2.txt") == b"at"
        assert new_fs.read("dest/a=b.txt") == b"equals"

    def test_deep_nesting(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "deep"
        deep = d / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "f.txt").write_text("deep")
        new_fs = fs.copy_in([str(d) + "/"], "dest")
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

        new_fs = fs.copy_in([str(d) + "/"], "dest")
        assert new_fs.readlink("dest/link_dir") == "real_dir"
        assert new_fs.read("dest/real_dir/file.txt") == b"inside"

    def test_file_symlink_preserved_to_repo(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "withlink"
        d.mkdir()
        (d / "target.txt").write_text("content")
        (d / "link.txt").symlink_to("target.txt")

        new_fs = fs.copy_in([str(d) + "/"], "dest")
        assert new_fs.readlink("dest/link.txt") == "target.txt"

    def test_dangling_symlink_to_repo(self, store_and_fs):
        """Dangling symlinks are stored correctly."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "dangle"
        d.mkdir()
        (d / "broken").symlink_to("nonexistent_target")
        new_fs = fs.copy_in([str(d) + "/"], "dest")
        assert new_fs.readlink("dest/broken") == "nonexistent_target"

    def test_absolute_symlink_target(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "abslink"
        d.mkdir()
        (d / "abs_link").symlink_to("/usr/bin/env")
        new_fs = fs.copy_in([str(d) + "/"], "dest")
        assert new_fs.readlink("dest/abs_link") == "/usr/bin/env"

    def test_relative_symlink_with_dotdot(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "rellink"
        (d / "sub").mkdir(parents=True)
        (d / "sub" / "uplink").symlink_to("../sibling/file")
        new_fs = fs.copy_in([str(d) + "/"], "dest")
        assert new_fs.readlink("dest/sub/uplink") == "../sibling/file"

    def test_symlink_from_repo_to_disk(self, store_and_fs):
        """Symlinks in repo are recreated on disk."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write_symlink("links/mylink", "target.txt")
        fs = fs.write("links/target.txt", b"content")
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["links/"], str(out))
        assert (out / "mylink").is_symlink()
        assert os.readlink(out / "mylink") == "target.txt"


class TestFollowSymlinksDeleteMode:
    """follow_symlinks=True in delete mode must hash content, not link targets."""

    def test_follow_symlinks_no_perpetual_update(self, store_and_fs):
        """Symlinked file with follow_symlinks=True shouldn't cause perpetual updates."""
        _, fs, tmp_path = store_and_fs
        local = tmp_path / "src"
        local.mkdir()
        target = tmp_path / "target.txt"
        target.write_text("content")
        (local / "link.txt").symlink_to(str(target))
        (local / "regular.txt").write_text("regular")

        fs1 = fs.copy_in([str(local) + "/"], "data",
                            follow_symlinks=True, delete=True)
        # Content should be stored, not symlink target
        assert fs1.read("data/link.txt") == b"content"

        # Second sync should find no changes
        plan = fs1.copy_in([str(local) + "/"], "data",
                           follow_symlinks=True, delete=True,
                           dry_run=True).changes
        assert plan is None

    def test_follow_symlinks_content_change_detected(self, store_and_fs):
        """With follow_symlinks=True, changing the target file is detected."""
        _, fs, tmp_path = store_and_fs
        local = tmp_path / "src"
        local.mkdir()
        target = tmp_path / "target.txt"
        target.write_text("version1")
        (local / "link.txt").symlink_to(str(target))

        fs1 = fs.copy_in([str(local) + "/"], "data",
                            follow_symlinks=True, delete=True)

        # Change the target content
        target.write_text("version2")

        plan = fs1.copy_in([str(local) + "/"], "data",
                           follow_symlinks=True, delete=True,
                           dry_run=True).changes
        assert plan is not None
        assert "link.txt" in paths(plan.update)


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
        new_fs = fs.copy_in([str(d) + "/"], "dir", delete=True)
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
        fs.copy_out(["existing.txt"], str(out), delete=True)
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
        new_fs = fs.copy_in([str(d) + "/"], "dir", delete=True)
        assert new_fs.commit_hash == fs.commit_hash  # no new commit

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
        new_fs = fs.copy_in(
            [str(d) + "/"], "data",
            delete=True, ignore_existing=True,
        )
        # extra.txt should be deleted
        assert not new_fs.exists("data/extra.txt")
        # change.txt should keep old content (ignore_existing skips updates)
        assert new_fs.read("data/change.txt") == b"old"
        # keep.txt unchanged
        assert new_fs.read("data/keep.txt") == b"keep"

    def test_delete_dry_run_plan(self, store_and_fs):
        """Dry run with delete=True returns categorized ChangeReport."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("data/keep.txt", b"keep")
        fs = fs.write("data/change.txt", b"old")
        fs = fs.write("data/extra.txt", b"extra")
        d = tmp_path / "src"
        d.mkdir()
        (d / "keep.txt").write_bytes(b"keep")
        (d / "change.txt").write_text("new")
        (d / "add.txt").write_text("added")
        plan = fs.copy_in([str(d) + "/"], "data", delete=True, dry_run=True).changes
        assert isinstance(plan, ChangeReport)
        assert "add.txt" in paths(plan.add)
        assert "change.txt" in paths(plan.update)
        assert "extra.txt" in paths(plan.delete)
        all_paths = paths(plan.add) | paths(plan.update) | paths(plan.delete)
        assert "keep.txt" not in all_paths

    def test_delete_file_dir_conflict(self, store_and_fs):
        """delete=True handles file↔directory conflicts."""
        _, fs, tmp_path = store_and_fs
        # repo has dir/a.txt, dir/b.txt, etc.
        d = tmp_path / "src"
        d.mkdir()
        # Replace "dir" structure with completely different content
        (d / "new.txt").write_text("new")
        new_fs = fs.copy_in([str(d) + "/"], "dir", delete=True)
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
        fs.copy_out(["existing.txt"], str(out), delete=True)
        assert (out / "existing.txt").read_text() == "exists"
        assert not (out / "sub").exists()

    def test_delete_from_repo_dry_run(self, store_and_fs):
        """Dry run with delete=True from repo returns ChangeReport."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "extra.txt").write_text("extra")
        plan = fs.copy_out(["existing.txt"], str(out), delete=True, dry_run=True).changes
        assert isinstance(plan, ChangeReport)
        assert "existing.txt" in paths(plan.add)
        assert "extra.txt" in paths(plan.delete)


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
        new_fs = fs.copy_in(
            [str(good), bad], "dest", ignore_errors=True,
        )
        changes = new_fs.changes
        assert new_fs.read("dest/good.txt") == b"good"
        assert len(changes.errors) == 1
        assert "nonexistent" in changes.errors[0].path

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
            new_fs = fs.copy_in(
                [str(d) + "/"], "dest", ignore_errors=True,
            )
            changes = new_fs.changes
            assert new_fs.read("dest/ok.txt") == b"ok"
            assert len(changes.errors) == 1
            assert "nope.txt" in changes.errors[0].path
        finally:
            bad.chmod(0o644)

    def test_ignore_errors_all_fail_raises(self, store_and_fs):
        """All sources bad -> RuntimeError even with ignore_errors=True."""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(RuntimeError, match="All files failed"):
            fs.copy_in(
                [str(tmp_path / "nope1"), str(tmp_path / "nope2")],
                "dest", ignore_errors=True,
            )

    def test_ignore_errors_default_raises(self, store_and_fs):
        """Default behavior unchanged — immediate raise on bad source."""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            fs.copy_in([str(tmp_path / "nope.txt")], "dest")

    def test_ignore_errors_success_no_errors(self, store_and_fs):
        """All succeed -> changes has no errors."""
        _, fs, tmp_path = store_and_fs
        f = tmp_path / "ok.txt"
        f.write_text("ok")
        new_fs = fs.copy_in(
            [str(f)], "dest", ignore_errors=True,
        )
        changes = new_fs.changes
        assert changes is not None
        assert changes.errors == []
        assert new_fs.read("dest/ok.txt") == b"ok"

    def test_ignore_errors_from_repo_write_fail(self, store_and_fs):
        """Read-only dest dir; all writes fail -> RuntimeError."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "readonly_out"
        out.mkdir()
        out.chmod(0o444)
        try:
            with pytest.raises(RuntimeError, match="All files failed"):
                fs.copy_out(
                    ["existing.txt"], str(out), ignore_errors=True,
                )
        finally:
            out.chmod(0o755)

    def test_ignore_errors_from_repo_all_fail_raises(self, store_and_fs):
        """All sources bad from repo -> RuntimeError."""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(RuntimeError, match="All files failed"):
            fs.copy_out(
                ["nonexistent1", "nonexistent2"],
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
            result = fs.copy_out(
                ["existing.txt"], str(out),
                delete=True, ignore_errors=True,
            )
            changes = result.changes
            assert changes is not None
            # The locked file should appear in errors
            assert any("locked" in e.path for e in changes.errors)
            # The good file should still be written
            assert (out / "existing.txt").read_text() == "exists"
        finally:
            sub.chmod(0o755)


# ---------------------------------------------------------------------------
# Fix 2: ignore_errors + delete + all fail should not delete destination
# ---------------------------------------------------------------------------

class TestIgnoreErrorsDeleteAllFail:
    def test_copy_to_repo_ignore_errors_delete_all_fail_no_delete(self, store_and_fs):
        """All sources invalid with ignore_errors=True, delete=True → raises,
        destination unchanged."""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(RuntimeError, match="All files failed"):
            fs.copy_in(
                [str(tmp_path / "nope1"), str(tmp_path / "nope2")],
                "dir",
                ignore_errors=True,
                delete=True,
            )
        # Original repo content untouched
        assert fs.read("dir/a.txt") == b"aaa"
        assert fs.read("dir/b.txt") == b"bbb"

    def test_copy_from_repo_ignore_errors_delete_all_fail_no_delete(self, store_and_fs):
        """All repo sources invalid with ignore_errors=True, delete=True → raises,
        local files unchanged."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        (out / "precious.txt").write_text("precious")
        with pytest.raises(RuntimeError, match="All files failed"):
            fs.copy_out(
                ["nonexistent1", "nonexistent2"],
                str(out),
                ignore_errors=True,
                delete=True,
            )
        # Local file untouched
        assert (out / "precious.txt").read_text() == "precious"


# ---------------------------------------------------------------------------
# Fix 3: Hash computation not covered by ignore_errors
# ---------------------------------------------------------------------------

class TestHashUnreadableIgnoreErrors:
    def test_copy_to_repo_delete_hash_unreadable_ignore_errors(self, store_and_fs):
        """Unreadable local file during hash comparison with ignore_errors=True
        completes with error recorded."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "src"
        d.mkdir()
        (d / "a.txt").write_bytes(b"new aaa")  # different content → real update
        (d / "b.txt").write_bytes(b"bbb")
        bad = d / ".dotfile"
        bad.write_bytes(b"dot")
        bad.chmod(0o000)
        try:
            new_fs = fs.copy_in(
                [str(d) + "/"], "dir",
                delete=True, ignore_errors=True,
            )
            changes = new_fs.changes
            assert changes is not None
            # The unreadable file should appear in errors
            assert any(".dotfile" in e.path for e in changes.errors)
            # Other files should be synced
            assert new_fs.read("dir/a.txt") == b"new aaa"
        finally:
            bad.chmod(0o644)

    def test_copy_from_repo_delete_hash_unreadable_ignore_errors(self, store_and_fs):
        """Unreadable local file during hash in copy_from_repo with ignore_errors
        completes with error recorded."""
        _, fs, tmp_path = store_and_fs
        out = tmp_path / "output"
        out.mkdir()
        existing = out / "existing.txt"
        existing.write_bytes(b"exists")
        existing.chmod(0o000)
        try:
            result = fs.copy_out(
                ["existing.txt"], str(out),
                delete=True, ignore_errors=True,
            )
            changes = result.changes
            assert changes is not None
            # The unreadable file should appear in errors
            assert any("existing.txt" in e.path for e in changes.errors)
        finally:
            existing.chmod(0o644)


# ---------------------------------------------------------------------------
# Fix 4: follow_symlinks=False doesn't handle source dir symlink
# ---------------------------------------------------------------------------

class TestSourceDirSymlinkNoFollow:
    def test_copy_to_repo_source_is_dir_symlink_no_follow(self, store_and_fs):
        """Source is a symlink to a directory; with follow_symlinks=False,
        the repo gets a symlink entry, not the directory contents."""
        _, fs, tmp_path = store_and_fs
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("inside")

        link = tmp_path / "link_to_dir"
        link.symlink_to(str(real_dir))

        new_fs = fs.copy_in(
            [str(link)], "dest", follow_symlinks=False,
        )
        # Should be stored as a symlink, not as directory contents
        assert new_fs.readlink("dest/link_to_dir") == str(real_dir)
        assert not new_fs.exists("dest/link_to_dir/file.txt")


# ---------------------------------------------------------------------------
# Fix 5: Disk globbing cross-platform
# ---------------------------------------------------------------------------

class TestExpandDiskGlobCrossPlatform:
    def test_expand_disk_glob_with_backslash_patterns(self, tmp_path):
        """_expand_disk_glob normalizes os.sep in patterns."""
        d = tmp_path / "globtest"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "b.txt").write_text("b")

        # Use forward-slash pattern (always works)
        result = _expand_disk_glob(str(d) + "/*.txt")
        assert len(result) == 2

        # Simulate what would happen with os.sep-based pattern
        pattern = os.path.join(str(d), "*.txt")
        result2 = _expand_disk_glob(pattern)
        assert len(result2) == 2
        assert sorted(result) == sorted(result2)


# ---------------------------------------------------------------------------
# Fix 6: Overlapping sources warns
# ---------------------------------------------------------------------------

class TestOverlappingSources:
    def test_copy_to_repo_overlapping_sources_warns(self, store_and_fs):
        """Two sources resolve to same dest; first wins, warning in warnings."""
        _, fs, tmp_path = store_and_fs
        # Create two different files with the same basename
        d1 = tmp_path / "dir1"
        d1.mkdir()
        (d1 / "same.txt").write_text("first")

        d2 = tmp_path / "dir2"
        d2.mkdir()
        (d2 / "same.txt").write_text("second")

        new_fs = fs.copy_in(
            [str(d1 / "same.txt"), str(d2 / "same.txt")],
            "dest",
            delete=True,
        )
        changes = new_fs.changes
        # First source wins
        assert new_fs.read("dest/same.txt") == b"first"
        # Overlap warning in warnings (not errors)
        assert changes is not None
        assert any("Overlapping" in w.error for w in changes.warnings)
        assert changes.errors == []

    def test_copy_from_repo_overlapping_sources_warns(self, store_and_fs):
        """Overlapping sources in from_repo go to warnings, not errors."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("dir/a.txt", b"aaa")
        fs = fs.write("other/a.txt", b"other")
        out = tmp_path / "output"
        out.mkdir()
        # dir/ and other/ both have a.txt → overlapping destination
        result = fs.copy_out(
            ["dir/", "other/"], str(out), delete=True,
        )
        changes = result.changes
        assert changes is not None
        assert any("Overlapping" in w.error for w in changes.warnings)
        assert changes.errors == []

    def test_copy_to_repo_dry_run_overlapping_sources_warns(self, store_and_fs):
        """Dry run with overlapping sources puts warnings in changes.warnings."""
        _, fs, tmp_path = store_and_fs
        d1 = tmp_path / "dir1"
        d1.mkdir()
        (d1 / "same.txt").write_text("first")
        d2 = tmp_path / "dir2"
        d2.mkdir()
        (d2 / "same.txt").write_text("second")
        result = fs.copy_in(
            [str(d1 / "same.txt"), str(d2 / "same.txt")],
            "dest",
            delete=True, dry_run=True,
        )
        changes = result.changes
        assert changes is not None
        assert any("Overlapping" in w.error for w in changes.warnings)


# ---------------------------------------------------------------------------
# Fix B2: repo_files built from pair_map not pairs
# ---------------------------------------------------------------------------

class TestCopyFromRepoDuplicateSources:
    def test_copy_from_repo_delete_duplicate_sources_consistent(self, store_and_fs):
        """Overlapping repo sources: hash comparison uses the correct (first) source."""
        _, fs, tmp_path = store_and_fs
        # Two repo files mapping to the same local relative path
        fs = fs.write("dir/shared.txt", b"from_dir")
        fs = fs.write("other/shared.txt", b"from_other")
        out = tmp_path / "output"
        out.mkdir()
        # Pre-populate with content matching "dir/shared.txt"
        (out / "shared.txt").write_bytes(b"from_dir")

        # dir/ is listed first → pair_map["shared.txt"] = "dir/shared.txt"
        result = fs.copy_out(
            ["dir/", "other/"], str(out), delete=True,
        )
        changes = result.changes
        assert changes is not None
        # "shared.txt" should NOT be in update (content matches first source)
        assert "shared.txt" not in paths(changes.update)
        # The overlap warning should be present
        assert any("Overlapping" in w.error for w in changes.warnings)

    def test_copy_from_repo_dry_run_delete_duplicate_sources_consistent(self, store_and_fs):
        """Dry-run with overlapping repo sources deduplicates and warns."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("dir/shared.txt", b"from_dir")
        fs = fs.write("other/shared.txt", b"from_other")
        out = tmp_path / "output"
        out.mkdir()
        (out / "shared.txt").write_bytes(b"from_dir")

        result = fs.copy_out(
            ["dir/", "other/"], str(out), delete=True,
            dry_run=True,
        )
        changes = result.changes
        assert changes is not None
        # "shared.txt" should NOT be in update (content matches first source)
        assert "shared.txt" not in paths(changes.update)
        # The overlap warning should be present
        assert any("Overlapping" in w.error for w in changes.warnings)


# ---------------------------------------------------------------------------
# Fix B3: Contents-mode symlinked dir follows symlink
# ---------------------------------------------------------------------------

class TestContentsModeSymlinkedDir:
    def test_copy_to_repo_contents_mode_symlinked_dir_follows(self, store_and_fs):
        """Contents mode ('symlink_dir/') follows symlink to walk dir contents."""
        _, fs, tmp_path = store_and_fs
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("inside")
        (real_dir / "sub").mkdir()
        (real_dir / "sub" / "nested.txt").write_text("nested")

        link = tmp_path / "link_to_dir"
        link.symlink_to(str(real_dir))

        # Contents mode: trailing slash → walk contents, even though base is a symlink
        new_fs = fs.copy_in(
            [str(link) + "/"], "dest", follow_symlinks=False,
        )
        assert new_fs.read("dest/file.txt") == b"inside"
        assert new_fs.read("dest/sub/nested.txt") == b"nested"

    def test_copy_to_repo_dir_mode_symlink_still_preserved(self, store_and_fs):
        """Dir mode (no trailing slash) still preserves symlink when not following."""
        _, fs, tmp_path = store_and_fs
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("inside")

        link = tmp_path / "link_to_dir"
        link.symlink_to(str(real_dir))

        # Dir mode (no trailing slash): symlink stored as symlink entry
        new_fs = fs.copy_in(
            [str(link)], "dest", follow_symlinks=False,
        )
        assert new_fs.readlink("dest/link_to_dir") == str(real_dir)


# ---------------------------------------------------------------------------
# ChangeReport: return None when empty
# ---------------------------------------------------------------------------

class TestChangeReportNone:
    def test_copy_to_repo_returns_none_when_no_changes(self, store_and_fs):
        """copy_to_repo returns None changes when already in sync."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "src"
        d.mkdir()
        (d / "a.txt").write_bytes(b"aaa")
        (d / "b.txt").write_bytes(b"bbb")
        (d / ".dotfile").write_bytes(b"dot")
        new_fs = fs.copy_in([str(d) + "/"], "dir", delete=True)
        changes = new_fs.changes
        assert changes is None
        assert new_fs.commit_hash == fs.commit_hash

    def test_copy_to_repo_dry_run_returns_none_when_in_sync(self, store_and_fs):
        """copy_to_repo_dry_run returns None when already in sync."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "src"
        d.mkdir()
        (d / "a.txt").write_bytes(b"aaa")
        (d / "b.txt").write_bytes(b"bbb")
        (d / ".dotfile").write_bytes(b"dot")
        changes = fs.copy_in([str(d) + "/"], "dir", delete=True, dry_run=True).changes
        assert changes is None


# ---------------------------------------------------------------------------
# /./  pivot (rsync -R style)
# ---------------------------------------------------------------------------

class TestCopyToRepoPivot:
    """Test the /./  pivot marker for preserving partial source paths."""

    def test_pivot_directory(self, store_and_fs):
        """cp /base/./sub/dir :dest → dest/sub/dir/..."""
        _, fs, tmp_path = store_and_fs
        base = tmp_path / "base" / "sub" / "mydir"
        base.mkdir(parents=True)
        (base / "x.txt").write_text("xxx")
        (base / "y.txt").write_text("yyy")
        src = str(tmp_path / "base") + "/./sub/mydir"
        new_fs = fs.copy_in([src], "dest")
        assert new_fs.read("dest/sub/mydir/x.txt") == b"xxx"
        assert new_fs.read("dest/sub/mydir/y.txt") == b"yyy"

    def test_pivot_contents(self, store_and_fs):
        """cp /base/./sub/dir/ :dest → dest/sub/..."""
        _, fs, tmp_path = store_and_fs
        base = tmp_path / "base" / "sub" / "mydir"
        base.mkdir(parents=True)
        (base / "a.txt").write_text("aaa")
        (base / "b.txt").write_text("bbb")
        src = str(tmp_path / "base") + "/./sub/mydir/"
        new_fs = fs.copy_in([src], "dest")
        assert new_fs.read("dest/sub/a.txt") == b"aaa"
        assert new_fs.read("dest/sub/b.txt") == b"bbb"

    def test_pivot_file(self, store_and_fs):
        """cp /base/./sub/file.txt :dest → dest/sub/file.txt"""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "base" / "sub"
        d.mkdir(parents=True)
        (d / "file.txt").write_text("hello")
        src = str(tmp_path / "base") + "/./sub/file.txt"
        new_fs = fs.copy_in([src], "dest")
        assert new_fs.read("dest/sub/file.txt") == b"hello"

    def test_leading_dot_slash_not_pivot(self, store_and_fs):
        """cp ./mydir :dest → dest/mydir/... (no pivot)"""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "z.txt").write_text("zzz")
        # Use a relative path starting with ./
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            new_fs = fs.copy_in(["./mydir"], "dest")
        finally:
            os.chdir(orig_cwd)
        assert new_fs.read("dest/mydir/z.txt") == b"zzz"

    def test_pivot_not_found(self, store_and_fs):
        """cp /nope/./foo :dest → FileNotFoundError"""
        _, fs, tmp_path = store_and_fs
        src = str(tmp_path / "nope") + "/./foo"
        with pytest.raises(FileNotFoundError):
            fs.copy_in([src], "dest")

    def test_pivot_dry_run(self, store_and_fs):
        """dry-run produces correct plan with pivot paths."""
        _, fs, tmp_path = store_and_fs
        base = tmp_path / "base" / "sub" / "mydir"
        base.mkdir(parents=True)
        (base / "p.txt").write_text("ppp")
        src = str(tmp_path / "base") + "/./sub/mydir"
        changes = fs.copy_in([src], "dest", dry_run=True).changes
        assert changes is not None
        assert paths(changes.add) == {"sub/mydir/p.txt"}

    def test_pivot_file_trailing_slash_error(self, store_and_fs):
        """cp /base/./file.txt/ :dest → NotADirectoryError"""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "base"
        d.mkdir(parents=True)
        (d / "file.txt").write_text("hello")
        src = str(d) + "/./file.txt/"
        with pytest.raises(NotADirectoryError):
            fs.copy_in([src], "dest")

    @pytest.mark.skipif(os.sep == "/", reason="backslash pivot only on Windows")
    def test_pivot_backslash_normalization(self, store_and_fs):
        """base\\.\\sub\\file normalised to forward slashes before pivot."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "base" / "sub"
        d.mkdir(parents=True)
        (d / "file.txt").write_text("hi")
        src = str(tmp_path / "base") + "\\.\\sub\\file.txt"
        new_fs = fs.copy_in([src], "dest")
        assert new_fs.read("dest/sub/file.txt") == b"hi"

    def test_pivot_with_glob(self, store_and_fs):
        """base/./sub/*.txt expands glob and preserves pivot prefix."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "base" / "sub"
        d.mkdir(parents=True)
        (d / "a.txt").write_text("aaa")
        (d / "b.txt").write_text("bbb")
        (d / "c.py").write_text("ccc")
        src = str(tmp_path / "base") + "/./sub/*.txt"
        new_fs = fs.copy_in([src], "dest")
        assert new_fs.read("dest/sub/a.txt") == b"aaa"
        assert new_fs.read("dest/sub/b.txt") == b"bbb"
        assert not new_fs.exists("dest/sub/c.py")

    def test_pivot_with_glob_recursive(self, store_and_fs):
        """base/./**/*.py expands recursive glob with pivot prefix."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "base"
        d.mkdir(parents=True)
        (d / "x.py").write_text("x")
        pkg = d / "pkg"
        pkg.mkdir()
        (pkg / "y.py").write_text("y")
        src = str(tmp_path / "base") + "/./**/*.py"
        new_fs = fs.copy_in([src], "dest")
        assert new_fs.read("dest/x.py") == b"x"
        assert new_fs.read("dest/pkg/y.py") == b"y"

    def test_pivot_with_glob_no_match(self, store_and_fs):
        """base/./sub/*.xyz raises FileNotFoundError when nothing matches."""
        _, fs, tmp_path = store_and_fs
        d = tmp_path / "base" / "sub"
        d.mkdir(parents=True)
        (d / "a.txt").write_text("aaa")
        src = str(tmp_path / "base") + "/./sub/*.xyz"
        with pytest.raises(FileNotFoundError):
            fs.copy_in([src], "dest")


# ---------------------------------------------------------------------------
# /./  pivot (rsync -R style) — repo → disk
# ---------------------------------------------------------------------------

class TestCopyFromRepoPivot:
    """Test the /./  pivot marker for repo → disk copies."""

    def test_pivot_directory(self, store_and_fs):
        """cp :src/./sub/dir ./dest → dest/sub/dir/..."""
        _, fs, tmp_path = store_and_fs
        # repo has: dir/a.txt, dir/b.txt
        out = tmp_path / "output"
        out.mkdir()
        # Use pivot: "dir" is the base, "a.txt" etc are inside
        # First set up a deeper structure in the repo
        fs = fs.write("base/sub/mydir/x.txt", b"xxx")
        fs = fs.write("base/sub/mydir/y.txt", b"yyy")
        fs.copy_out(["base/./sub/mydir"], str(out))
        assert (out / "sub" / "mydir" / "x.txt").read_text() == "xxx"
        assert (out / "sub" / "mydir" / "y.txt").read_text() == "yyy"

    def test_pivot_contents(self, store_and_fs):
        """cp :src/./sub/dir/ ./dest → dest/sub/..."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/sub/mydir/a.txt", b"aaa")
        fs = fs.write("base/sub/mydir/b.txt", b"bbb")
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["base/./sub/mydir/"], str(out))
        assert (out / "sub" / "a.txt").read_text() == "aaa"
        assert (out / "sub" / "b.txt").read_text() == "bbb"

    def test_pivot_file(self, store_and_fs):
        """cp :src/./sub/file.txt ./dest → dest/sub/file.txt"""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/sub/file.txt", b"hello")
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["base/./sub/file.txt"], str(out))
        assert (out / "sub" / "file.txt").read_text() == "hello"

    def test_leading_dot_slash_not_pivot(self, store_and_fs):
        """./dir has no pivot — behaves as normal relative path."""
        _, fs, tmp_path = store_and_fs
        # "./dir" starts with ./ so idx=0, not > 0 — no pivot
        # But repo paths don't start with ./ anyway; this just tests
        # that the function doesn't crash on edge cases.
        # The repo "dir" already exists in the fixture.
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["dir"], str(out))
        assert (out / "dir" / "a.txt").read_text() == "aaa"

    def test_pivot_dry_run(self, store_and_fs):
        """dry-run produces correct plan with pivot paths."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/sub/mydir/p.txt", b"ppp")
        out = tmp_path / "output"
        changes = fs.copy_out(["base/./sub/mydir"], str(out), dry_run=True).changes
        assert changes is not None
        assert paths(changes.add) == {"sub/mydir/p.txt"}

    def test_pivot_not_found(self, store_and_fs):
        """cp :nope/./foo ./dest → FileNotFoundError"""
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            fs.copy_out(["nope/./foo"], str(tmp_path / "out"))

    def test_pivot_file_trailing_slash_error(self, store_and_fs):
        """cp :base/./file.txt/ ./dest → NotADirectoryError"""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/file.txt", b"hello")
        out = tmp_path / "output"
        out.mkdir()
        with pytest.raises(NotADirectoryError):
            fs.copy_out(["base/./file.txt/"], str(out))

    def test_pivot_backslash_normalization(self, store_and_fs):
        """base\\.\\sub/file.txt normalised (repo paths, cross-platform)."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/sub/file.txt", b"hi")
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["base\\.\\sub/file.txt"], str(out))
        assert (out / "sub" / "file.txt").read_text() == "hi"

    def test_pivot_with_glob(self, store_and_fs):
        """base/./sub/*.txt expands glob and preserves pivot prefix."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/sub/a.txt", b"aaa")
        fs = fs.write("base/sub/b.txt", b"bbb")
        fs = fs.write("base/sub/c.py", b"ccc")
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["base/./sub/*.txt"], str(out))
        assert (out / "sub" / "a.txt").read_text() == "aaa"
        assert (out / "sub" / "b.txt").read_text() == "bbb"
        assert not (out / "sub" / "c.py").exists()

    def test_pivot_with_glob_recursive(self, store_and_fs):
        """base/./**/*.py expands recursive glob with pivot prefix."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/x.py", b"x")
        fs = fs.write("base/pkg/y.py", b"y")
        out = tmp_path / "output"
        out.mkdir()
        fs.copy_out(["base/./**/*.py"], str(out))
        assert (out / "x.py").read_text() == "x"
        assert (out / "pkg" / "y.py").read_text() == "y"

    def test_pivot_with_glob_no_match(self, store_and_fs):
        """base/./sub/*.xyz raises FileNotFoundError when nothing matches."""
        _, fs, tmp_path = store_and_fs
        fs = fs.write("base/sub/a.txt", b"aaa")
        out = tmp_path / "output"
        out.mkdir()
        with pytest.raises(FileNotFoundError):
            fs.copy_out(["base/./sub/*.xyz"], str(out))


# ---------------------------------------------------------------------------
# TestRemoveFromRepo
# ---------------------------------------------------------------------------

class TestRemoveFromRepo:
    def test_remove_single_file(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        new_fs = fs.remove(["existing.txt"])
        assert not new_fs.exists("existing.txt")
        assert new_fs.exists("dir/a.txt")

    def test_remove_glob(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        new_fs = fs.remove(["dir/*.txt"])
        assert not new_fs.exists("dir/a.txt")
        assert not new_fs.exists("dir/b.txt")
        # dotfiles are not matched by *
        assert new_fs.exists("dir/.dotfile")

    def test_remove_glob_recursive(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        new_fs = fs.remove(["**/*.txt"])
        assert not new_fs.exists("existing.txt")
        assert not new_fs.exists("dir/a.txt")
        assert not new_fs.exists("dir/b.txt")
        assert not new_fs.exists("other/c.txt")
        # dotfile still there
        assert new_fs.exists("dir/.dotfile")

    def test_remove_directory_requires_recursive(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(IsADirectoryError):
            fs.remove(["dir"])

    def test_remove_directory_recursive(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        new_fs = fs.remove(["dir"], recursive=True)
        assert not new_fs.exists("dir/a.txt")
        assert not new_fs.exists("dir/b.txt")
        assert not new_fs.exists("dir/.dotfile")
        assert new_fs.exists("existing.txt")

    def test_remove_no_match(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            fs.remove(["nonexistent.xyz"])

    def test_remove_dry_run(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        changes = fs.remove(["existing.txt"], dry_run=True).changes
        assert changes is not None
        assert paths(changes.delete) == {"existing.txt"}
        # FS is unchanged
        assert fs.exists("existing.txt")

    def test_remove_multiple_patterns(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        new_fs = fs.remove(["existing.txt", "other/c.txt"])
        assert not new_fs.exists("existing.txt")
        assert not new_fs.exists("other/c.txt")
        assert new_fs.exists("dir/a.txt")

    def test_remove_report_attached(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        new_fs = fs.remove(["existing.txt"])
        changes = new_fs.changes
        assert changes is not None
        assert paths(changes.delete) == {"existing.txt"}
        assert not changes.add
        assert not changes.update

    def test_remove_glob_no_match(self, store_and_fs):
        _, fs, tmp_path = store_and_fs
        with pytest.raises(FileNotFoundError):
            fs.remove(["*.xyz"])

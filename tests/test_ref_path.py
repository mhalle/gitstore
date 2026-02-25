"""Tests for ref:path parsing, validation, and CLI integration."""

import pytest
import click

from vost.cli import main
from vost.cli._helpers import RefPath, _parse_ref_path
from vost.repo import _validate_ref_name


class TestParseRefPath:
    """Tests for _parse_ref_path()."""

    def test_local_plain_file(self):
        rp = _parse_ref_path("file.txt")
        assert rp == RefPath(ref=None, back=0, path="file.txt")
        assert not rp.is_repo

    def test_repo_colon_prefix(self):
        rp = _parse_ref_path(":file.txt")
        assert rp == RefPath(ref="", back=0, path="file.txt")
        assert rp.is_repo

    def test_repo_colon_only(self):
        rp = _parse_ref_path(":")
        assert rp == RefPath(ref="", back=0, path="")
        assert rp.is_repo

    def test_explicit_ref(self):
        rp = _parse_ref_path("main:file.txt")
        assert rp == RefPath(ref="main", back=0, path="file.txt")
        assert rp.is_repo

    def test_explicit_ref_empty_path(self):
        rp = _parse_ref_path("main:")
        assert rp == RefPath(ref="main", back=0, path="")
        assert rp.is_repo

    def test_ref_with_dot_in_name(self):
        rp = _parse_ref_path("v1.0:data/file")
        assert rp == RefPath(ref="v1.0", back=0, path="data/file")

    def test_ancestor_suffix(self):
        rp = _parse_ref_path("main~3:file.txt")
        assert rp == RefPath(ref="main", back=3, path="file.txt")

    def test_ancestor_on_tag(self):
        rp = _parse_ref_path("v1.0~1:data/")
        assert rp == RefPath(ref="v1.0", back=1, path="data/")

    def test_ancestor_no_ref_name(self):
        """~3:file.txt → current branch, 3 back."""
        rp = _parse_ref_path("~3:file.txt")
        assert rp == RefPath(ref="", back=3, path="file.txt")

    def test_windows_drive_with_slash(self):
        rp = _parse_ref_path("C:/Users/foo")
        assert rp == RefPath(ref=None, back=0, path="C:/Users/foo")

    def test_windows_drive_with_backslash(self):
        rp = _parse_ref_path("C:\\Users\\foo")
        assert rp == RefPath(ref=None, back=0, path="C:\\Users\\foo")

    def test_single_letter_no_slash_is_ref(self):
        """D:file → repo ref 'D', not a drive letter (no slash after colon)."""
        rp = _parse_ref_path("D:file")
        assert rp == RefPath(ref="D", back=0, path="file")

    def test_slash_before_colon_is_local(self):
        rp = _parse_ref_path("path/to:rest")
        assert rp == RefPath(ref=None, back=0, path="path/to:rest")

    def test_dot_slash_before_colon_is_local(self):
        rp = _parse_ref_path("./local:file")
        assert rp == RefPath(ref=None, back=0, path="./local:file")

    def test_backslash_before_colon_is_local(self):
        rp = _parse_ref_path("path\\to:rest")
        assert rp == RefPath(ref=None, back=0, path="path\\to:rest")

    def test_invalid_tilde_non_numeric(self):
        with pytest.raises(click.ClickException, match="must be a positive integer"):
            _parse_ref_path("main~abc:f")

    def test_invalid_tilde_zero(self):
        with pytest.raises(click.ClickException, match="~0"):
            _parse_ref_path("main~0:f")

    def test_empty_string(self):
        rp = _parse_ref_path("")
        assert rp == RefPath(ref=None, back=0, path="")

    def test_large_ancestor(self):
        rp = _parse_ref_path("main~100:path")
        assert rp == RefPath(ref="main", back=100, path="path")

    def test_multiple_colons_first_wins(self):
        """Only the first colon is the split point; subsequent colons are in the path."""
        rp = _parse_ref_path("ref:path:with:colons")
        assert rp == RefPath(ref="ref", back=0, path="path:with:colons")

    def test_tilde_in_path_not_in_ref(self):
        """Tilde after the colon is just part of the path."""
        rp = _parse_ref_path("main:dir/file~backup")
        assert rp == RefPath(ref="main", back=0, path="dir/file~backup")

    def test_ancestor_current_branch_empty_path(self):
        rp = _parse_ref_path("~3:")
        assert rp == RefPath(ref="", back=3, path="")


class TestValidateRefName:
    """Tests for _validate_ref_name()."""

    def test_valid_name(self):
        _validate_ref_name("main")  # no error

    def test_colon_rejected(self):
        with pytest.raises(ValueError, match="colon"):
            _validate_ref_name("my:branch")

    def test_space_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("my branch")

    def test_tab_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("my\tbranch")

    def test_newline_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("my\nbranch")

    def test_valid_with_dots_and_slashes(self):
        _validate_ref_name("feature/my-thing.v2")  # no error

    def test_dotdot_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("..foo")

    def test_lock_suffix_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("foo.lock")

    def test_at_brace_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("foo@{bar}")

    def test_tilde_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("foo~1")

    def test_caret_rejected(self):
        with pytest.raises(ValueError, match="Invalid ref name"):
            _validate_ref_name("foo^2")


# ---------------------------------------------------------------------------
# CLI integration tests for ref:path syntax
# ---------------------------------------------------------------------------

class TestRefPath:
    """Integration tests for ref:path syntax across commands."""

    def test_ls_explicit_ref(self, runner, repo_with_files):
        """ls main:path lists from specific branch."""
        r = runner.invoke(main, ["ls", "--repo", repo_with_files, "main:"])
        assert r.exit_code == 0, r.output
        assert "hello.txt" in r.output

    def test_ls_multiple_refs(self, runner, repo_with_files):
        """ls from multiple refs in one call."""
        # Create dev branch with a unique file
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        runner.invoke(main, [
            "write", "--repo", repo_with_files, "-b", "dev", ":dev.txt"
        ], input="dev")
        # List from both branches
        r = runner.invoke(main, [
            "ls", "--repo", repo_with_files, "main:", "dev:"
        ])
        assert r.exit_code == 0, r.output
        assert "hello.txt" in r.output
        assert "dev.txt" in r.output

    def test_cat_explicit_ref(self, runner, repo_with_files):
        """cat main:file reads from specific branch."""
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "main:hello.txt"])
        assert r.exit_code == 0
        assert r.output == "hello world\n"

    def test_cat_from_tag(self, runner, repo_with_files):
        """cat v1:file reads from tag."""
        runner.invoke(main, ["tag", "--repo", repo_with_files, "set", "v1"])
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "v1:hello.txt"])
        assert r.exit_code == 0
        assert r.output == "hello world\n"

    def test_cat_ancestor(self, runner, repo_with_files, tmp_path):
        """cat ~1:file reads from one commit back."""
        # Write new content
        f = tmp_path / "hello.txt"
        f.write_text("updated content")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":hello.txt"])
        # Read current
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":hello.txt"])
        assert r.output == "updated content"
        # Read ancestor
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "~1:hello.txt"])
        assert r.exit_code == 0
        assert r.output == "hello world\n"

    def test_rm_explicit_ref(self, runner, repo_with_files):
        """rm dev:file removes from specific branch."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        runner.invoke(main, [
            "write", "--repo", repo_with_files, "-b", "dev", ":dev.txt"
        ], input="dev")
        r = runner.invoke(main, ["rm", "--repo", repo_with_files, "dev:dev.txt"])
        assert r.exit_code == 0, r.output
        # Verify gone from dev
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "dev:dev.txt"])
        assert r.exit_code != 0

    def test_write_explicit_ref(self, runner, repo_with_files):
        """write dev:file writes to specific branch."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        r = runner.invoke(main, [
            "write", "--repo", repo_with_files, "dev:new.txt"
        ], input="new content")
        assert r.exit_code == 0, r.output
        # Verify on dev
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "dev:new.txt"])
        assert r.output == "new content"
        # Not on main
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":new.txt"])
        assert r.exit_code != 0

    def test_write_ancestor_error(self, runner, repo_with_files):
        """write ~1:file should error."""
        r = runner.invoke(main, [
            "write", "--repo", repo_with_files, "~1:file.txt"
        ], input="data")
        assert r.exit_code != 0
        assert "historical" in r.output.lower()

    def test_log_positional_ref_path(self, runner, repo_with_files, tmp_path):
        """log main:hello.txt filters by both ref and path."""
        f = tmp_path / "hello.txt"
        f.write_text("updated")
        runner.invoke(main, [
            "cp", "--repo", repo_with_files, str(f), ":hello.txt", "-m", "update hello"
        ])
        r = runner.invoke(main, ["log", "--repo", repo_with_files, "main:hello.txt"])
        assert r.exit_code == 0, r.output
        assert "update hello" in r.output

    def test_log_positional_ancestor(self, runner, repo_with_files, tmp_path):
        """log ~1: starts from one commit back."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":a.txt", "-m", "add a"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":a.txt", "-m", "update a"])
        r = runner.invoke(main, ["log", "--repo", repo_with_files, "~1:"])
        assert r.exit_code == 0, r.output
        # Should not include "update a" (the latest commit)
        assert "update a" not in r.output

    def test_log_conflict_error(self, runner, repo_with_files):
        """log ref:path + --ref should error."""
        r = runner.invoke(main, [
            "log", "--repo", repo_with_files, "main:", "--ref", "main"
        ])
        assert r.exit_code != 0
        assert "positional ref" in r.output.lower() or "Cannot specify" in r.output

    def test_diff_positional_ancestor(self, runner, repo_with_files, tmp_path):
        """diff ~1: shows changes from one commit back."""
        f = tmp_path / "new.txt"
        f.write_text("new")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":new.txt"])
        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "~1:"])
        assert r.exit_code == 0, r.output
        assert "A  new.txt" in r.output

    def test_diff_positional_ref(self, runner, repo_with_files):
        """diff dev: compares HEAD vs dev branch."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        # Modify main
        runner.invoke(main, [
            "write", "--repo", repo_with_files, ":unique.txt"
        ], input="main-only")
        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "dev:"])
        assert r.exit_code == 0, r.output
        assert "A  unique.txt" in r.output

    def test_sync_repo_to_repo_cross_branch(self, runner, repo_with_files):
        """sync main: dev: syncs content from main to dev."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        # Add file to main
        runner.invoke(main, [
            "write", "--repo", repo_with_files, ":sync-test.txt"
        ], input="synced")
        # Sync main -> dev
        r = runner.invoke(main, [
            "sync", "--repo", repo_with_files, "main:", "dev:"
        ])
        assert r.exit_code == 0, r.output
        # Verify on dev
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "dev:sync-test.txt"])
        assert r.exit_code == 0
        assert r.output == "synced"

    def test_sync_repo_to_repo_deletes(self, runner, repo_with_files):
        """sync repo->repo deletes files in dest not in source."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        # Add unique file to dev
        runner.invoke(main, [
            "write", "--repo", repo_with_files, "-b", "dev", ":dev-only.txt"
        ], input="dev")
        # Sync main -> dev (should delete dev-only.txt)
        r = runner.invoke(main, [
            "sync", "--repo", repo_with_files, "main:", "dev:"
        ])
        assert r.exit_code == 0, r.output
        # dev-only.txt should be gone
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "dev:dev-only.txt"])
        assert r.exit_code != 0

    def test_validate_ref_name_colon(self, runner, repo_with_files):
        """Creating a branch with ':' in the name should fail."""
        r = runner.invoke(main, [
            "branch", "--repo", repo_with_files, "set", "bad:name"
        ])
        assert r.exit_code != 0
        assert "colon" in r.output.lower() or "Invalid ref" in r.output

    def test_validate_ref_name_space(self, runner, repo_with_files):
        """Creating a branch with space in the name should fail."""
        r = runner.invoke(main, [
            "branch", "--repo", repo_with_files, "set", "bad name"
        ])
        assert r.exit_code != 0
        assert "space" in r.output.lower() or "Invalid ref" in r.output

    # ---- Conflict detection tests ----

    def test_ls_explicit_ref_with_flag_ref_error(self, runner, repo_with_files):
        """ls main:path --ref xxx is an error."""
        r = runner.invoke(main, [
            "ls", "--repo", repo_with_files, "main:", "--ref", "main"
        ])
        assert r.exit_code != 0
        assert "--ref" in r.output

    def test_ls_explicit_ref_with_branch_error(self, runner, repo_with_files):
        """ls main:path -b dev is an error."""
        r = runner.invoke(main, [
            "ls", "--repo", repo_with_files, "main:", "-b", "main"
        ])
        assert r.exit_code != 0
        assert "-b" in r.output or "--branch" in r.output

    def test_cat_tilde_with_back_error(self, runner, repo_with_files, tmp_path):
        """cat main~1:file --back 1 is an error."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":a.txt"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":a.txt"])
        r = runner.invoke(main, [
            "cat", "--repo", repo_with_files, "~1:a.txt", "--back", "1"
        ])
        assert r.exit_code != 0
        assert "--back" in r.output or "~N" in r.output

    def test_ls_multiple_different_refs_with_filter_error(self, runner, repo_with_files):
        """ls main:x dev:y --back 1 is an error (different refs + filter)."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        r = runner.invoke(main, [
            "ls", "--repo", repo_with_files, "main:", "dev:", "--back", "1"
        ])
        assert r.exit_code != 0
        assert "different refs" in r.output.lower() or "snapshot filters" in r.output.lower()

    def test_ls_same_ref_with_back_ok(self, runner, repo_with_files, tmp_path):
        """ls main:path --back 1 works (filters apply to explicit ref)."""
        # Add a file, then another, so there are 2 commits
        f = tmp_path / "v1.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":v1.txt"])
        f2 = tmp_path / "v2.txt"
        f2.write_text("v2")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f2), ":v2.txt"])
        # ls main: --back 1 should show v1.txt but not v2.txt
        r = runner.invoke(main, [
            "ls", "--repo", repo_with_files, "main:", "--back", "1"
        ])
        assert r.exit_code == 0, r.output
        assert "v1.txt" in r.output
        assert "v2.txt" not in r.output

    def test_cat_explicit_ref_with_back(self, runner, repo_with_files, tmp_path):
        """cat main:hello.txt --back 1 reads from one commit back on main."""
        f = tmp_path / "hello.txt"
        f.write_text("updated")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":hello.txt"])
        # Current content
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "main:hello.txt"])
        assert r.output == "updated"
        # One back
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "main:hello.txt", "--back", "1"])
        assert r.exit_code == 0, r.output
        assert r.output == "hello world\n"

    def test_log_explicit_ref_with_branch_error(self, runner, repo_with_files):
        """log main: -b dev is an error."""
        r = runner.invoke(main, [
            "log", "--repo", repo_with_files, "main:", "-b", "main"
        ])
        assert r.exit_code != 0
        assert "-b" in r.output or "--branch" in r.output

    def test_diff_explicit_ref_with_branch_error(self, runner, repo_with_files):
        """diff dev: -b main is an error."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        r = runner.invoke(main, [
            "diff", "--repo", repo_with_files, "dev:", "-b", "main"
        ])
        assert r.exit_code != 0
        assert "-b" in r.output or "--branch" in r.output

    def test_sync_explicit_ref_with_back(self, runner, repo_with_files, tmp_path):
        """sync main: ./dest --back 1 syncs from one commit back on main."""
        f = tmp_path / "extra.txt"
        f.write_text("extra")
        runner.invoke(main, ["cp", "--repo", repo_with_files, str(f), ":extra.txt"])
        dest = tmp_path / "out"
        dest.mkdir()
        r = runner.invoke(main, [
            "sync", "--repo", repo_with_files, "main:", str(dest), "--back", "1"
        ])
        assert r.exit_code == 0, r.output
        assert (dest / "hello.txt").exists()
        assert not (dest / "extra.txt").exists()  # one back = before extra.txt was added


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
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
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
        result = runner.invoke(main, ["tag", "--repo", repo_with_files, "set", "v1"])
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
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
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
        runner.invoke(main, ["tag", "--repo", repo_with_files, "set", "v1"])
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


class TestMv:
    """Integration tests for the mv command."""

    def test_rename_file(self, runner, repo_with_files):
        """mv :old :new renames a file."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt", ":renamed.txt"
        ])
        assert result.exit_code == 0, result.output
        # renamed.txt exists
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":renamed.txt"])
        assert r.exit_code == 0
        assert r.output == "hello world\n"
        # hello.txt gone
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":hello.txt"])
        assert r.exit_code != 0

    def test_move_into_directory(self, runner, repo_with_files):
        """mv :file :dir/ moves file into directory."""
        # Create dest dir with a file first
        runner.invoke(main, [
            "write", "--repo", repo_with_files, ":archive/placeholder.txt"
        ], input="x")
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt", ":archive/"
        ])
        assert result.exit_code == 0, result.output
        # File moved into archive/
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":archive/hello.txt"])
        assert r.exit_code == 0
        assert r.output == "hello world\n"
        # Original gone
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":hello.txt"])
        assert r.exit_code != 0

    def test_move_multiple_into_dir(self, runner, repo_with_files):
        """mv :a :b :dir/ moves multiple files."""
        # Add another file
        runner.invoke(main, [
            "write", "--repo", repo_with_files, ":extra.txt"
        ], input="extra")
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt", ":extra.txt", ":archive/"
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":archive/hello.txt"])
        assert r.exit_code == 0
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":archive/extra.txt"])
        assert r.exit_code == 0
        # Originals gone
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":hello.txt"])
        assert r.exit_code != 0
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":extra.txt"])
        assert r.exit_code != 0

    def test_move_directory_recursive(self, runner, repo_with_files):
        """mv -R :dir :newdir renames a directory."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, "-R", ":data", ":newdata"
        ])
        assert result.exit_code == 0, result.output
        # File exists under new name
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":newdata/data.bin"])
        assert r.exit_code == 0
        # Old dir gone
        r = runner.invoke(main, ["ls", "--repo", repo_with_files, ":newdata"])
        assert r.exit_code == 0
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":data/data.bin"])
        assert r.exit_code != 0

    def test_move_glob(self, runner, repo_with_tree):
        """mv ':*.txt' :archive/ moves glob matches."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_tree, ":*.txt", ":archive/"
        ])
        assert result.exit_code == 0, result.output
        # readme.txt moved to archive/
        r = runner.invoke(main, ["cat", "--repo", repo_with_tree, ":archive/readme.txt"])
        assert r.exit_code == 0
        assert r.output == "readme"
        # Original gone
        r = runner.invoke(main, ["cat", "--repo", repo_with_tree, ":readme.txt"])
        assert r.exit_code != 0
        # Non-txt files still in place
        r = runner.invoke(main, ["cat", "--repo", repo_with_tree, ":setup.py"])
        assert r.exit_code == 0

    def test_dry_run(self, runner, repo_with_files):
        """mv -n shows plan without executing."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, "-n", ":hello.txt", ":renamed.txt"
        ])
        assert result.exit_code == 0, result.output
        assert "+" in result.output
        assert "renamed.txt" in result.output
        assert "-" in result.output
        assert "hello.txt" in result.output
        # Verify nothing changed
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":hello.txt"])
        assert r.exit_code == 0

    def test_source_equals_dest_error(self, runner, repo_with_files):
        """mv :file :file is an error."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt", ":hello.txt"
        ])
        assert result.exit_code != 0
        assert "same" in result.output.lower()

    def test_nonexistent_source_error(self, runner, repo_with_files):
        """mv :missing :dest errors."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":missing.txt", ":dest.txt"
        ])
        assert result.exit_code != 0

    def test_directory_without_recursive_error(self, runner, repo_with_files):
        """mv :dir :newdir without -R errors."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":data", ":newdata"
        ])
        assert result.exit_code != 0
        assert "-R" in result.output or "recursive" in result.output.lower()

    def test_local_path_rejected(self, runner, repo_with_files):
        """mv without colon prefix errors."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, "hello.txt", ":dest.txt"
        ])
        assert result.exit_code != 0
        assert "colon" in result.output.lower() or "repo path" in result.output.lower()

    def test_explicit_ref(self, runner, repo_with_files):
        """mv dev:old.txt dev:new.txt works on explicit branch."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        runner.invoke(main, [
            "write", "--repo", repo_with_files, "-b", "dev", ":devfile.txt"
        ], input="dev content")
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, "dev:devfile.txt", "dev:renamed.txt"
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "dev:renamed.txt"])
        assert r.exit_code == 0
        assert r.output == "dev content"

    def test_cross_branch_error(self, runner, repo_with_files):
        """mv main:file dev:file is an error."""
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, "main:hello.txt", "dev:hello.txt"
        ])
        assert result.exit_code != 0
        assert "same branch" in result.output.lower() or "same" in result.output.lower()

    def test_ancestor_dest_error(self, runner, repo_with_files):
        """mv :file main~1:file is an error (can't write to history)."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt", "main~1:renamed.txt"
        ])
        assert result.exit_code != 0
        assert "historical" in result.output.lower()

    def test_single_arg_error(self, runner, repo_with_files):
        """mv :file with no dest errors."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt"
        ])
        assert result.exit_code != 0

    def test_custom_message(self, runner, repo_with_files):
        """mv -m 'msg' sets commit message."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt", ":renamed.txt",
            "-m", "renamed hello"
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["log", "--repo", repo_with_files])
        assert "renamed hello" in r.output

    def test_atomicity(self, runner, repo_with_files):
        """After mv, source is gone and dest exists in same commit."""
        result = runner.invoke(main, [
            "mv", "--repo", repo_with_files, ":hello.txt", ":moved.txt"
        ])
        assert result.exit_code == 0, result.output
        # Check the latest commit has both changes
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":moved.txt"])
        assert r.exit_code == 0
        assert r.output == "hello world\n"
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, ":hello.txt"])
        assert r.exit_code != 0
        # Verify it's a single commit by checking ~1 still has original
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "~1:hello.txt"])
        assert r.exit_code == 0
        assert r.output == "hello world\n"
        r = runner.invoke(main, ["cat", "--repo", repo_with_files, "~1:moved.txt"])
        assert r.exit_code != 0

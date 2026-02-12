"""Unit tests for _parse_ref_path() and _validate_ref_name()."""

import pytest
import click

from gitstore.cli._helpers import RefPath, _parse_ref_path
from gitstore.repo import _validate_ref_name


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
        with pytest.raises(ValueError, match="space"):
            _validate_ref_name("my branch")

    def test_tab_rejected(self):
        with pytest.raises(ValueError, match="tab"):
            _validate_ref_name("my\tbranch")

    def test_newline_rejected(self):
        with pytest.raises(ValueError, match="newline"):
            _validate_ref_name("my\nbranch")

    def test_valid_with_dots_and_slashes(self):
        _validate_ref_name("feature/my-thing.v2")  # no error

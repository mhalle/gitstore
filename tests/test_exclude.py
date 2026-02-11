"""Tests for ExcludeFilter and its integration with _walk_local_paths."""

import os

import pytest

from gitstore._exclude import ExcludeFilter
from gitstore.copy._resolve import _walk_local_paths


# ---------------------------------------------------------------------------
# Unit tests for ExcludeFilter
# ---------------------------------------------------------------------------

class TestExcludeFilter:
    def test_no_patterns_not_active(self):
        ef = ExcludeFilter()
        assert ef.active is False

    def test_exclude_pattern_match(self):
        ef = ExcludeFilter(patterns=["*.pyc"])
        assert ef.active is True
        assert ef.is_excluded("foo.pyc") is True
        assert ef.is_excluded("sub/bar.pyc") is True

    def test_exclude_pattern_no_match(self):
        ef = ExcludeFilter(patterns=["*.pyc"])
        assert ef.is_excluded("foo.py") is False

    def test_exclude_directory_pattern(self):
        ef = ExcludeFilter(patterns=["build/"])
        assert ef.is_excluded("build", is_dir=True) is True
        # A file named "build" should not be matched by "build/"
        assert ef.is_excluded("build", is_dir=False) is False

    def test_negation_pattern(self):
        ef = ExcludeFilter(patterns=["*.pyc", "!important.pyc"])
        assert ef.is_excluded("foo.pyc") is True
        assert ef.is_excluded("important.pyc") is False

    def test_anchored_pattern(self):
        ef = ExcludeFilter(patterns=["/build"])
        assert ef.is_excluded("build") is True
        assert ef.is_excluded("src/build") is False

    def test_exclude_from_file(self, tmp_path):
        pfile = tmp_path / "excludes.txt"
        pfile.write_text("*.log\n# comment\n__pycache__/\n")
        ef = ExcludeFilter(exclude_from=str(pfile))
        assert ef.active is True
        assert ef.is_excluded("app.log") is True
        assert ef.is_excluded("__pycache__", is_dir=True) is True
        assert ef.is_excluded("app.py") is False

    def test_gitignore_active(self):
        ef = ExcludeFilter(gitignore=True)
        assert ef.active is True

    def test_gitignore_loading(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / ".gitignore").write_text("*.log\n")
        (root / "app.py").write_text("code")
        (root / "debug.log").write_text("log")

        ef = ExcludeFilter(gitignore=True)
        ef.enter_directory(root, "")

        # .gitignore files themselves are excluded
        assert ef.is_excluded_in_walk(".gitignore") is True
        # Pattern from .gitignore applies
        assert ef.is_excluded_in_walk("debug.log") is True
        assert ef.is_excluded_in_walk("app.py") is False

    def test_nested_gitignore(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / ".gitignore").write_text("*.log\n")
        sub = root / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.tmp\n")

        ef = ExcludeFilter(gitignore=True)
        ef.enter_directory(root, "")
        ef.enter_directory(sub, "sub")

        # Root .gitignore applies everywhere
        assert ef.is_excluded_in_walk("debug.log") is True
        assert ef.is_excluded_in_walk("sub/debug.log") is True
        # Sub .gitignore applies only in sub/
        assert ef.is_excluded_in_walk("sub/temp.tmp") is True
        assert ef.is_excluded_in_walk("temp.tmp") is False

    def test_gitignore_files_excluded(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / ".gitignore").write_text("*.pyc\n")
        sub = root / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.tmp\n")

        ef = ExcludeFilter(gitignore=True)
        ef.enter_directory(root, "")
        ef.enter_directory(sub, "sub")

        assert ef.is_excluded_in_walk(".gitignore") is True
        assert ef.is_excluded_in_walk("sub/.gitignore") is True

    def test_combined_patterns_and_gitignore(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / ".gitignore").write_text("*.log\n")

        ef = ExcludeFilter(patterns=["*.pyc"], gitignore=True)
        ef.enter_directory(root, "")

        assert ef.is_excluded_in_walk("foo.pyc") is True
        assert ef.is_excluded_in_walk("debug.log") is True
        assert ef.is_excluded_in_walk("app.py") is False


# ---------------------------------------------------------------------------
# Integration tests via _walk_local_paths
# ---------------------------------------------------------------------------

class TestWalkWithExclude:
    def test_walk_with_exclude(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / "app.py").write_text("code")
        (root / "app.pyc").write_text("compiled")
        sub = root / "sub"
        sub.mkdir()
        (sub / "mod.py").write_text("code")
        (sub / "mod.pyc").write_text("compiled")

        ef = ExcludeFilter(patterns=["*.pyc"])
        result = _walk_local_paths(str(root), exclude=ef)
        assert "app.py" in result
        assert "sub/mod.py" in result
        assert "app.pyc" not in result
        assert "sub/mod.pyc" not in result

    def test_walk_prunes_directories(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / "app.py").write_text("code")
        cache = root / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-312.pyc").write_text("compiled")

        ef = ExcludeFilter(patterns=["__pycache__/"])
        result = _walk_local_paths(str(root), exclude=ef)
        assert "app.py" in result
        assert "__pycache__/mod.cpython-312.pyc" not in result

    def test_walk_with_gitignore(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / ".gitignore").write_text("*.pyc\n__pycache__/\n")
        (root / "app.py").write_text("code")
        (root / "app.pyc").write_text("compiled")
        cache = root / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-312.pyc").write_text("compiled")

        ef = ExcludeFilter(gitignore=True)
        result = _walk_local_paths(str(root), exclude=ef)
        assert "app.py" in result
        assert "app.pyc" not in result
        assert "__pycache__/mod.cpython-312.pyc" not in result
        # .gitignore itself excluded
        assert ".gitignore" not in result

    def test_walk_no_exclude_returns_all(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / "app.py").write_text("code")
        (root / "app.pyc").write_text("compiled")

        result = _walk_local_paths(str(root))
        assert "app.py" in result
        assert "app.pyc" in result

    def test_walk_follow_symlinks_with_exclude(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / "app.py").write_text("code")
        (root / "app.pyc").write_text("compiled")
        sub = root / "sub"
        sub.mkdir()
        (sub / "mod.py").write_text("code")

        ef = ExcludeFilter(patterns=["*.pyc"])
        result = _walk_local_paths(str(root), follow_symlinks=True, exclude=ef)
        assert "app.py" in result
        assert "sub/mod.py" in result
        assert "app.pyc" not in result

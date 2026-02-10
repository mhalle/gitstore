"""Tests for FS.glob() and FS.is_dir()."""

import pytest

from gitstore import GitStore


@pytest.fixture
def fs_with_tree(tmp_path):
    """Create a repo with a varied tree for glob testing."""
    repo = GitStore.open(tmp_path / "test.git")
    fs = repo.branches["main"]
    fs = fs.write("readme.txt", b"readme")
    fs = fs.write("setup.py", b"setup")
    fs = fs.write(".hidden", b"dot")
    fs = fs.write("src/main.py", b"main")
    fs = fs.write("src/util.py", b"util")
    fs = fs.write("src/.config", b"cfg")
    fs = fs.write("src/sub/deep.txt", b"deep")
    fs = fs.write("docs/guide.md", b"guide")
    fs = fs.write("docs/api.md", b"api")
    fs = fs.write("data.txt", b"data")
    return fs


class TestIsDir:
    def test_dir(self, fs_with_tree):
        assert fs_with_tree.is_dir("src") is True

    def test_file(self, fs_with_tree):
        assert fs_with_tree.is_dir("readme.txt") is False

    def test_nested_dir(self, fs_with_tree):
        assert fs_with_tree.is_dir("src/sub") is True

    def test_missing(self, fs_with_tree):
        assert fs_with_tree.is_dir("nope") is False


class TestGlobStar:
    def test_star_matches_files(self, fs_with_tree):
        result = fs_with_tree.glob("*.txt")
        assert "readme.txt" in result
        assert "data.txt" in result

    def test_star_excludes_dotfiles(self, fs_with_tree):
        result = fs_with_tree.glob("*")
        assert ".hidden" not in result
        # But regular files should be there
        assert "readme.txt" in result
        assert "src" in result

    def test_dotstar_matches_dotfiles(self, fs_with_tree):
        result = fs_with_tree.glob(".*")
        assert ".hidden" in result
        assert "readme.txt" not in result

    def test_star_in_subdir(self, fs_with_tree):
        result = fs_with_tree.glob("src/*")
        assert "src/main.py" in result
        assert "src/util.py" in result
        assert "src/sub" in result
        # Dotfiles excluded
        assert "src/.config" not in result

    def test_star_extension_filter(self, fs_with_tree):
        result = fs_with_tree.glob("src/*.py")
        assert "src/main.py" in result
        assert "src/util.py" in result
        assert "src/sub" not in result

    def test_docs_star_md(self, fs_with_tree):
        result = fs_with_tree.glob("docs/*.md")
        assert sorted(result) == ["docs/api.md", "docs/guide.md"]


class TestGlobQuestion:
    def test_question_mark(self, fs_with_tree):
        result = fs_with_tree.glob("docs/???.md")
        assert "docs/api.md" in result
        assert "docs/guide.md" not in result


class TestGlobNested:
    def test_literal_then_glob(self, fs_with_tree):
        result = fs_with_tree.glob("src/sub/*.txt")
        assert result == ["src/sub/deep.txt"]

    def test_glob_then_literal(self, fs_with_tree):
        # */main.py — matches src/main.py
        result = fs_with_tree.glob("*/main.py")
        assert "src/main.py" in result


class TestGlobEdgeCases:
    def test_no_matches(self, fs_with_tree):
        result = fs_with_tree.glob("*.zzz")
        assert result == []

    def test_literal_path(self, fs_with_tree):
        result = fs_with_tree.glob("readme.txt")
        assert result == ["readme.txt"]

    def test_literal_missing(self, fs_with_tree):
        result = fs_with_tree.glob("nope.txt")
        assert result == []

    def test_empty_pattern(self, fs_with_tree):
        result = fs_with_tree.glob("")
        assert result == []

    def test_results_sorted(self, fs_with_tree):
        result = fs_with_tree.glob("*")
        assert result == sorted(result)


class TestGlobDoublestar:
    def test_doublestar_all(self, fs_with_tree):
        """** matches everything recursively (skipping dotfile dirs)."""
        result = fs_with_tree.glob("**")
        # Should include files and dirs at all levels
        assert "readme.txt" in result
        assert "src/main.py" in result
        assert "src/sub/deep.txt" in result
        assert "docs/guide.md" in result

    def test_doublestar_extension(self, fs_with_tree):
        """**/*.py matches .py at all depths."""
        result = fs_with_tree.glob("**/*.py")
        assert "setup.py" in result
        assert "src/main.py" in result
        assert "src/util.py" in result
        # Non-.py excluded
        assert "readme.txt" not in result
        assert "src/sub/deep.txt" not in result

    def test_doublestar_prefix(self, fs_with_tree):
        """src/**/*.py matches .py files under src/."""
        result = fs_with_tree.glob("src/**/*.py")
        assert "src/main.py" in result
        assert "src/util.py" in result
        # Root-level .py not matched
        assert "setup.py" not in result

    def test_doublestar_middle(self, fs_with_tree):
        """src/**/deep.txt matches nested file."""
        result = fs_with_tree.glob("src/**/deep.txt")
        assert "src/sub/deep.txt" in result

    def test_doublestar_no_dotfiles(self, fs_with_tree):
        """** skips dot-named entries, consistent with * behavior."""
        result = fs_with_tree.glob("**")
        assert ".hidden" not in result
        assert "src/.config" not in result
        # Regular files still present
        assert "readme.txt" in result
        assert "src/main.py" in result

    def test_doublestar_no_duplicates(self, fs_with_tree):
        """No file appears twice in results."""
        result = fs_with_tree.glob("**/*.py")
        assert len(result) == len(set(result))

    def test_doublestar_empty_repo(self, tmp_path):
        """** returns [] for empty repo."""
        from gitstore import GitStore
        repo = GitStore.open(tmp_path / "empty.git")
        fs = repo.branches["main"]
        result = fs.glob("**")
        assert result == []

    def test_doublestar_at_root(self, fs_with_tree):
        """**/readme.txt matches file at root."""
        result = fs_with_tree.glob("**/readme.txt")
        assert "readme.txt" in result

    def test_doublestar_results_sorted(self, fs_with_tree):
        result = fs_with_tree.glob("**")
        assert result == sorted(result)

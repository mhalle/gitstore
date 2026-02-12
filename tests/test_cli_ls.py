"""Tests for the gitstore CLI — ls and cat commands."""

import pytest
from click.testing import CliRunner

from gitstore.cli import main


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

    def test_back(self, runner, repo_with_files):
        # --back 1 should show state before data/ was added (only hello.txt)
        result = runner.invoke(main, [
            "ls", "--repo", repo_with_files, "--back", "1"
        ])
        assert result.exit_code == 0
        assert "hello.txt" in result.output
        assert "data" not in result.output


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
        assert len(lines) == len(set(lines))  # unique, not necessarily sorted

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
        assert result.exit_code == 0
        assert result.output.strip() == "readme.txt"

    def test_empty_branch(self, runner, tmp_path):
        p = str(tmp_path / "empty.git")
        r = runner.invoke(main, ["init", "--repo", p, "--branch", "main"])
        assert r.exit_code == 0
        result = runner.invoke(main, ["ls", "-R", "--repo", p])
        assert result.exit_code == 0
        assert result.output.strip() == ""


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

    def test_multiple_files(self, runner, repo_with_files):
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, ":hello.txt", ":hello.txt"
        ])
        assert result.exit_code == 0
        assert result.output == "hello world\nhello world\n"

    def test_multiple_stops_on_error(self, runner, repo_with_files):
        result = runner.invoke(main, [
            "cat", "--repo", repo_with_files, ":nope.txt", ":hello.txt"
        ])
        assert result.exit_code != 0

    def test_directory_error(self, runner, repo_with_files):
        result = runner.invoke(main, ["cat", "--repo", repo_with_files, ":data"])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()

    def test_back(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("version1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":f.txt"])
        f.write_text("version2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":f.txt"])
        # --back 1 should read the previous version
        result = runner.invoke(main, [
            "cat", "--repo", initialized_repo, "--back", "1", ":f.txt"
        ])
        assert result.exit_code == 0
        assert result.output == "version1"

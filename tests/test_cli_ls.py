"""Tests for the vost CLI — ls and cat commands."""

import json

import pytest
from click.testing import CliRunner

from vost.cli import main


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


class TestLsLong:
    def test_ls_l_shows_sizes(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-l", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        lines = result.output.strip().splitlines()
        # Format: hash  size  name — find lines with a numeric size (2nd column)
        found_file = False
        for line in lines:
            parts = line.split()
            if len(parts) >= 3 and parts[1].isdigit():
                found_file = True
                assert int(parts[1]) > 0  # size is positive
                assert len(parts[0]) == 7  # short hash
        assert found_file

    def test_ls_l_recursive(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-l", "-R", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        lines = result.output.strip().splitlines()
        # Should contain full paths like src/main.py with sizes
        names = [line.split()[-1] for line in lines if line.strip()]
        assert "src/main.py" in names
        assert "src/sub/deep.txt" in names
        assert "readme.txt" in names

    def test_ls_l_directory_no_size(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-l", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        lines = result.output.strip().splitlines()
        # Directory entries should have trailing / and no size
        dir_lines = [l for l in lines if l.rstrip().endswith("/")]
        assert len(dir_lines) > 0  # at least src/ or docs/
        for dl in dir_lines:
            # Format: hash       name/ — hash then empty size column then name
            parts = dl.split()
            name = parts[-1]
            assert name.endswith("/")
            assert name in ("docs/", "src/")

    def test_ls_l_json(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-l", "--format", "json", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        # Find a file entry
        file_entries = [e for e in data if e.get("type") != "tree"]
        assert len(file_entries) > 0
        for e in file_entries:
            assert "name" in e
            assert "size" in e
            assert "type" in e
            assert isinstance(e["size"], int)
            assert "hash" in e
            assert len(e["hash"]) == 40  # full hash in JSON
        # Find a dir entry
        dir_entries = [e for e in data if e.get("type") == "tree"]
        assert len(dir_entries) > 0
        for e in dir_entries:
            assert "name" in e
            assert "type" in e
            assert "size" not in e

    def test_ls_l_jsonl(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "-l", "--format", "jsonl", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        lines = result.output.strip().splitlines()
        assert len(lines) > 0
        for line in lines:
            obj = json.loads(line)
            assert "name" in obj
            assert "type" in obj

    def test_ls_json_without_l(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--format", "json", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        # Without -l, should be an array of strings
        for item in data:
            assert isinstance(item, str)
        assert "readme.txt" in data

    def test_ls_jsonl_without_l(self, runner, repo_with_tree):
        result = runner.invoke(main, ["ls", "--format", "jsonl", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        lines = result.output.strip().splitlines()
        assert len(lines) > 0
        # Each line should be a JSON string
        names = [json.loads(line) for line in lines]
        for name in names:
            assert isinstance(name, str)
        assert "readme.txt" in names

    def test_ls_l_symlink_text(self, runner, repo_with_tree):
        from vost.repo import GitStore
        store = GitStore.open(repo_with_tree, create=False)
        fs = store.branches["main"]
        fs.write_symlink("shortcut", "readme.txt")

        result = runner.invoke(main, ["ls", "-l", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        # Should show "shortcut -> readme.txt"
        assert "shortcut -> readme.txt" in result.output

    def test_ls_l_symlink_json(self, runner, repo_with_tree):
        from vost.repo import GitStore
        store = GitStore.open(repo_with_tree, create=False)
        fs = store.branches["main"]
        fs.write_symlink("shortcut", "readme.txt")

        result = runner.invoke(main, ["ls", "-l", "--format", "json", "--repo", repo_with_tree])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        link_entries = [e for e in data if e.get("type") == "link"]
        assert len(link_entries) == 1
        assert link_entries[0]["name"] == "shortcut"
        assert link_entries[0]["target"] == "readme.txt"
        assert "size" in link_entries[0]

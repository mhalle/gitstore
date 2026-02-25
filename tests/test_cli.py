"""Tests for the vost CLI — core commands (init, destroy, rm, write, log, sync, diff, undo, redo, reflog)."""

import os
import time
import pytest
from click.testing import CliRunner

from vost.cli import main


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_repo(self, runner, repo_path):
        result = runner.invoke(main, ["init", "--repo", repo_path])
        assert result.exit_code == 0
        result = runner.invoke(main, ["branch", "--repo", repo_path, "list"])
        assert "main" in result.output

    def test_creates_repo_with_custom_branch(self, runner, repo_path):
        result = runner.invoke(main, ["init", "--repo", repo_path, "--branch", "trunk"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["branch", "--repo", repo_path, "list"])
        assert "trunk" in result.output

    def test_already_exists_error(self, runner, initialized_repo):
        result = runner.invoke(main, ["init", "--repo", initialized_repo])
        assert result.exit_code != 0
        assert "already exists" in result.output


# ---------------------------------------------------------------------------
# TestDestroy
# ---------------------------------------------------------------------------

class TestDestroy:
    def test_destroy_empty(self, runner, initialized_repo):
        result = runner.invoke(main, ["destroy", "--repo", initialized_repo])
        assert result.exit_code == 0
        assert not os.path.exists(initialized_repo)

    def test_destroy_nonempty_requires_force(self, runner, repo_with_files):
        result = runner.invoke(main, ["destroy", "--repo", repo_with_files])
        assert result.exit_code != 0
        assert "not empty" in result.output.lower()
        assert os.path.exists(repo_with_files)

    def test_destroy_nonempty_with_force(self, runner, repo_with_files):
        result = runner.invoke(main, ["destroy", "--repo", repo_with_files, "-f"])
        assert result.exit_code == 0
        assert not os.path.exists(repo_with_files)

    def test_destroy_missing_repo(self, runner, tmp_path):
        bad_path = str(tmp_path / "nope.git")
        result = runner.invoke(main, ["destroy", "--repo", bad_path])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# TestGc
# ---------------------------------------------------------------------------

class TestGc:
    def test_gc_succeeds(self, runner, repo_with_files):
        import shutil
        if shutil.which("git") is None:
            pytest.skip("git not installed")
        result = runner.invoke(main, ["gc", "--repo", repo_with_files])
        assert result.exit_code == 0

    def test_gc_missing_repo(self, runner, tmp_path):
        bad_path = str(tmp_path / "nope.git")
        result = runner.invoke(main, ["gc", "--repo", bad_path])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_gc_help(self, runner):
        result = runner.invoke(main, ["gc", "--help"])
        assert result.exit_code == 0
        assert "garbage collection" in result.output.lower()


# ---------------------------------------------------------------------------
# TestRm
# ---------------------------------------------------------------------------

class TestRm:
    def test_removes_file(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":hello.txt"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "hello.txt" not in result.output

    def test_missing_file_error(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":nonexistent.txt"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_directory_rejected(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":data"])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()
        assert "-R" in result.output

    def test_without_colon(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, "hello.txt"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "hello.txt" not in result.output

    def test_custom_message(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":hello.txt", "-m", "bye bye"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["log", "--repo", repo_with_files])
        assert "bye bye" in result.output

    def test_rm_glob(self, runner, repo_with_files):
        # Add a second txt file first
        from pathlib import Path
        extra = Path(repo_with_files).parent / "extra.txt"
        extra.write_text("extra")
        result = runner.invoke(main, ["cp", "--repo", repo_with_files, str(extra), ":"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["rm", "--repo", repo_with_files, ":*.txt"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "hello.txt" not in result.output
        assert "extra.txt" not in result.output

    def test_rm_recursive(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "-R", "--repo", repo_with_files, ":data"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_files])
        assert "data.bin" not in result.output

    def test_rm_dry_run(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "-n", "--repo", repo_with_files, ":hello.txt"])
        assert result.exit_code == 0, result.output
        assert "- :hello.txt" in result.output

        # File still exists
        result = runner.invoke(main, ["ls", "--repo", repo_with_files])
        assert "hello.txt" in result.output

    def test_rm_multiple_paths(self, runner, repo_with_files):
        result = runner.invoke(main, ["rm", "-R", "--repo", repo_with_files, ":hello.txt", ":data"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "-R", "--repo", repo_with_files])
        assert "hello.txt" not in result.output
        assert "data.bin" not in result.output


# ---------------------------------------------------------------------------
# TestWrite
# ---------------------------------------------------------------------------

class TestWrite:
    def test_write_from_stdin(self, runner, initialized_repo):
        result = runner.invoke(main, ["write", "--repo", initialized_repo, "file.txt"], input=b"hello world\n")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, "file.txt"])
        assert result.exit_code == 0
        assert result.output == "hello world\n"

    def test_write_overwrites_existing(self, runner, repo_with_files):
        result = runner.invoke(main, ["write", "--repo", repo_with_files, "hello.txt"], input=b"new content\n")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["cat", "--repo", repo_with_files, "hello.txt"])
        assert result.exit_code == 0
        assert result.output == "new content\n"

    def test_write_custom_message(self, runner, initialized_repo):
        result = runner.invoke(main, ["write", "--repo", initialized_repo, "file.txt", "-m", "my msg"], input=b"data")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "my msg" in result.output

    def test_write_colon_prefix_optional(self, runner, initialized_repo):
        result = runner.invoke(main, ["write", "--repo", initialized_repo, ":file.txt"], input=b"abc")
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, "file.txt"])
        assert result.exit_code == 0
        assert result.output == "abc"

    def test_write_passthrough_echoes_to_stdout(self, runner, initialized_repo):
        result = runner.invoke(
            main,
            ["write", "--repo", initialized_repo, "log.txt", "--passthrough"],
            input=b"pipeline data\n",
        )
        assert result.exit_code == 0, result.output
        # stdout should contain the piped-through data
        assert "pipeline data\n" in result.output

        # File should also be in the repo
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, "log.txt"])
        assert result.exit_code == 0
        assert result.output == "pipeline data\n"

    def test_write_passthrough_short_flag(self, runner, initialized_repo):
        result = runner.invoke(
            main,
            ["write", "--repo", initialized_repo, "log.txt", "-p"],
            input=b"short flag\n",
        )
        assert result.exit_code == 0, result.output
        assert "short flag\n" in result.output

    def test_write_without_passthrough_no_stdout(self, runner, initialized_repo):
        result = runner.invoke(
            main,
            ["write", "--repo", initialized_repo, "quiet.txt"],
            input=b"silent data\n",
        )
        assert result.exit_code == 0, result.output
        # Without passthrough, the input data should NOT appear in stdout
        assert "silent data" not in result.output


# ---------------------------------------------------------------------------
# TestLog
# ---------------------------------------------------------------------------

class TestLog:
    def test_all_commits(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        # At least: init + write hello.txt + write data tree
        assert len(lines) >= 3

    def test_path_filter(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--path", "hello.txt"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) >= 1

    def test_at_without_colon(self, runner, repo_with_files):
        """--path should work without a leading ':'."""
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--path", "hello.txt"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) >= 1

    def test_nonexistent_path_empty(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--path", "nonexistent.txt"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_match_exact(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])
        result = runner.invoke(main, ["log", "--repo", initialized_repo, "--match", "deploy v1"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "deploy v1" in lines[0]

    def test_match_wildcard(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v2"])
        f.write_text("c")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])
        result = runner.invoke(main, ["log", "--repo", initialized_repo, "--match", "deploy*"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 2
        assert all("deploy" in line for line in lines)

    def test_match_no_results(self, runner, repo_with_files):
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--match", "zzz-no-match*"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_match_and_at(self, runner, initialized_repo, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a")
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f1), ":a.txt", "-m", "deploy a"])
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "deploy b"])
        f1.write_text("a2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f1), ":a.txt", "-m", "fix a"])
        result = runner.invoke(main, ["log", "--repo", initialized_repo, "--path", "a.txt", "--match", "deploy*"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "deploy a" in lines[0]

    def test_json_format(self, runner, repo_with_files):
        import json
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 3
        entry = data[0]
        assert "hash" in entry
        assert "message" in entry
        assert "time" in entry
        assert "author_name" in entry
        assert "author_email" in entry
        assert len(entry["hash"]) == 40

    def test_jsonl_format(self, runner, repo_with_files):
        import json
        result = runner.invoke(main, ["log", "--repo", repo_with_files, "--format", "jsonl"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) >= 3
        for line in lines:
            entry = json.loads(line)
            assert "hash" in entry
            assert "message" in entry

    def test_back(self, runner, repo_with_files):
        # repo_with_files has: init + write hello.txt + write data/
        # --back 1 should start log from the "write hello.txt" commit
        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--back", "1"
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        # Should have 2 commits (hello.txt write + init), not 3
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# TestErrorPaths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_missing_repo(self, runner, tmp_path):
        bad_path = str(tmp_path / "nope.git")
        result = runner.invoke(main, ["ls", "--repo", bad_path])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_branch(self, runner, initialized_repo):
        result = runner.invoke(main, ["ls", "--repo", initialized_repo, "-b", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_missing_repo_error(self, runner):
        """Running a command with no --repo and no GITSTORE_REPO should fail."""
        result = runner.invoke(main, ["ls"])
        assert result.exit_code != 0
        assert "GITSTORE_REPO" in result.output

    def test_env_var_fallback(self, runner, initialized_repo):
        """GITSTORE_REPO env var should work as fallback for --repo."""
        result = runner.invoke(main, ["ls"], env={"GITSTORE_REPO": initialized_repo})
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestSync
# ---------------------------------------------------------------------------

class TestSync:
    def test_sync_1arg_disk_to_repo(self, runner, initialized_repo, tmp_path):
        """sync ./dir syncs local dir to repo root."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, str(src),
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "a.txt" in r.output
        assert "b.txt" in r.output

    def test_sync_2arg_disk_to_repo(self, runner, initialized_repo, tmp_path):
        """sync ./dir :dest syncs to a repo sub-path."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.txt").write_text("xxx")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, str(src), ":data",
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["ls", "--repo", initialized_repo, ":data"])
        assert "x.txt" in r.output

    def test_sync_2arg_repo_to_disk(self, runner, repo_with_files, tmp_path):
        """sync :data ./out syncs repo path to disk."""
        dest = tmp_path / "out"
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, ":data", str(dest),
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "data.bin").exists()

    def test_sync_deletes_extra_files(self, runner, repo_with_files, tmp_path):
        """Sync deletes files in dest not present in source."""
        # First sync repo data to disk
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "extra.txt").write_text("extra")
        (dest / "data.bin").write_bytes(b"\x00\x01\x02")
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, ":data", str(dest),
        ])
        assert result.exit_code == 0, result.output
        assert (dest / "data.bin").exists()
        assert not (dest / "extra.txt").exists()

    def test_sync_dry_run(self, runner, initialized_repo, tmp_path):
        """-n shows plan without writing."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "new.txt").write_text("new")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", str(src),
        ])
        assert result.exit_code == 0, result.output
        assert "+" in result.output  # add action
        # Verify nothing was actually written
        r = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "new.txt" not in r.output

    def test_sync_both_local_error(self, runner, initialized_repo, tmp_path):
        """sync a b (no colon on either) errors."""
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "a", "b",
        ])
        assert result.exit_code != 0
        assert "Neither argument is a repo path" in result.output

    def test_sync_repo_to_repo(self, runner, repo_with_files):
        """sync :src :dest now works (repo→repo sync)."""
        # First create a second branch
        runner.invoke(main, ["branch", "--repo", repo_with_files, "set", "dev"])
        # Sync from main to dev (repo→repo)
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, ":", "dev:", "-n",
        ])
        # Should not error about "Both arguments are repo paths"
        assert "Both arguments are repo paths" not in result.output

    def test_sync_1arg_repo_error(self, runner, initialized_repo):
        """sync :path errors (1-arg must be local)."""
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, ":path",
        ])
        assert result.exit_code != 0
        assert "must be a local path" in result.output

    def test_sync_ignore_errors(self, runner, repo_with_files, tmp_path):
        """--ignore-errors works."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "good.txt").write_text("good")
        # Create an unreadable file
        bad = src / "bad.txt"
        bad.write_text("bad")
        os.chmod(str(bad), 0o000)
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, str(src), ":dest",
            "--ignore-errors",
        ])
        # Restore permissions for cleanup
        os.chmod(str(bad), 0o644)
        # good.txt should have been written
        r = runner.invoke(main, ["ls", "--repo", repo_with_files, ":dest"])
        assert "good.txt" in r.output

    def test_sync_custom_message(self, runner, initialized_repo, tmp_path):
        """-m sets commit message."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("data")
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo,
            "-m", "custom sync message", str(src),
        ])
        assert result.exit_code == 0, result.output
        r = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "custom sync message" in r.output

    def test_sync_watch_dry_run_incompatible(self, runner, initialized_repo, tmp_path):
        """--watch and --dry-run are incompatible."""
        src = tmp_path / "src"
        src.mkdir()
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "--watch", "-n", str(src),
        ])
        assert result.exit_code != 0
        assert "--watch and --dry-run are incompatible" in result.output

    def test_sync_watch_from_repo_incompatible(self, runner, repo_with_files, tmp_path):
        """--watch with repo->disk direction errors."""
        dest = tmp_path / "out"
        result = runner.invoke(main, [
            "sync", "--repo", repo_with_files, "--watch", ":data", str(dest),
        ])
        assert result.exit_code != 0
        assert "--watch only supports disk" in result.output

    def test_sync_watch_debounce_too_low(self, runner, initialized_repo, tmp_path):
        """--debounce below 100 errors."""
        src = tmp_path / "src"
        src.mkdir()
        result = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "--watch", "--debounce", "50", str(src),
        ])
        assert result.exit_code != 0
        assert "--debounce must be at least 100" in result.output


class TestChecksumMode:
    """Tests for the mtime-based (default) vs checksum change detection."""

    def test_sync_skips_unchanged_files_default_mode(self, runner, initialized_repo, tmp_path):
        """Default mode: sync dir to repo, touch nothing, sync again → no updates."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        # Initial sync
        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Second sync with no changes — dry-run should show nothing
        r = runner.invoke(main, ["sync", "--repo", initialized_repo, "-n", str(src)])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output  # no updates
        assert "+" not in r.output  # no adds
        assert "-" not in r.output  # no deletes

    def test_sync_detects_new_mtime(self, runner, initialized_repo, tmp_path):
        """Rewriting a file (new mtime) is detected in default mode."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("original")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Rewrite the file — mtime must land in a later second
        time.sleep(1.1)
        (src / "a.txt").write_text("changed")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, "-n", str(src)])
        assert r.exit_code == 0, r.output
        assert "~" in r.output  # update detected

    def test_cp_delete_skips_unchanged_default_mode(self, runner, initialized_repo, tmp_path):
        """cp --delete: unchanged files are skipped in default (mtime) mode."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.txt").write_text("xxx")

        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "--delete",
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output

        # Dry-run again with no changes
        r = runner.invoke(main, [
            "cp", "--repo", initialized_repo, "--delete", "-n",
            str(src) + "/", ":",
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output

    def test_checksum_detects_backdated_change(self, runner, initialized_repo, tmp_path):
        """--checksum catches content change even when mtime is backdated."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("original")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Change content but backdate the mtime to before the commit
        (src / "a.txt").write_text("sneaky change")
        old_time = 1000000000.0  # Sep 2001
        os.utime(src / "a.txt", (old_time, old_time))

        # Default mode (mtime): misses the change
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output  # mtime mode skips it

        # --checksum mode: catches it
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", "-c", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert "~" in r.output  # checksum mode catches it

    def test_checksum_dry_run_matches_real_run(self, runner, initialized_repo, tmp_path):
        """--checksum dry-run and real-run agree on what changes."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Modify one file — mtime must land in a later second
        time.sleep(1.1)
        (src / "a.txt").write_text("AAA")

        # Dry-run with --checksum
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", "-c", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert ":a.txt" in r.output
        assert "b.txt" not in r.output

        # Real run with --checksum
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-c", str(src),
        ])
        assert r.exit_code == 0, r.output

        # Verify: now a dry-run shows no changes
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", "-c", str(src),
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output
        assert "+" not in r.output

    def test_default_mode_skips_old_mtime_file(self, runner, initialized_repo, tmp_path):
        """Document the tradeoff: a file with old mtime is skipped in default mode."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("original")

        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Write new content but backdate mtime
        (src / "a.txt").write_text("different content")
        old_time = 946684800.0  # Jan 1 2000
        os.utime(src / "a.txt", (old_time, old_time))

        # Default mode skips it (file appears unchanged)
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, str(src),
        ])
        assert r.exit_code == 0, r.output

        # Verify the repo still has the original content
        r = runner.invoke(main, ["cat", "--repo", initialized_repo, "a.txt"])
        assert r.output == "original"

    def test_round_trip_preserves_mtime(self, runner, initialized_repo, tmp_path):
        """After repo→disk, files get commit mtime so disk→repo skips them."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        # Sync disk → repo
        r = runner.invoke(main, ["sync", "--repo", initialized_repo, str(src)])
        assert r.exit_code == 0, r.output

        # Sync repo → disk (different directory)
        dest = tmp_path / "dest"
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, ":", str(dest),
        ])
        assert r.exit_code == 0, r.output
        assert (dest / "a.txt").read_text() == "aaa"

        # Now sync that dest back to repo — should detect no changes
        r = runner.invoke(main, [
            "sync", "--repo", initialized_repo, "-n", str(dest),
        ])
        assert r.exit_code == 0, r.output
        assert "~" not in r.output  # no updates
        assert "+" not in r.output  # no adds


# ---------------------------------------------------------------------------
# TestDiff
# ---------------------------------------------------------------------------

class TestDiff:
    def test_diff_no_changes(self, runner, repo_with_files):
        """diff --back 0 compares HEAD to itself — no output."""
        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "--back", "0"])
        assert r.exit_code == 0, r.output
        assert r.output == ""

    def test_diff_added_file(self, runner, repo_with_files, tmp_path):
        """New file shows as A (added)."""
        new = tmp_path / "new.txt"
        new.write_text("new content")
        r = runner.invoke(main, ["cp", "--repo", repo_with_files, str(new), ":new.txt"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "--back", "1"])
        assert r.exit_code == 0, r.output
        assert "A  new.txt" in r.output

    def test_diff_modified_file(self, runner, repo_with_files, tmp_path):
        """Modified file shows as M."""
        updated = tmp_path / "hello.txt"
        updated.write_text("changed content")
        r = runner.invoke(main, ["cp", "--repo", repo_with_files, str(updated), ":hello.txt"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "--back", "1"])
        assert r.exit_code == 0, r.output
        assert "M  hello.txt" in r.output

    def test_diff_deleted_file(self, runner, repo_with_files):
        """Deleted file shows as D."""
        r = runner.invoke(main, ["rm", "--repo", repo_with_files, ":hello.txt"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "--back", "1"])
        assert r.exit_code == 0, r.output
        assert "D  hello.txt" in r.output

    def test_diff_mixed(self, runner, repo_with_files, tmp_path):
        """Add + modify + delete in one commit shows all three prefixes."""
        from vost import GitStore
        store = GitStore.open(repo_with_files, create=False)
        fs = store.branches["main"]
        fs = fs.write("hello.txt", b"changed")
        fs = fs.write("added.txt", b"new")
        fs = fs.remove("data/data.bin")

        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "--back", "3"])
        assert r.exit_code == 0, r.output
        assert "A  added.txt" in r.output
        assert "M  hello.txt" in r.output
        assert "D  data/data.bin" in r.output

    def test_diff_reverse(self, runner, repo_with_files, tmp_path):
        """--reverse swaps A and D."""
        new = tmp_path / "new.txt"
        new.write_text("new content")
        r = runner.invoke(main, ["cp", "--repo", repo_with_files, str(new), ":new.txt"])
        assert r.exit_code == 0, r.output

        r = runner.invoke(main, ["diff", "--repo", repo_with_files, "--back", "1", "--reverse"])
        assert r.exit_code == 0, r.output
        assert "D  new.txt" in r.output
        assert "A" not in r.output or "A  new.txt" not in r.output


# ---------------------------------------------------------------------------
# TestUndo (CLI)
# ---------------------------------------------------------------------------

class TestUndo:
    def test_basic_undo(self, runner, initialized_repo, tmp_path):
        """Undo one commit via CLI."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "update a"])

        r = runner.invoke(main, ["undo", "--repo", initialized_repo])
        assert r.exit_code == 0, r.output
        assert "Branch now at:" in r.output

        # Branch should now be at v1
        r = runner.invoke(main, ["cat", "--repo", initialized_repo, ":a.txt"])
        assert r.output == "v1"

    def test_multi_step_undo(self, runner, initialized_repo, tmp_path):
        """Undo multiple commits at once."""
        f = tmp_path / "a.txt"
        for i in range(4):
            f.write_text(f"v{i}")
            runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", f"v{i}"])

        r = runner.invoke(main, ["undo", "--repo", initialized_repo, "3"])
        assert r.exit_code == 0, r.output
        assert "Branch now at:" in r.output

        r = runner.invoke(main, ["cat", "--repo", initialized_repo, ":a.txt"])
        assert r.output == "v0"

    def test_undo_past_root_error(self, runner, initialized_repo):
        """Undoing past the root commit errors out."""
        r = runner.invoke(main, ["undo", "--repo", initialized_repo, "5"])
        assert r.exit_code != 0
        assert "Cannot undo" in r.output or "too short" in r.output.lower()

    def test_undo_nonexistent_branch(self, runner, initialized_repo):
        """Undo on a non-existent branch errors out."""
        r = runner.invoke(main, ["undo", "--repo", initialized_repo, "-b", "nope"])
        assert r.exit_code != 0
        assert "not found" in r.output.lower()

    def test_undo_custom_branch(self, runner, initialized_repo, tmp_path):
        """Undo on a specific branch via -b."""
        runner.invoke(main, ["branch", "--repo", initialized_repo, "set", "dev"])
        f = tmp_path / "a.txt"
        f.write_text("dev-data")
        runner.invoke(main, ["cp", "--repo", initialized_repo, "-b", "dev", str(f), ":a.txt"])

        r = runner.invoke(main, ["undo", "--repo", initialized_repo, "-b", "dev"])
        assert r.exit_code == 0, r.output
        assert "Branch now at:" in r.output


# ---------------------------------------------------------------------------
# TestRedo (CLI)
# ---------------------------------------------------------------------------

class TestRedo:
    def test_undo_then_redo(self, runner, initialized_repo, tmp_path):
        """Undo then redo restores the original state."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "update a"])

        # Undo
        r = runner.invoke(main, ["undo", "--repo", initialized_repo])
        assert r.exit_code == 0, r.output
        r = runner.invoke(main, ["cat", "--repo", initialized_repo, ":a.txt"])
        assert r.output == "v1"

        # Redo
        r = runner.invoke(main, ["redo", "--repo", initialized_repo])
        assert r.exit_code == 0, r.output
        assert "Branch now at:" in r.output
        r = runner.invoke(main, ["cat", "--repo", initialized_repo, ":a.txt"])
        assert r.output == "v2"

    def test_redo_past_available_steps_error(self, runner, initialized_repo, tmp_path):
        """Redo more steps than available should fail."""
        f = tmp_path / "a.txt"
        f.write_text("data")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt"])

        # There are only a few reflog entries, so redo 100 should fail
        r = runner.invoke(main, ["redo", "--repo", initialized_repo, "100"])
        assert r.exit_code != 0
        assert "Cannot redo" in r.output or "step" in r.output.lower()

    def test_redo_nonexistent_branch(self, runner, initialized_repo):
        """Redo on a non-existent branch errors out."""
        r = runner.invoke(main, ["redo", "--repo", initialized_repo, "-b", "nope"])
        assert r.exit_code != 0
        assert "not found" in r.output.lower()


# ---------------------------------------------------------------------------
# TestReflogCLI
# ---------------------------------------------------------------------------

class TestReflogCLI:
    def test_reflog_text(self, runner, initialized_repo, tmp_path):
        """Default text format shows reflog entries."""
        f = tmp_path / "a.txt"
        f.write_text("data")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt"])

        r = runner.invoke(main, ["reflog", "--repo", initialized_repo])
        assert r.exit_code == 0, r.output
        assert "Reflog for branch" in r.output

    def test_reflog_json(self, runner, initialized_repo, tmp_path):
        """--format json outputs valid JSON array."""
        import json

        f = tmp_path / "a.txt"
        f.write_text("data")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt"])

        r = runner.invoke(main, ["reflog", "--repo", initialized_repo, "--format", "json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "new_sha" in data[0]
        assert "message" in data[0]

    def test_reflog_jsonl(self, runner, initialized_repo, tmp_path):
        """--format jsonl outputs one JSON object per line."""
        import json

        f = tmp_path / "a.txt"
        f.write_text("data")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt"])

        r = runner.invoke(main, ["reflog", "--repo", initialized_repo, "--format", "jsonl"])
        assert r.exit_code == 0, r.output
        lines = r.output.strip().split("\n")
        assert len(lines) >= 1
        for line in lines:
            entry = json.loads(line)
            assert "new_sha" in entry

    def test_reflog_limit(self, runner, initialized_repo, tmp_path):
        """--limit N shows at most N entries."""
        f = tmp_path / "a.txt"
        for i in range(5):
            f.write_text(f"v{i}")
            runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", f"v{i}"])

        r = runner.invoke(main, ["reflog", "--repo", initialized_repo, "--format", "json", "-n", "2"])
        assert r.exit_code == 0, r.output
        import json
        data = json.loads(r.output)
        assert len(data) == 2

    def test_reflog_nonexistent_branch(self, runner, initialized_repo):
        """Reflog on a non-existent branch errors out."""
        r = runner.invoke(main, ["reflog", "--repo", initialized_repo, "-b", "nope"])
        assert r.exit_code != 0
        assert "not found" in r.output.lower()


# ---------------------------------------------------------------------------
# TestSnapshotFilterCombined (CLI)
# ---------------------------------------------------------------------------

class TestSnapshotFilterCombined:
    def test_path_and_back(self, runner, initialized_repo, tmp_path):
        """--path + --back together: back from the latest commit touching that path."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "update a"])
        f.write_text("v3")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "update a again"])

        # --back 1 from tip gets "update a" commit
        r = runner.invoke(main, ["log", "--repo", initialized_repo, "--back", "1"])
        assert r.exit_code == 0, r.output
        lines = r.output.strip().split("\n")
        assert "update a again" not in r.output

    def test_before_and_match(self, runner, initialized_repo, tmp_path):
        """--before + --match together: only commits matching pattern before cutoff."""
        import time
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        time.sleep(1.1)
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v2"])

        # Get timestamp between the two commits
        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        entries = list(fs.log())
        # entries[0] = deploy v2 (newest), entries[1] = deploy v1
        cutoff = entries[0].time  # include both

        r = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--before", cutoff.isoformat(),
            "--match", "deploy*"
        ])
        assert r.exit_code == 0, r.output
        lines = [l for l in r.output.strip().split("\n") if l.strip()]
        assert len(lines) == 2
        assert all("deploy" in line for line in lines)

    def test_back_and_match(self, runner, initialized_repo, tmp_path):
        """--back + --match: start from ancestor, filter by message."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])
        f.write_text("v3")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v3"])

        # --back 1 starts from "fix bug" commit, --match "deploy*" should only match "deploy v1"
        r = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--back", "1", "--match", "deploy*"
        ])
        assert r.exit_code == 0, r.output
        lines = [l for l in r.output.strip().split("\n") if l.strip()]
        assert len(lines) == 1
        assert "deploy v1" in lines[0]


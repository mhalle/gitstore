"""Tests for --format json/jsonl on CLI commands."""

import json
import pytest

from vost.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_file(runner, repo, name, content="data"):
    """Write a file to the repo via the write command."""
    import tempfile, os
    fd, path = tempfile.mkstemp()
    try:
        os.write(fd, content.encode() if isinstance(content, str) else content)
        os.close(fd)
        r = runner.invoke(main, ["cp", "--repo", repo, path, f":{name}"])
        assert r.exit_code == 0, r.output
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# diff --format
# ---------------------------------------------------------------------------

class TestDiffFormat:
    def test_json(self, runner, initialized_repo, tmp_path):
        _write_file(runner, initialized_repo, "a.txt", "v1")
        _write_file(runner, initialized_repo, "a.txt", "v2")

        r = runner.invoke(main, [
            "diff", "--repo", initialized_repo, "--back", "1", "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert isinstance(data, list)
        statuses = {item["status"] for item in data}
        assert statuses <= {"A", "M", "D"}

    def test_jsonl(self, runner, initialized_repo, tmp_path):
        _write_file(runner, initialized_repo, "a.txt", "v1")
        _write_file(runner, initialized_repo, "a.txt", "v2")

        r = runner.invoke(main, [
            "diff", "--repo", initialized_repo, "--back", "1", "--format", "jsonl",
        ])
        assert r.exit_code == 0, r.output
        lines = [l for l in r.output.strip().split("\n") if l]
        for line in lines:
            item = json.loads(line)
            assert "path" in item
            assert "status" in item

    def test_text_unchanged(self, runner, initialized_repo, tmp_path):
        _write_file(runner, initialized_repo, "a.txt", "v1")
        _write_file(runner, initialized_repo, "a.txt", "v2")

        r = runner.invoke(main, [
            "diff", "--repo", initialized_repo, "--back", "1",
        ])
        assert r.exit_code == 0, r.output
        assert "M  a.txt" in r.output


# ---------------------------------------------------------------------------
# hash --format
# ---------------------------------------------------------------------------

class TestHashFormat:
    def test_commit_json(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")

        r = runner.invoke(main, [
            "hash", "--repo", initialized_repo, "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["type"] == "commit"
        assert len(data["hash"]) == 40

    def test_blob_json(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")

        r = runner.invoke(main, [
            "hash", "--repo", initialized_repo, ":x.txt", "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["type"] == "blob"
        assert data["path"] == "x.txt"

    def test_text_unchanged(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")

        r = runner.invoke(main, [
            "hash", "--repo", initialized_repo,
        ])
        assert r.exit_code == 0, r.output
        assert len(r.output.strip()) == 40


# ---------------------------------------------------------------------------
# branch list --format
# ---------------------------------------------------------------------------

class TestBranchListFormat:
    def test_json(self, runner, initialized_repo):
        r = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "list", "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert isinstance(data, list)
        assert "main" in data

    def test_jsonl(self, runner, initialized_repo):
        r = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "list", "--format", "jsonl",
        ])
        assert r.exit_code == 0, r.output
        lines = [l for l in r.output.strip().split("\n") if l]
        names = [json.loads(l) for l in lines]
        assert "main" in names

    def test_text_unchanged(self, runner, initialized_repo):
        r = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "list",
        ])
        assert r.exit_code == 0, r.output
        assert "main" in r.output


# ---------------------------------------------------------------------------
# branch hash --format
# ---------------------------------------------------------------------------

class TestBranchHashFormat:
    def test_json(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")

        r = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "hash", "main", "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["branch"] == "main"
        assert len(data["hash"]) == 40

    def test_text_unchanged(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")

        r = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "hash", "main",
        ])
        assert r.exit_code == 0, r.output
        assert len(r.output.strip()) == 40


# ---------------------------------------------------------------------------
# branch current --format
# ---------------------------------------------------------------------------

class TestBranchCurrentFormat:
    def test_json(self, runner, initialized_repo):
        r = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "current", "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["name"] == "main"

    def test_text_unchanged(self, runner, initialized_repo):
        r = runner.invoke(main, [
            "branch", "--repo", initialized_repo, "current",
        ])
        assert r.exit_code == 0, r.output
        assert r.output.strip() == "main"


# ---------------------------------------------------------------------------
# tag list --format
# ---------------------------------------------------------------------------

class TestTagListFormat:
    def test_json(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, ["tag", "--repo", initialized_repo, "set", "v1"])

        r = runner.invoke(main, [
            "tag", "--repo", initialized_repo, "list", "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert isinstance(data, list)
        assert "v1" in data

    def test_jsonl(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, ["tag", "--repo", initialized_repo, "set", "v1"])

        r = runner.invoke(main, [
            "tag", "--repo", initialized_repo, "list", "--format", "jsonl",
        ])
        assert r.exit_code == 0, r.output
        names = [json.loads(l) for l in r.output.strip().split("\n") if l]
        assert "v1" in names

    def test_text_unchanged(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, ["tag", "--repo", initialized_repo, "set", "v1"])

        r = runner.invoke(main, [
            "tag", "--repo", initialized_repo, "list",
        ])
        assert r.exit_code == 0, r.output
        assert "v1" in r.output


# ---------------------------------------------------------------------------
# tag hash --format
# ---------------------------------------------------------------------------

class TestTagHashFormat:
    def test_json(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, ["tag", "--repo", initialized_repo, "set", "v1"])

        r = runner.invoke(main, [
            "tag", "--repo", initialized_repo, "hash", "v1", "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["tag"] == "v1"
        assert len(data["hash"]) == 40

    def test_text_unchanged(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, ["tag", "--repo", initialized_repo, "set", "v1"])

        r = runner.invoke(main, [
            "tag", "--repo", initialized_repo, "hash", "v1",
        ])
        assert r.exit_code == 0, r.output
        assert len(r.output.strip()) == 40


# ---------------------------------------------------------------------------
# note list --format
# ---------------------------------------------------------------------------

class TestNoteListFormat:
    def test_json(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, [
            "note", "set", "--repo", initialized_repo, "hello",
        ])

        r = runner.invoke(main, [
            "note", "list", "--repo", initialized_repo, "--format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_jsonl(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, [
            "note", "set", "--repo", initialized_repo, "hello",
        ])

        r = runner.invoke(main, [
            "note", "list", "--repo", initialized_repo, "--format", "jsonl",
        ])
        assert r.exit_code == 0, r.output
        lines = [l for l in r.output.strip().split("\n") if l]
        for line in lines:
            h = json.loads(line)
            assert isinstance(h, str)

    def test_text_unchanged(self, runner, initialized_repo):
        _write_file(runner, initialized_repo, "x.txt")
        runner.invoke(main, [
            "note", "set", "--repo", initialized_repo, "hello",
        ])

        r = runner.invoke(main, [
            "note", "list", "--repo", initialized_repo,
        ])
        assert r.exit_code == 0, r.output
        assert len(r.output.strip()) >= 7  # at least a short hash


# ---------------------------------------------------------------------------
# backup/restore --output-format (dry-run only)
# ---------------------------------------------------------------------------

class TestBackupRestoreFormat:
    def test_backup_dry_run_json(self, runner, initialized_repo, tmp_path):
        _write_file(runner, initialized_repo, "x.txt")
        dest = str(tmp_path / "backup.git")
        runner.invoke(main, ["init", "--repo", dest])

        r = runner.invoke(main, [
            "backup", "--repo", initialized_repo, dest,
            "-n", "--output-format", "json",
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert "add" in data
        assert "total" in data
        assert isinstance(data["in_sync"], bool)

    def test_backup_dry_run_jsonl(self, runner, initialized_repo, tmp_path):
        _write_file(runner, initialized_repo, "x.txt")
        dest = str(tmp_path / "backup.git")
        runner.invoke(main, ["init", "--repo", dest])

        r = runner.invoke(main, [
            "backup", "--repo", initialized_repo, dest,
            "-n", "--output-format", "jsonl",
        ])
        assert r.exit_code == 0, r.output
        lines = [l for l in r.output.strip().split("\n") if l]
        for line in lines:
            item = json.loads(line)
            assert "action" in item
            assert "ref" in item

    def test_backup_dry_run_text_unchanged(self, runner, initialized_repo, tmp_path):
        _write_file(runner, initialized_repo, "x.txt")
        dest = str(tmp_path / "backup.git")
        runner.invoke(main, ["init", "--repo", dest])

        r = runner.invoke(main, [
            "backup", "--repo", initialized_repo, dest, "-n",
        ])
        assert r.exit_code == 0, r.output
        assert "ref(s) would be changed" in r.output or "in sync" in r.output.lower()

#!/usr/bin/env bash
# Read and validate interop repos using only the git CLI.
# Usage: git_read.sh <fixtures.json> <workdir> <prefix>
#
# Runs git fsck --strict on every repo, then spot-checks content,
# symlinks, executables, history, and notes against the fixture spec.
set -euo pipefail

exec python3 - "$@" <<'PYEOF'
import base64, json, subprocess, sys
from pathlib import Path


def git(repo, *args):
    """Run a git command and return stdout bytes."""
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
    )
    return result


def git_out(repo, *args):
    """Run a git command and return stdout as string, or None on failure."""
    r = git(repo, *args)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def git_bytes(repo, *args):
    """Run a git command and return raw stdout bytes, or None on failure."""
    r = git(repo, *args)
    if r.returncode != 0:
        return None
    return r.stdout


failures = 0


def fail(msg):
    global failures
    print(f"  FAIL {msg}")
    failures += 1


def ok(msg):
    print(f"  OK   {msg}")


def check_fixture(repo, name, spec):
    global failures

    if not repo.exists():
        fail(f"{name}: repo not found at {repo}")
        return

    # --- git fsck --strict ---
    r = git(repo, "fsck", "--strict")
    if r.returncode != 0:
        fail(f"{name}: git fsck --strict failed")
        for line in r.stderr.decode().splitlines()[:10]:
            print(f"    {line}")
        return
    ok(f"{name}: fsck --strict")

    branch = spec.get("branch", "main")
    tip = git_out(repo, "rev-parse", f"refs/heads/{branch}")
    if tip is None:
        fail(f"{name}: branch {branch} not found")
        return
    tip = tip.strip()

    # --- Text files ---
    for path, expected in spec.get("files", {}).items():
        actual = git_out(repo, "show", f"{tip}:{path}")
        if actual is None:
            fail(f"{name}: {path} not found")
        elif actual == expected:
            ok(f"{name}: {path}")
        else:
            fail(f"{name}: {path} content mismatch")

    # --- Symlinks ---
    for path, expected_target in spec.get("symlinks", {}).items():
        ls = git_out(repo, "ls-tree", "-r", tip, "--", path)
        if ls is None:
            fail(f"{name}: symlink {path} not found")
            continue
        mode = ls.split()[0]
        if mode != "120000":
            fail(f"{name}: {path} expected mode 120000, got {mode}")
            continue
        actual = git_out(repo, "show", f"{tip}:{path}")
        if actual is None:
            fail(f"{name}: symlink {path} blob not found")
        elif actual == expected_target:
            ok(f"{name}: symlink {path} -> {actual}")
        else:
            fail(f"{name}: symlink {path} target expected {expected_target!r}, got {actual!r}")

    # --- Binary files ---
    for path, b64 in spec.get("binary_files", {}).items():
        expected_bytes = base64.b64decode(b64)
        actual_bytes = git_bytes(repo, "show", f"{tip}:{path}")
        if actual_bytes is None:
            fail(f"{name}: binary {path} not found")
        elif actual_bytes == expected_bytes:
            ok(f"{name}: binary {path} ({len(expected_bytes)} bytes)")
        else:
            fail(f"{name}: binary {path} content mismatch")

    # --- Executable files ---
    for path, expected in spec.get("executable_files", {}).items():
        ls = git_out(repo, "ls-tree", "-r", tip, "--", path)
        if ls is None:
            fail(f"{name}: executable {path} not found")
            continue
        mode = ls.split()[0]
        if mode != "100755":
            fail(f"{name}: {path} expected mode 100755, got {mode}")
            continue
        actual = git_out(repo, "show", f"{tip}:{path}")
        if actual is None:
            fail(f"{name}: executable {path} blob not found")
        elif actual == expected:
            ok(f"{name}: executable {path}")
        else:
            fail(f"{name}: executable {path} content mismatch")

    # --- History ---
    if "commits" in spec:
        commits = spec["commits"]
        num_expected = len(commits)

        # HEAD content (last commit)
        last = commits[-1]
        for path, expected in last.get("files", {}).items():
            actual = git_out(repo, "show", f"{tip}:{path}")
            if actual is None:
                fail(f"{name}: HEAD {path} not found")
            elif actual == expected:
                ok(f"{name}: HEAD {path}")
            else:
                fail(f"{name}: HEAD {path} content mismatch")

        # Removed files
        for path in last.get("removes", []):
            r = git(repo, "show", f"{tip}:{path}")
            if r.returncode == 0:
                fail(f"{name}: {path} should have been removed")
            else:
                ok(f"{name}: {path} removed")

        # First commit content (skip initial empty commit)
        rev_list = git_out(repo, "rev-list", "--reverse", f"refs/heads/{branch}")
        if rev_list:
            all_commits = rev_list.strip().splitlines()
            # Index 1 = first user commit (index 0 = empty init commit)
            if len(all_commits) > 1:
                first_commit = all_commits[1]
                first = commits[0]
                for path, expected in first.get("files", {}).items():
                    actual = git_out(repo, "show", f"{first_commit}:{path}")
                    if actual is None:
                        fail(f"{name}: commit[0] {path} not found")
                    elif actual == expected:
                        ok(f"{name}: commit[0] {path}")
                    else:
                        fail(f"{name}: commit[0] {path} content mismatch")

            # Commit count (+1 for initial empty commit)
            commit_count = len(all_commits)
            expected_count = num_expected + 1
            if commit_count == expected_count:
                ok(f"{name}: {commit_count} commits in history")
            else:
                fail(f"{name}: expected {expected_count} commits, found {commit_count}")

    # --- Notes ---
    for ns, expected_text in spec.get("notes", {}).items():
        r = git(repo, "rev-parse", "--verify", f"refs/notes/{ns}")
        if r.returncode != 0:
            fail(f"{name}: notes[{ns}] ref not found")
            continue
        actual = git_out(repo, "notes", f"--ref={ns}", "show", tip)
        if actual is None:
            fail(f"{name}: notes[{ns}] not found for {tip}")
        elif actual == expected_text:
            ok(f"{name}: notes[{ns}]")
        else:
            fail(f"{name}: notes[{ns}] content mismatch")


def main():
    fixtures_path = sys.argv[1]
    workdir = Path(sys.argv[2])
    prefix = sys.argv[3] if len(sys.argv) > 3 else "py"

    fixtures = json.loads(Path(fixtures_path).read_text())

    for name, spec in fixtures.items():
        repo = workdir / f"{prefix}_{name}.git"
        check_fixture(repo, name, spec)

    print()
    if failures:
        print(f"{failures} failure(s)")
        sys.exit(1)
    else:
        print("All checks passed")


main()
PYEOF

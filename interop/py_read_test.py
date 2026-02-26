"""Read repos written by TypeScript and verify contents match fixtures."""

import base64
import json
import sys
from pathlib import Path

from vost import GitStore, FileType


def check_basic(fs, spec, name):
    """Check files, symlinks, binary_files, executable_files."""
    failures = 0

    # Text files
    for filepath, expected in spec.get("files", {}).items():
        actual = fs.read_text(filepath)
        if actual != expected:
            print(f"  FAIL {name}: {filepath} content expected {expected!r}, got {actual!r}")
            failures += 1
        else:
            print(f"  OK   {name}: {filepath}")

    # Symlinks
    for filepath, expected_target in spec.get("symlinks", {}).items():
        actual_target = fs.readlink(filepath)
        if actual_target != expected_target:
            print(f"  FAIL {name}: {filepath} link target expected {expected_target!r}, got {actual_target!r}")
            failures += 1
        else:
            print(f"  OK   {name}: symlink {filepath} -> {actual_target}")

    # Binary files
    for filepath, b64 in spec.get("binary_files", {}).items():
        expected_bytes = base64.b64decode(b64)
        actual_bytes = fs.read(filepath)
        if actual_bytes != expected_bytes:
            print(f"  FAIL {name}: {filepath} binary content mismatch")
            failures += 1
        else:
            print(f"  OK   {name}: binary {filepath} ({len(actual_bytes)} bytes)")

    # Executable files
    for filepath, expected in spec.get("executable_files", {}).items():
        actual = fs.read_text(filepath)
        if actual != expected:
            print(f"  FAIL {name}: {filepath} content expected {expected!r}, got {actual!r}")
            failures += 1
            continue
        # Check mode via walk
        found = False
        for dirpath, _subdirs, entries in fs.walk():
            for entry in entries:
                rel = f"{dirpath}/{entry.name}" if dirpath else entry.name
                if rel == filepath:
                    if entry.file_type != FileType.EXECUTABLE:
                        print(f"  FAIL {name}: {filepath} expected EXECUTABLE, got {entry.file_type}")
                        failures += 1
                    else:
                        print(f"  OK   {name}: executable {filepath}")
                    found = True
                    break
            if found:
                break

    # Verify file count
    all_files = set()
    for dirpath, _subdirs, entries in fs.walk():
        for entry in entries:
            rel = f"{dirpath}/{entry.name}" if dirpath else entry.name
            all_files.add(rel)
    expected_files = set()
    expected_files.update(spec.get("files", {}).keys())
    expected_files.update(spec.get("symlinks", {}).keys())
    expected_files.update(spec.get("binary_files", {}).keys())
    expected_files.update(spec.get("executable_files", {}).keys())

    extra = all_files - expected_files
    missing = expected_files - all_files
    if extra:
        print(f"  FAIL {name}: unexpected files {extra}")
        failures += 1
    if missing:
        print(f"  FAIL {name}: missing files {missing}")
        failures += 1

    return failures


def check_history(store, branch, spec, name):
    """Check multi-commit history scenario."""
    failures = 0
    fs = store.branches[branch]

    # Final state: last commit's cumulative result
    last = spec["commits"][-1]
    for filepath, expected in last.get("files", {}).items():
        actual = fs.read_text(filepath)
        if actual != expected:
            print(f"  FAIL {name}: HEAD {filepath} expected {expected!r}, got {actual!r}")
            failures += 1
        else:
            print(f"  OK   {name}: HEAD {filepath}")

    # Removed files should not exist
    for filepath in last.get("removes", []):
        if fs.exists(filepath):
            print(f"  FAIL {name}: {filepath} should have been removed")
            failures += 1
        else:
            print(f"  OK   {name}: {filepath} removed")

    # Check we can walk back through history
    num_commits = len(spec["commits"])
    back_fs = fs.back(num_commits - 1)
    first = spec["commits"][0]
    for filepath, expected in first.get("files", {}).items():
        actual = back_fs.read_text(filepath)
        if actual != expected:
            print(f"  FAIL {name}: commit[0] {filepath} expected {expected!r}, got {actual!r}")
            failures += 1
        else:
            print(f"  OK   {name}: commit[0] {filepath}")

    # Verify commit count by walking parents
    count = 0
    current = fs
    while True:
        count += 1
        try:
            current = current.back(1)
        except (ValueError, Exception):
            break
    # +1 for the initial empty commit created by GitStore.open
    if count != num_commits + 1:
        print(f"  FAIL {name}: expected {num_commits + 1} commits, found {count}")
        failures += 1
    else:
        print(f"  OK   {name}: {count} commits in history")

    return failures


def check_notes(store, branch, spec, name):
    """Check that notes on HEAD match expected values."""
    failures = 0
    fs = store.branches[branch]
    commit_hash = fs.commit_hash

    for namespace, expected_text in spec["notes"].items():
        try:
            actual = store.notes[namespace][commit_hash]
            if actual != expected_text:
                print(f"  FAIL {name}: notes[{namespace}] expected {expected_text!r}, got {actual!r}")
                failures += 1
            else:
                print(f"  OK   {name}: notes[{namespace}]")
        except KeyError:
            print(f"  FAIL {name}: notes[{namespace}] not found for {commit_hash}")
            failures += 1

    return failures


def main(fixtures_path: str, repo_dir: str, prefix: str = "ts") -> None:
    fixtures = json.loads(Path(fixtures_path).read_text())
    failures = 0

    for name, spec in fixtures.items():
        repo_path = Path(repo_dir) / f"{prefix}_{name}.git"
        branch = spec.get("branch", "main")

        if not repo_path.exists():
            print(f"  FAIL {name}: repo not found at {repo_path}")
            failures += 1
            continue

        store = GitStore.open(repo_path, create=False)

        if "commits" in spec:
            failures += check_history(store, branch, spec, name)
        else:
            fs = store.branches[branch]
            failures += check_basic(fs, spec, name)

        if "notes" in spec:
            failures += check_notes(store, branch, spec, name)

    if failures:
        print(f"\n{failures} failure(s)")
        sys.exit(1)
    else:
        print("\nAll checks passed")


if __name__ == "__main__":
    prefix = sys.argv[3] if len(sys.argv) > 3 else "ts"
    main(sys.argv[1], sys.argv[2], prefix)

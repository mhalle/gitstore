"""Write repos from fixtures.json so TypeScript can read them."""

import base64
import json
import sys
from pathlib import Path

from gitstore import GitStore, FileType


def write_scenario(store, branch, spec):
    """Write a single scenario (non-history)."""
    fs = store.branches[branch]
    with fs.batch(message="interop") as batch:
        for filepath, content in spec.get("files", {}).items():
            batch.write(filepath, content.encode())
        for filepath, target in spec.get("symlinks", {}).items():
            batch.write_symlink(filepath, target)
        for filepath, b64 in spec.get("binary_files", {}).items():
            batch.write(filepath, base64.b64decode(b64))
        for filepath, content in spec.get("executable_files", {}).items():
            batch.write(filepath, content.encode(), mode=FileType.EXECUTABLE)


def write_history(store, branch, spec):
    """Write a multi-commit history scenario."""
    fs = store.branches[branch]
    for step in spec["commits"]:
        with fs.batch(message=step["message"]) as batch:
            for filepath, content in step.get("files", {}).items():
                batch.write(filepath, content.encode())
            for filepath in step.get("removes", []):
                batch.remove(filepath)
        fs = batch.fs


def write_notes(store, branch, spec):
    """Write notes on the HEAD commit for each namespace."""
    fs = store.branches[branch]
    commit_hash = fs.commit_hash
    for namespace, text in spec["notes"].items():
        store.notes[namespace][commit_hash] = text


def main(fixtures_path: str, output_dir: str) -> None:
    fixtures = json.loads(Path(fixtures_path).read_text())

    for name, spec in fixtures.items():
        repo_path = Path(output_dir) / f"py_{name}.git"
        branch = spec.get("branch", "main")
        store = GitStore.open(repo_path, branch=branch)

        if "commits" in spec:
            write_history(store, branch, spec)
        else:
            write_scenario(store, branch, spec)

        if "notes" in spec:
            write_notes(store, branch, spec)

        print(f"  py_write: {name} -> {repo_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

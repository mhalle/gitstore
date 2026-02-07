# gitstore

A versioned key-value filesystem backed by bare Git repositories. Store, retrieve, and version binary data using an immutable-snapshot API — every write produces a new commit, and old snapshots remain accessible forever.

Built on [pygit2](https://www.pygit2.org/), gitstore gives you Git's content-addressable storage, branching, tagging, and history without touching the working directory or the `git` CLI.

## Installation

```
pip install gitstore
```

Requires Python 3.10+ and pygit2 >= 1.14.

## Quick start

```python
from gitstore import GitStore

# Create a new repository with a "main" branch
repo = GitStore.open("data.git", create="main")

# Get a snapshot of the branch
fs = repo.branches["main"]

# Write a file — returns a new immutable snapshot
fs = fs.write("hello.txt", b"Hello, world!")

# Read it back
print(fs.read("hello.txt"))  # b'Hello, world!'

# Every write is a commit
print(fs.hash)     # full 40-char SHA
print(fs.message)  # 'Write hello.txt'
```

## Core concepts

**`GitStore`** opens or creates a bare Git repository. It exposes `branches` and `tags` as dict-like objects.

**`FS`** is an immutable snapshot of a committed tree. Reading methods (`read`, `ls`, `walk`, `exists`, `open`) never mutate state. Writing methods (`write`, `remove`, `batch`) return a *new* `FS` pointing at the new commit — the original `FS` is unchanged.

Snapshots obtained from **branches** are writable. Snapshots obtained from **tags** are read-only.

## API

### Opening a repository

```python
# Create new repo with an initial branch
repo = GitStore.open("data.git", create="main")

# Create empty repo (no branches)
repo = GitStore.open("data.git", create=True)

# Open existing repo
repo = GitStore.open("data.git")

# Custom author for commits
repo = GitStore.open("data.git", create="main", author="alice", email="alice@example.com")
```

### Branches and tags

```python
# Access branches and tags like dicts
fs = repo.branches["main"]
repo.branches["experiment"] = fs   # fork a branch
del repo.branches["experiment"]    # delete a branch

# Tags are immutable — overwriting raises KeyError
repo.tags["v1.0"] = fs
snapshot = repo.tags["v1.0"]       # read-only FS (branch=None)

# Iteration
for name in repo.branches:
    print(name)

print(len(repo.tags))
print("main" in repo.branches)    # True
```

### Reading

```python
data = fs.read("path/to/file.bin")           # bytes
entries = fs.ls()                             # root listing
entries = fs.ls("src")                        # subdirectory listing
exists = fs.exists("path/to/file.bin")        # bool

# Walk the tree (like os.walk)
for dirpath, dirnames, filenames in fs.walk():
    print(dirpath, dirnames, filenames)

# Walk a subtree
for dirpath, dirnames, filenames in fs.walk("src"):
    ...

# File-like object
with fs.open("data.bin", "rb") as f:
    header = f.read(4)
    f.seek(0)
    all_data = f.read()
```

### Writing

Every write auto-commits and returns a new snapshot:

```python
fs = fs.write("config.json", b'{"key": "value"}')
fs = fs.write("data/nested/file.bin", b"\x00\x01\x02")  # directories created automatically

fs = fs.remove("old-file.txt")  # raises FileNotFoundError if missing
```

The original `FS` is never mutated:

```python
fs1 = repo.branches["main"]
fs2 = fs1.write("new.txt", b"data")
assert not fs1.exists("new.txt")  # fs1 is unchanged
assert fs2.exists("new.txt")
```

### Batch writes

Multiple writes/removes in a single commit:

```python
with fs.batch() as b:
    b.write("a.txt", b"alpha")
    b.write("b.txt", b"bravo")
    b.remove("old.txt")

    # File-like interface
    with b.open("c.txt", "wb") as f:
        f.write(b"charlie")

fs = b.fs  # new snapshot after the batch commits
```

If an exception occurs inside the batch, nothing is committed:

```python
try:
    with fs.batch() as b:
        b.write("x.txt", b"data")
        raise RuntimeError("abort")
except RuntimeError:
    pass
assert b.fs is None  # no commit was made
```

### File-like objects

```python
# Reading
with fs.open("data.bin", "rb") as f:
    chunk = f.read(1024)
    f.seek(0)
    pos = f.tell()

# Writing (commits on context manager exit)
with fs.open("output.bin", "wb") as f:
    f.write(b"some data")
new_fs = f.fs
```

### History

```python
# Parent snapshot
parent = fs.parent       # FS or None (for the initial commit)

# Walk the full commit log
for snapshot in fs.log():
    print(snapshot.hash, snapshot.message)
```

### Dump to filesystem

Export the entire tree to a directory on disk:

```python
fs.dump("/tmp/export")
# Creates /tmp/export/hello.txt, /tmp/export/src/main.py, etc.
```

### Snapshot properties

```python
fs.hash      # str — full 40-character commit SHA
fs.branch    # str | None — branch name, or None for tags
fs.message   # str — commit message
```

## Concurrency safety

gitstore detects stale writes. If a branch advances after you obtain a snapshot (e.g. another process or another `FS` wrote to it), attempting to write from the stale snapshot raises `StaleSnapshotError`:

```python
from gitstore import StaleSnapshotError

fs = repo.branches["main"]
fs.write("a.txt", b"a")         # advances the branch

try:
    fs.write("b.txt", b"b")     # fs is now stale
except StaleSnapshotError:
    fs = repo.branches["main"]  # re-fetch and retry
```

This prevents silent data loss from concurrent writes.

## Error handling

| Exception | When |
|-----------|------|
| `FileNotFoundError` | `read`/`remove` on a missing path; opening a missing repo |
| `FileExistsError` | Creating a repo at a path that already exists |
| `IsADirectoryError` | `read` on a directory path |
| `NotADirectoryError` | `ls`/`walk` on a file path |
| `PermissionError` | Writing to a tag snapshot |
| `KeyError` | Accessing a missing branch/tag; overwriting an existing tag |
| `ValueError` | Invalid path (`..`, empty segments); unsupported open mode |
| `TypeError` | Assigning a non-`FS` value to a branch or tag |
| `StaleSnapshotError` | Writing from a snapshot whose branch has moved forward |

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Run tests
uv run python -m pytest -v
```

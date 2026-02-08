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

**Bare repository.** gitstore uses a *bare* Git repository — one that contains only Git's internal object database, with no working directory or checked-out files. You won't see your stored files by browsing the repo directory; all data lives inside Git's content-addressable object store and is accessed exclusively through the gitstore API. This is by design: it avoids filesystem conflicts, keeps the storage compact, and lets Git handle deduplication and integrity.

**`GitStore`** opens or creates a bare repository. It exposes `branches` and `tags` as [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping) objects (supporting `.get`, `.keys`, `.values`, `.items`, etc.).

**`FS`** is an immutable snapshot of a committed tree. Reading methods (`read`, `ls`, `walk`, `exists`, `open`) never mutate state. Writing methods (`write`, `remove`, `batch`) return a *new* `FS` pointing at the new commit — the original `FS` is unchanged.

Snapshots obtained from **branches** are writable. Snapshots obtained from **tags** are read-only.

## API

### Opening a repository

```python
# Create new repo with an initial branch
repo = GitStore.open("data.git", create="main")

# Equivalent — separate create and branch args
repo = GitStore.open("data.git", create=True, branch="main")

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

# Full MutableMapping interface — .get, .keys, .values, .items, etc.
fs = repo.branches.get("main")              # returns None if missing
for name, snapshot in repo.branches.items():
    print(name, snapshot.hash)
```

### Paths

All path arguments throughout the API (`read`, `write`, `remove`, `ls`, `walk`, `exists`, `open`, `batch.write`, `batch.remove`, `batch.open`) accept `str` or any `os.PathLike` (e.g. `pathlib.PurePosixPath`). Paths use forward slashes as separators.

### Reading

```python
from pathlib import PurePosixPath

data = fs.read("path/to/file.bin")           # bytes
data = fs.read(PurePosixPath("path/to/file.bin"))  # PathLike works too
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
fs = fs.write("script.sh", b"#!/bin/sh\n", mode=0o100755)  # executable
fs = fs.write("config.json", b"{}", message="Reset config")  # custom commit message

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

# Custom commit message
with fs.batch(message="Import dataset v2") as b:
    b.write("data.csv", csv_bytes)
    b.write("meta.json", meta_bytes)
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

File objects support `closed`, `readable()`, `writable()`, and `seekable()` for compatibility with code that checks standard file properties.

```python
# Reading — supports read, seek, tell, close
with fs.open("data.bin", "rb") as f:
    chunk = f.read(1024)
    f.seek(0)
    pos = f.tell()
    assert f.readable() and f.seekable()

# Writing (commits on context manager exit) — or call close() explicitly
with fs.open("output.bin", "wb") as f:
    f.write(b"some data")
    assert f.writable()
new_fs = f.fs
```

### History

```python
# Parent snapshot
parent = fs.parent       # FS or None (for the initial commit)

# Walk the full commit log
for snapshot in fs.log():
    print(snapshot.hash, snapshot.message)

# Only commits that changed a specific file
for snapshot in fs.log("path/to/file.txt"):
    print(snapshot.hash, snapshot.message)

# Same thing using the keyword form
for snapshot in fs.log(at="path/to/file.txt"):
    print(snapshot.hash, snapshot.message)

# Filter by commit message (supports * and ? wildcards)
for snapshot in fs.log(match="deploy*"):
    print(snapshot.hash, snapshot.message)

# Combine both filters (AND)
for snapshot in fs.log(at="config.json", match="fix*"):
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
fs.hash          # str — full 40-character commit SHA
fs.branch        # str | None — branch name, or None for tags
fs.message       # str — commit message
fs.time          # datetime — commit timestamp (timezone-aware)
fs.author_name   # str — commit author name
fs.author_email  # str — commit author email
```

## Concurrency safety

gitstore uses an advisory file lock (`gitstore.lock` in the repo directory) to make the stale-snapshot check and ref update atomic on a single machine. If a branch advances after you obtain a snapshot, attempting to write from the stale snapshot raises `StaleSnapshotError`:

```python
from gitstore import StaleSnapshotError

fs = repo.branches["main"]
_ = fs.write("a.txt", b"a")     # advances the branch (returns new FS)

try:
    fs.write("b.txt", b"b")     # fs is now stale — branch moved past it
except StaleSnapshotError:
    fs = repo.branches["main"]  # re-fetch and retry
```

**Guarantees and limitations:**

- Single-machine, multi-process writes to the same branch are serialized by the file lock and will never silently lose commits.
- When a stale write is rejected, the commit object is created but unreferenced. These dangling objects are harmless and will be cleaned up by `git gc`.
- Cross-machine coordination (e.g. NFS-mounted repos) is not supported — file locks are not reliable over network filesystems.

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
| `RuntimeError` | Writing/removing on a closed `Batch` |
| `StaleSnapshotError` | Writing from a snapshot whose branch has moved forward |

## CLI

gitstore includes a command-line interface for working with bare repos without writing Python. Install the package to get the `gitstore` command.

Specify the repository with `--repo`/`-r` or the `GITSTORE_REPO` environment variable. Use `--branch`/`-b` to select a branch (defaults to `main`). For `cp` and `cptree`, prefix repo-side paths with `:` to distinguish them from local paths. For other commands (`ls`, `cat`, `rm`) the `:` prefix is optional.

```bash
# Set once per session
export GITSTORE_REPO=/path/to/repo.git
gitstore init
gitstore cp local-file.txt :remote-file.txt
gitstore ls

# Or per-command
gitstore ls --repo /path/to/repo.git
gitstore -r /path/to/repo.git ls
```

```bash
# Create a repo
gitstore init --repo /path/to/repo.git

# Destroy a repo
gitstore destroy                          # fails if repo has data
gitstore destroy -f                       # force-remove non-empty repo

# Copy files in and out
gitstore cp local-file.txt :remote-file.txt
gitstore cp :remote-file.txt local-copy.txt
gitstore cp local-file.txt :              # keep original name at root

# Multiple sources (last arg is destination directory)
gitstore cp file1.txt file2.txt :dir
gitstore cp :a.txt :b.txt ./local-dir

# Set file mode
gitstore cp script.sh :script.sh --mode 755

# Copy directory trees
gitstore cptree ./local-dir :repo-dir
gitstore cptree :repo-dir ./local-dir

# Browse contents
gitstore ls
gitstore ls subdir
gitstore cat file.txt

# Remove files
gitstore rm old-file.txt

# View commit history
gitstore log
gitstore log --at file.txt                # commits that changed this file
gitstore log --match "deploy*"            # commits matching message pattern
gitstore log --at file.txt --match "fix*" # both filters (AND)
gitstore log --format json                # JSON array
gitstore log --format jsonl               # one JSON object per line

# Manage branches
gitstore branch                           # list
gitstore branch create dev                # empty orphan branch
gitstore branch create dev --from main    # fork from existing ref
gitstore branch delete dev

# Manage tags
gitstore tag create v1.0 main
gitstore tag create v1.0-fix main --at bugfix.py  # tag the commit that last changed bugfix.py
gitstore tag delete v1.0

# Export repo contents to a zip file
gitstore zip archive.zip
gitstore zip archive.zip --at file.txt    # snapshot where file.txt last changed
gitstore zip archive.zip --match "v1*"    # snapshot matching message pattern

# Import a zip file into the repo
gitstore unzip archive.zip
gitstore unzip archive.zip -m "Import data"
gitstore unzip archive.zip -b dev

# Export repo contents to a tar archive
gitstore tar archive.tar
gitstore tar archive.tar.gz                # auto-compress based on extension
gitstore tar - | gzip > archive.tar.gz     # or pipe to gzip
gitstore tar archive.tar --at file.txt     # snapshot where file.txt last changed

# Import a tar archive into the repo
gitstore untar archive.tar.gz              # auto-detects compression
gitstore untar                             # reads from stdin (default)
cat archive.tar.gz | gitstore untar        # equivalent
gitstore untar archive.tar -m "Import data"
```

Write commands (`cp`, `cptree`, `rm`, `unzip`, `untar`) accept `-m` for custom commit messages. Use `-b` on any command to target a branch other than `main`. `cp` accepts `--mode 644` or `--mode 755` to set file permissions. Pass `-v` before the command for status messages on stderr. `zip` and `tar` accept `-` as FILENAME to write to stdout; `untar` defaults to stdin when no filename is given.

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Run tests
uv run python -m pytest -v
```

# gitstore

A versioned key-value filesystem backed by bare Git repositories. Store, retrieve, and version binary data using an immutable-snapshot API -- every write produces a new commit, and old snapshots remain accessible forever.

Built on [dulwich](https://www.dulwich.io/), gitstore gives you Git's content-addressable storage, branching, tagging, and history without touching the working directory or the `git` CLI.

## Installation

```
pip install gitstore          # core library (dulwich only)
pip install gitstore[cli]     # adds the gitstore command-line tool
```

Requires Python 3.10+.

## Quick start

```python
from gitstore import GitStore

# Create (or open) a repository with a "main" branch
repo = GitStore.open("data.git")

# Get a snapshot of the branch
fs = repo.branches["main"]

# Write a file -- returns a new immutable snapshot
fs = fs.write("hello.txt", b"Hello, world!")

# Read it back
print(fs.read("hello.txt"))     # b'Hello, world!'

# Every write is a commit
print(fs.commit_hash)           # full 40-char SHA
print(fs.message)               # '+ hello.txt'
```

## Core concepts

**Bare repository.** gitstore uses a *bare* Git repository -- one that contains only Git's internal object database, with no working directory or checked-out files. You won't see your stored files by browsing the repo directory; all data lives inside Git's content-addressable object store and is accessed exclusively through the gitstore API. This is by design: it avoids filesystem conflicts, keeps the storage compact, and lets Git handle deduplication and integrity.

**`GitStore`** opens or creates a bare repository. It exposes `branches` and `tags` as [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping) objects (supporting `.get`, `.keys`, `.values`, `.items`, etc.).

**`FS`** is an immutable snapshot of a committed tree. Reading methods (`read`, `ls`, `walk`, `exists`, `open`) never mutate state. Writing methods (`write`, `write_from_file`, `remove`, `batch`) return a *new* `FS` pointing at the new commit -- the original `FS` is unchanged.

Snapshots obtained from **branches** are writable. Snapshots obtained from **tags** are read-only.

## API

### Opening a repository

```python
repo = GitStore.open("data.git")                         # create or open
repo = GitStore.open("data.git", create=False)            # open only
repo = GitStore.open("data.git", branch="dev")            # custom initial branch
repo = GitStore.open("data.git", branch=None)             # branchless
repo = GitStore.open("data.git", author="alice",          # custom author
                     email="alice@example.com")
```

### Branches and tags

```python
fs = repo.branches["main"]
repo.branches["experiment"] = fs   # fork a branch
del repo.branches["experiment"]    # delete a branch

repo.tags["v1.0"] = fs            # create a tag
snapshot = repo.tags["v1.0"]       # read-only FS

for name in repo.branches:
    print(name)
"main" in repo.branches           # True
```

### Reading

```python
data = fs.read("path/to/file.bin")           # bytes
text = fs.read_text("config.json")           # str (UTF-8)
entries = fs.ls()                             # root listing
entries = fs.ls("src")                        # subdirectory listing
exists = fs.exists("path/to/file.bin")        # bool

# Walk the tree (like os.walk)
for dirpath, dirnames, file_entries in fs.walk():
    for entry in file_entries:
        print(entry.name, entry.file_type)    # WalkEntry with name, oid, filemode

# Glob
matches = fs.glob("**/*.py")                 # sorted list of matching paths

# File-like object
with fs.open("data.bin", "rb") as f:
    header = f.read(4)
```

### Writing

Every write auto-commits and returns a new snapshot:

```python
fs = fs.write("config.json", b'{"key": "value"}')
fs = fs.write_text("notes.txt", "Hello")                  # str convenience
fs = fs.write("script.sh", b"#!/bin/sh\n", mode=0o100755) # executable
fs = fs.write("config.json", b"{}", message="Reset")      # custom message
fs = fs.write_from_file("big.bin", "/data/big.bin")        # from disk
fs = fs.write_symlink("link", "target")                    # symlink
fs = fs.remove("old-file.txt")
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
with fs.batch(message="Import dataset v2") as b:
    b.write("a.txt", b"alpha")
    b.write_from_file("big.bin", "/data/big.bin")
    b.write_symlink("link.txt", "a.txt")
    b.remove("old.txt")
fs = b.fs  # new snapshot after the batch commits
```

If an exception occurs inside the batch, nothing is committed.

### History

```python
parent = fs.parent                               # FS or None
ancestor = fs.back(3)                            # 3 commits back

for snapshot in fs.log():                        # full commit log
    print(snapshot.commit_hash, snapshot.message)

for snapshot in fs.log("config.json"):           # file history
    print(snapshot.commit_hash, snapshot.message)

for snapshot in fs.log(match="deploy*"):         # message filter
    ...

for snapshot in fs.log(before=cutoff):           # date filter
    ...

fs = fs.undo()                                   # move branch back 1 commit
fs = fs.redo()                                   # move branch forward 1 reflog step
```

### Export

```python
fs.export("/tmp/export")
# Creates /tmp/export/hello.txt, /tmp/export/src/main.py, etc.
```

### Copy and sync

```python
# Disk to repo
fs = fs.copy_in(["./data/"], "backup")
print(fs.changes.add)                            # [FileEntry(...), ...]

# Repo to disk
fs.copy_out(["docs"], "./local-docs")

# Sync (make identical, including deletes)
fs = fs.sync_in("./local", "data")
fs.sync_out("data", "./local")

# Remove and move within repo
fs = fs.remove(["old-dir"], recursive=True)
fs = fs.move(["old.txt"], "new.txt")
```

### Snapshot properties

```python
fs.commit_hash           # str -- full 40-character commit SHA
fs.branch                # str | None -- branch name, or None for tags
fs.message               # str -- commit message
fs.time                  # datetime -- commit timestamp (timezone-aware)
fs.author_name           # str -- commit author name
fs.author_email          # str -- commit author email
fs.changes               # ChangeReport | None -- changes from last operation
```

### Backup and restore

```python
diff = repo.backup("https://github.com/user/repo.git")    # MirrorDiff
diff = repo.restore("https://github.com/user/repo.git")   # MirrorDiff
diff = repo.backup(url, dry_run=True)                      # preview only
```

## Concurrency safety

gitstore uses an advisory file lock (`gitstore.lock` in the repo directory) to make the stale-snapshot check and ref update atomic on a single machine. If a branch advances after you obtain a snapshot, attempting to write from the stale snapshot raises `StaleSnapshotError`:

```python
from gitstore import StaleSnapshotError

fs = repo.branches["main"]
_ = fs.write("a.txt", b"a")     # advances the branch

try:
    fs.write("b.txt", b"b")     # fs is now stale
except StaleSnapshotError:
    fs = repo.branches["main"]  # re-fetch and retry
```

For single-file writes, `retry_write` handles the re-fetch-and-retry loop automatically with exponential backoff:

```python
from gitstore import retry_write
fs = retry_write(repo, "main", "file.txt", data)
```

**Guarantees and limitations:**

- Single-machine, multi-process writes to the same branch are serialized by the file lock and will never silently lose commits.
- When a stale write is rejected, the commit object is created but unreferenced. These dangling objects are harmless and will be cleaned up by `git gc`.
- Cross-machine coordination (e.g. NFS-mounted repos) is not supported -- file locks are not reliable over network filesystems.

**Maintenance:** gitstore repos are standard bare Git repositories. Run `gitstore gc` (or `git gc` directly) to repack loose objects and prune unreferenced data. This is optional but can reduce disk usage for long-lived repos.

## Error handling

| Exception | When |
|-----------|------|
| `FileNotFoundError` | `read`/`remove` on a missing path; `write_from_file` with a missing local file; opening a missing repo with `create=False` |
| `IsADirectoryError` | `read` on a directory path; `write_from_file` with a directory; `remove` on a directory |
| `NotADirectoryError` | `ls`/`walk` on a file path |
| `PermissionError` | Writing to a tag snapshot |
| `KeyError` | Accessing a missing branch/tag; overwriting an existing tag |
| `ValueError` | Invalid path (`..`, empty segments); unsupported open mode |
| `TypeError` | Assigning a non-`FS` value to a branch or tag |
| `RuntimeError` | Writing/removing on a closed `Batch` |
| `StaleSnapshotError` | Writing from a snapshot whose branch has moved forward |

## CLI

gitstore includes a command-line interface. Install with `pip install gitstore[cli]`.

```bash
export GITSTORE_REPO=/path/to/repo.git    # or pass --repo/-r per command
```

### Repo paths and the `:` prefix

Because gitstore commands work with both local files and files stored in the repo, you need a way to tell them apart. **A leading `:` marks a repo path.** Without it, the argument is a local filesystem path.

```
:file.txt              repo path on the current branch
:                      repo root
main:file.txt          repo path on the "main" branch
v1.0:data/             repo path on the "v1.0" tag
main~3:file.txt        3 commits back on main
```

This applies to `cp`, `sync`, `rm`, `mv`, `ls`, `cat`, and other commands. For `ls`, `cat`, `rm`, and `write` the `:` is optional (arguments are always repo paths), but it is **required** for `cp`, `sync`, and `mv` to distinguish repo paths from local paths.

For full details on path parsing, ancestor syntax (`~N`), and interaction with flags, see [Path Syntax](docs/paths.md).

```bash
# Repository management
gitstore init
gitstore destroy -f
gitstore gc

# Copy files (disk <-> repo, repo <-> repo)
gitstore cp local-file.txt :                        # disk to repo root
gitstore cp ./mydir/ :dest                           # contents mode
gitstore cp './src/*.py' :backup                     # glob
gitstore cp :file.txt ./local.txt                    # repo to disk
gitstore cp -n ./mydir :dest                         # dry run

# Sync (make identical, including deletes)
gitstore sync ./local :repo_path
gitstore sync :repo_path ./local
gitstore sync --watch ./dir :data                    # continuous watch mode

# Browse
gitstore ls
gitstore ls -R :src
gitstore cat file.txt

# Write stdin
echo "hello" | gitstore write file.txt
cmd | gitstore write log.txt -p | grep error         # passthrough (tee)

# Remove and move within repo
gitstore rm old-file.txt
gitstore rm -R :dir
gitstore mv :old.txt :new.txt
gitstore mv ':*.txt' :archive/

# History
gitstore log
gitstore log --path file.txt --format jsonl
gitstore diff --back 3
gitstore undo
gitstore redo

# Branches and tags
gitstore branch set dev --ref main
gitstore branch exists dev
gitstore tag set v1.0
gitstore tag delete v1.0

# Archives
gitstore archive out.zip
gitstore unarchive data.tar.gz

# Mirror (backup/restore all refs)
gitstore backup https://github.com/user/repo.git
gitstore restore https://github.com/user/repo.git
gitstore backup -n https://github.com/user/repo.git  # dry run

# Serve files over HTTP
gitstore serve                                        # single branch
gitstore serve --all --cors                           # all refs with CORS

# Serve repo over git protocol (read-only)
gitstore gitserve
```

For full CLI documentation, see [docs/cli.md](docs/cli.md).

## Documentation

- [Documentation hub](docs/index.md) -- quick start and navigation
- [Python API Reference](docs/api.md) -- classes, methods, and data types
- [CLI Reference](docs/cli.md) -- the `gitstore` command-line tool
- [Path Syntax](docs/paths.md) -- how `ref:path` works across commands

## Development

```bash
uv sync --dev       # install with dev dependencies (includes CLI)
uv run python -m pytest -v
```

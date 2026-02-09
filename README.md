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

**`FS`** is an immutable snapshot of a committed tree. Reading methods (`read`, `ls`, `walk`, `exists`, `open`) never mutate state. Writing methods (`write`, `write_from`, `remove`, `batch`) return a *new* `FS` pointing at the new commit — the original `FS` is unchanged.

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

All path arguments throughout the API (`read`, `write`, `write_from`, `remove`, `ls`, `walk`, `exists`, `open`, `batch.write`, `batch.write_from`, `batch.remove`, `batch.open`) accept `str` or any `os.PathLike` (e.g. `pathlib.PurePosixPath`). Paths use forward slashes as separators.

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

# Write from a file on disk (avoids loading into Python memory)
fs = fs.write_from("big-dataset.bin", "/data/dataset.bin")

# Preserves executable bit from disk permissions
fs = fs.write_from("script.sh", "/usr/local/bin/script.sh")

# Override mode explicitly
fs = fs.write_from("script.sh", "./script.sh", mode=0o100755)

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
    b.write("script.sh", b"#!/bin/sh", mode=0o100755)  # executable mode
    b.write_from("big.bin", "/data/big.bin")            # from disk
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
for snapshot in fs.log(path="path/to/file.txt"):
    print(snapshot.hash, snapshot.message)

# Filter by commit message (supports * and ? wildcards)
for snapshot in fs.log(match="deploy*"):
    print(snapshot.hash, snapshot.message)

# Only commits on or before a date
from datetime import datetime, timezone
cutoff = datetime(2024, 6, 1, tzinfo=timezone.utc)
for snapshot in fs.log(before=cutoff):
    print(snapshot.hash, snapshot.message)

# Combine filters (AND)
for snapshot in fs.log(path="config.json", match="fix*"):
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

**Maintenance:** gitstore repos are standard bare Git repositories. You can run `git gc /path/to/repo.git` to repack loose objects and prune unreferenced data. This is optional — Git objects are cheap and the repo will work fine without it — but it can reduce disk usage for long-lived repos with many writes.

## Error handling

| Exception | When |
|-----------|------|
| `FileNotFoundError` | `read`/`remove` on a missing path; `write_from` with a missing local file; opening a missing repo |
| `FileExistsError` | Creating a repo at a path that already exists |
| `IsADirectoryError` | `read` on a directory path; `write_from` with a directory as local path; `remove` on a directory |
| `NotADirectoryError` | `ls`/`walk` on a file path |
| `PermissionError` | Writing to a tag snapshot |
| `KeyError` | Accessing a missing branch/tag; overwriting an existing tag |
| `ValueError` | Invalid path (`..`, empty segments); unsupported open mode |
| `TypeError` | Assigning a non-`FS` value to a branch or tag |
| `RuntimeError` | Writing/removing on a closed `Batch` |
| `StaleSnapshotError` | Writing from a snapshot whose branch has moved forward |

## CLI

gitstore includes a command-line interface for working with bare repos without writing Python. Install the package to get the `gitstore` command.

Specify the repository with `--repo`/`-r` or the `GITSTORE_REPO` environment variable. Use `--branch`/`-b` to select a branch (defaults to `main`). Use `--hash` to read from any branch, tag, or commit hash. For `cp` and `cptree`, prefix repo-side paths with `:` to distinguish them from local paths. For other commands (`ls`, `cat`, `rm`) the `:` prefix is optional.

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

# Copy directory trees (symlinks preserved by default)
gitstore cptree ./local-dir :repo-dir
gitstore cptree ./local-dir :repo-dir --follow-symlinks  # dereference symlinks
gitstore cptree :repo-dir ./local-dir

# Browse contents
gitstore ls
gitstore ls subdir
gitstore cat file.txt

# Remove files
gitstore rm old-file.txt

# View commit history
gitstore log
gitstore log --path file.txt                # commits that changed this file
gitstore log --match "deploy*"            # commits matching message pattern
gitstore log --path file.txt --match "fix*" # both filters (AND)
gitstore log --before 2024-06-01          # commits on or before this date
gitstore log --before 2024-06-01T14:30:00 # date-time (ISO 8601)
gitstore log --format json                # JSON array
gitstore log --format jsonl               # one JSON object per line

# Manage branches
gitstore branch                           # list
gitstore branch create dev                # empty orphan branch
gitstore branch create dev --from main    # fork from existing ref
gitstore branch create dev --from main --path config.json  # fork from commit that last changed a file
gitstore branch create dev --from main --match "deploy*"   # fork from commit matching message
gitstore branch create dev --from main --before 2024-06-01 # fork from commit as of a date
gitstore branch delete dev

# Manage tags
gitstore tag create v1.0 main
gitstore tag create v1.0-fix main --path bugfix.py         # tag the commit that last changed bugfix.py
gitstore tag create v1.0 main --match "deploy*"            # tag the latest deploy commit
gitstore tag create v1.0 main --before 2024-06-01          # tag the state as of a date
gitstore tag delete v1.0

# Export to an archive (format auto-detected from extension)
gitstore archive archive.zip
gitstore archive archive.tar.gz
gitstore archive archive.tar --path file.txt  # snapshot where file.txt last changed
gitstore archive archive.zip --match "v1*"    # snapshot matching message pattern
gitstore archive out.dat --format zip         # override format detection
gitstore archive - --format tar | gzip > a.tar.gz  # stdout (requires --format)

# Import an archive (format auto-detected from extension)
gitstore unarchive archive.zip
gitstore unarchive archive.tar.gz
gitstore unarchive data.bin --format tar      # override format detection
gitstore unarchive --format tar < archive.tar # stdin (requires --format)
gitstore unarchive archive.zip -m "Import data" -b dev

# zip/unzip/tar/untar still work as aliases
gitstore zip archive.zip
gitstore unzip archive.zip
gitstore tar archive.tar.gz
gitstore untar archive.tar.gz

# Backup to a remote (exact mirror — all branches and tags)
gitstore backup https://github.com/user/repo.git
gitstore backup git@github.com:user/repo.git
gitstore backup /path/to/other-bare-repo.git

# Preview what backup would do
gitstore backup -n https://github.com/user/repo.git

# Restore from a remote (overwrite local to match remote)
gitstore restore https://github.com/user/repo.git

# Preview what restore would do
gitstore restore -n https://github.com/user/repo.git
```

### Backup and restore

`backup` and `restore` replicate an entire gitstore repository to and from a remote URL. They are whole-repo mirror operations: every branch and tag is included, and the destination becomes an exact copy of the source.

- **`gitstore backup URL`** pushes all local refs (branches and tags) to the remote. Remote refs that don't exist locally are deleted. Diverged histories are force-overwritten. After backup, the remote is an exact mirror of the local repo.

- **`gitstore restore URL`** fetches all objects from the remote, then overwrites local refs to match. Local refs that don't exist on the remote are deleted. After restore, the local repo is an exact mirror of the remote.

- **`-n` / `--dry-run`** connects to the remote and compares refs, showing what would be created, updated, or deleted, without transferring any data.

The URL can be any git remote: HTTPS (`https://github.com/...`), SSH (`git@github.com:...`), or a local path (`/path/to/bare-repo.git`).

**Authentication.** For HTTPS URLs, gitstore automatically obtains credentials by running `git credential fill`, which delegates to whatever credential helper is configured on your system (macOS Keychain, Windows Credential Manager, GNOME Keyring, `gh auth setup-git`, etc.). If that fails and the host is GitHub, it falls back to `gh auth token`. SSH URLs use your SSH agent as usual. No additional configuration is needed if `git push` already works for you.

**Typical workflow.** gitstore repos are local bare repositories with no configured remotes. Use `backup` after making changes to push a safety copy, and `restore` to recreate a repo from that copy:

```bash
# Initial setup: create a repo and add data
gitstore init -r /path/to/repo.git
gitstore cp -r /path/to/repo.git data.csv :data.csv
gitstore tag -r /path/to/repo.git create v1 main

# Push everything to GitHub
gitstore backup -r /path/to/repo.git https://github.com/user/repo.git

# Later, on another machine: recreate from backup
gitstore init -r /path/to/repo.git
gitstore restore -r /path/to/repo.git https://github.com/user/repo.git

# Verify
gitstore ls -r /path/to/repo.git        # data.csv
gitstore tag -r /path/to/repo.git list   # v1
```

```bash
# Browse at a specific commit
gitstore log --path file.txt                # find the commit hash
gitstore cat file.txt --hash abc1234...   # read file at that commit
gitstore ls --hash abc1234...             # list files at that commit

# Works with tags too
gitstore cat file.txt --hash v1.0

# Export a snapshot at a specific commit
gitstore zip archive.zip --hash abc1234...
gitstore tar archive.tar --hash abc1234...

# Copy from a specific commit
gitstore cp :file.txt local.txt --hash abc1234...
```

Write commands (`cp`, `cptree`, `rm`, `unarchive`, `unzip`, `untar`) accept `-m` for custom commit messages. Use `-b` on any command to target a branch other than `main`. Read commands (`cat`, `ls`, `cp`, `cptree`, `archive`, `zip`, `tar`, `log`) accept `--hash` to read from any branch, tag, or full commit hash. `log`, `archive`, `zip`, and `tar` accept `--before` with an ISO 8601 date or datetime to filter to commits on or before that point in time. `cp` accepts `--mode 644` or `--mode 755` to set file permissions; `cptree` auto-detects executable permissions from disk. `cptree` preserves symlinks by default when copying disk→repo; pass `--follow-symlinks` to dereference them instead. When copying repo→disk, `cp` and `cptree` recreate symlink entries as symlinks on disk. Pass `-v` before the command for status messages on stderr. `archive`, `zip`, and `tar` accept `-` as FILENAME to write to stdout; `unarchive` and `untar` read from stdin when no filename is given (or with `-`). `archive` and `unarchive` auto-detect the format from the filename extension; use `--format zip` or `--format tar` to override or when piping to/from stdout/stdin. The `zip`/`unzip`/`tar`/`untar` commands remain as aliases. `backup` and `restore` operate on the entire repository (all branches and tags) and accept `-n`/`--dry-run` to preview changes without transferring data.

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Run tests
uv run python -m pytest -v
```

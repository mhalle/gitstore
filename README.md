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
fs = fs.write_text("hello.txt", "Hello, world!")

# Read it back
print(fs.read_text("hello.txt"))  # 'Hello, world!'

# Every write is a commit
print(fs.commit_hash)           # full 40-char SHA
print(fs.message)               # '+ hello.txt'
```

## Core concepts

**Bare repository.** gitstore uses a *bare* Git repository -- one that contains only Git's internal object database, with no working directory or checked-out files. You won't see your stored files by browsing the repo directory; all data lives inside Git's content-addressable object store and is accessed exclusively through the gitstore API. This is by design: it avoids filesystem conflicts, keeps the storage compact, and lets Git handle deduplication and integrity.

**`GitStore`** opens or creates a bare repository. It exposes `branches` and `tags` as [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping) objects (supporting `.get`, `.keys`, `.values`, `.items`, etc.).

**`FS`** is an immutable snapshot of a committed tree. Reading methods (`read`, `ls`, `walk`, `exists`, `open`) never mutate state. Writing methods (`write`, `write_from_file`, `remove`, `batch`) return a *new* `FS` pointing at the new commit -- the original `FS` is unchanged.

Snapshots obtained from **branches** are writable (`fs.writable == True`). Snapshots obtained from **tags** are read-only (`fs.writable == False`).

## API

### Opening a repository

```python
repo = GitStore.open("data.git")                         # create or open (default branch: "main")
repo = GitStore.open("data.git", create=False)            # open only
repo = GitStore.open("data.git", branch="dev")            # custom default branch
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

repo.branches.current_name           # "main"
fs = repo.branches.current           # FS for the current branch
repo.branches.current = "dev"        # set current branch

for name in repo.branches:
    print(name)
"main" in repo.branches           # True
```

### Reading

```python
data = fs.read("path/to/file.bin")           # bytes
text = fs.read_text("config.json")           # str (UTF-8)
chunk = fs.read("big.bin", offset=100, size=50)  # partial read (50 bytes at offset 100)
chunk = fs.read_by_hash(sha, offset=0, size=1024)  # read blob by SHA, bypasses tree walk

entries = fs.ls()                             # root listing — list of name strings
entries = fs.ls("src")                        # subdirectory listing
details = fs.listdir("src")                  # list of WalkEntry (name, oid, mode)
exists = fs.exists("path/to/file.bin")        # bool
info = fs.stat("path/to/file.bin")           # StatResult (mode, file_type, size, hash, nlink, mtime)
ftype = fs.file_type("run.sh")               # FileType.EXECUTABLE
nbytes = fs.size("path/to/file.bin")         # int (bytes)
sha = fs.object_hash("path/to/file.bin")     # 40-char hex SHA
tree_sha = fs.tree_hash                      # root tree 40-char hex SHA

# Walk the tree (like os.walk)
for dirpath, dirnames, file_entries in fs.walk():
    for entry in file_entries:
        print(entry.name, entry.file_type)    # WalkEntry with name, oid, mode

# Glob
matches = fs.glob("**/*.py")                 # sorted list of matching paths

# File-like object
with fs.open("data.bin", "rb") as f:
    header = f.read(4)
```

### Writing

Every write auto-commits and returns a new snapshot:

```python
from gitstore import FileType

fs = fs.write_text("config.json", '{"key": "value"}')
fs = fs.write_text("script.sh", "#!/bin/sh\n", mode=FileType.EXECUTABLE)
fs = fs.write_text("config.json", "{}", message="Reset")   # custom commit message
fs = fs.write("image.png", raw_bytes)                       # binary data
fs = fs.write_from_file("big.bin", "/data/big.bin")         # from disk
fs = fs.write_symlink("link", "target")                     # symlink
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

# Reflog — branch movement history
for entry in repo.branches.reflog("main"):
    print(entry.old_sha, entry.new_sha, entry.message)
```

### Copy and sync

```python
# Disk to repo (current branch)
fs = fs.copy_in(["./data/"], "backup")
print(fs.changes.add)                            # [FileEntry(...), ...]

# Repo to disk
fs.copy_out(["docs"], "./local-docs")

# Work with a non-default branch
dev = repo.branches["dev"]
dev = dev.copy_in(["./features/"], "src")

# Copy between branches (atomic, no disk I/O)
main = repo.branches["main"]
dev = dev.copy_from_ref(main, "config", "config")  # copy config/ from main into dev

# Sync (make identical, including deletes)
fs = fs.sync_in("./local", "data")
fs.sync_out("data", "./local")

# Expand globs on disk (same dotfile rules as fs.glob)
from gitstore import disk_glob
files = disk_glob("./data/**/*.csv")

# Remove and move within repo
fs = fs.remove(["old-dir"], recursive=True)
fs = fs.move(["old.txt"], "new.txt")
```

### Atomic apply

Apply multiple writes and removes in a single commit without a context manager:

```python
from gitstore import WriteEntry

fs = fs.apply(
    writes={
        "config.json": b'{"v": 2}',
        "script.sh": WriteEntry(data=b"#!/bin/sh\n", mode=0o100755),
        "link": WriteEntry(target="config.json"),          # symlink
    },
    removes=["old.txt", "deprecated/"],
    message="Update config and clean up",
)
```

### Snapshot properties

```python
fs.commit_hash           # str -- full 40-character commit SHA
fs.ref_name              # str | None -- ref name (branch or tag), or None for detached
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

For full details on path parsing, ancestor syntax (`~N`), and interaction with flags, see [Path Syntax](https://github.com/mhalle/gitstore/blob/master/docs/paths.md).

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
gitstore archive_out out.zip
gitstore archive_in data.tar.gz

# Mirror (backup/restore all refs)
gitstore backup https://github.com/user/repo.git
gitstore restore https://github.com/user/repo.git
gitstore backup -n https://github.com/user/repo.git  # dry run

# Serve files over HTTP
gitstore serve                                        # single branch
gitstore serve --all --cors                           # all refs with CORS

# Serve repo over Git protocol (read-only)
gitstore gitserve
```

For full CLI documentation, see [CLI Reference](https://github.com/mhalle/gitstore/blob/master/docs/cli.md).

## Git notes

Attach metadata to commits without modifying history:

```python
# Default namespace (refs/notes/commits)
ns = repo.notes.commits
ns[fs.commit_hash] = "reviewed by Alice"
print(ns[fs.commit_hash])                       # "reviewed by Alice"
del ns[fs.commit_hash]

# Custom namespaces
reviews = repo.notes["reviews"]
reviews[fs.commit_hash] = "LGTM"

# Shortcut: note for the current HEAD commit
ns.for_current_branch = "deployed to staging"
print(ns.for_current_branch)

# Batch writes (single commit)
with repo.notes.commits.batch() as b:
    b[hash1] = "note one"
    b[hash2] = "note two"

# Iteration
for commit_hash, text in ns.items():
    print(commit_hash, text)
```

## Documentation

- [Documentation hub](https://github.com/mhalle/gitstore/blob/master/docs/index.md) -- quick start and navigation
- [Python API Reference](https://github.com/mhalle/gitstore/blob/master/docs/api.md) -- classes, methods, and data types
- [CLI Reference](https://github.com/mhalle/gitstore/blob/master/docs/cli.md) -- the `gitstore` command-line tool
- [Path Syntax](https://github.com/mhalle/gitstore/blob/master/docs/paths.md) -- how `ref:path` works across commands
- [GitHub Repository](https://github.com/mhalle/gitstore) -- source code, issues, and releases

## Development

```bash
uv sync --dev       # install with dev dependencies (includes CLI)
uv run python -m pytest -v
```

# Python API Reference

All public classes and functions are importable from the top-level `gitstore` package:

```python
from gitstore import GitStore, FS, StaleSnapshotError
from gitstore import copy_to_repo, copy_from_repo, sync_to_repo, sync_from_repo
from gitstore import CopyReport, CopyAction, CopyError, SyncDiff, RefChange
```

---

## GitStore

The entry point. Opens or creates a bare Git repository.

### `GitStore.open(path, *, create=True, branch="main", author="gitstore", email="gitstore@localhost")`

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str \| Path` | Path to the bare repository. |
| `create` | `bool` | If `True` (default), create the repo when it doesn't exist. If `False`, raise `FileNotFoundError` when missing. |
| `branch` | `str \| None` | Initial branch name when creating (default `"main"`). `None` to create a bare repo with no branches. |
| `author` | `str` | Default author name for commits. |
| `email` | `str` | Default author email for commits. |

**Returns:** `GitStore`

**Raises:** `FileNotFoundError` (missing repo when `create=False`).

Idempotent: if the repo already exists, it is opened regardless of `create` and `branch`.

```python
repo = GitStore.open("data.git")                                # create or open (default)
repo = GitStore.open("data.git", branch="dev")                  # create with "dev" branch
repo = GitStore.open("data.git", branch=None)                   # bare (no branches)
repo = GitStore.open("data.git", create=False)                  # open existing only
repo = GitStore.open("data.git", author="alice", email="a@b")   # custom author
```

### `repo.branches`

A `MutableMapping[str, FS]` of branches. Supports `[]`, `del`, `in`, `len`, iteration, `.get`, `.keys`, `.values`, `.items`.

```python
fs = repo.branches["main"]
repo.branches["dev"] = fs       # fork
del repo.branches["dev"]        # delete
"main" in repo.branches         # True
```

#### `repo.branches.set(name, fs) -> FS`

Set a branch to an FS snapshot and return a writable FS bound to it. This combines setting and getting in one operation.

**Returns:** New writable `FS` bound to the branch (not the input `fs`).

```python
# Instead of:
repo.branches['feature'] = fs
fs_feature = repo.branches['feature']

# Use:
fs_feature = repo.branches.set('feature', fs)
```

**Important:** Avoids the chained assignment footgun:
```python
# ❌ WRONG - fs2 is still bound to old branch!
fs2 = repo.branches['wow'] = fs1

# ✓ CORRECT - fs2 is bound to 'wow'
fs2 = repo.branches.set('wow', fs1)
```

#### `repo.branches.reflog(name) -> list[dict]`

Read the reflog (reference log) for a branch. The reflog records every time a branch pointer moves, including commits, undos, and branch updates.

**Returns:** List of reflog entries (chronologically ordered), each a dict with:
- `old_sha` (str) - Previous commit hash
- `new_sha` (str) - New commit hash
- `committer` (str) - Name and email
- `timestamp` (int) - Unix timestamp
- `message` (str) - Reflog message

**Raises:** `KeyError` (branch doesn't exist), `FileNotFoundError` (no reflog), `ValueError` (called on tags).

```python
entries = repo.branches.reflog("main")
for entry in entries[-5:]:  # Last 5 movements
    print(f"{entry['new_sha'][:7]}: {entry['message']}")
```

### `repo.tags`

A `MutableMapping[str, FS]` of tags. Tags are immutable -- overwriting an existing tag raises `KeyError`. Tag snapshots are read-only (`branch=None`).

```python
repo.tags["v1.0"] = fs
snapshot = repo.tags["v1.0"]    # read-only FS
```

### `repo.backup(url, *, dry_run=False)`

Push all refs (branches and tags) to `url`, creating an exact mirror. Remote-only refs are deleted.

**Returns:** `SyncDiff`

### `repo.restore(url, *, dry_run=False)`

Fetch all refs from `url`, overwriting local state. Local-only refs are deleted.

**Returns:** `SyncDiff`

---

## FS

An immutable snapshot of a committed tree. Read operations never mutate state. Write operations return a *new* `FS` -- the original is unchanged.

Snapshots from **branches** are writable. Snapshots from **tags** are read-only.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `hash` | `str` | Full 40-character commit SHA. |
| `branch` | `str \| None` | Branch name, or `None` for tag snapshots. |
| `message` | `str` | Commit message. |
| `time` | `datetime` | Timezone-aware commit timestamp. |
| `author_name` | `str` | Commit author name. |
| `author_email` | `str` | Commit author email. |

### Read methods

#### `fs.read(path) -> bytes`

Read a file. Raises `FileNotFoundError` if missing, `IsADirectoryError` if path is a directory.

#### `fs.ls(path=None) -> list[str]`

List entries at `path` (or root). Raises `NotADirectoryError` if path is a file.

#### `fs.walk(path=None) -> Iterator[tuple[str, list[str], list[str]]]`

Walk the tree like `os.walk`. Yields `(dirpath, dirnames, filenames)`. Pass `path` to walk a subtree.

#### `fs.exists(path) -> bool`

Return `True` if `path` exists (file or directory).

#### `fs.is_dir(path) -> bool`

Return `True` if `path` is a directory. Returns `False` if missing.

#### `fs.glob(pattern) -> list[str]`

Expand a glob pattern (`*`, `?` -- no `**`). Wildcards do not match a leading `.` unless the pattern segment starts with `.`. Returns a sorted list of matching paths.

#### `fs.readlink(path) -> str`

Read the target of a symlink. Raises `FileNotFoundError` if missing, `ValueError` if not a symlink.

#### `fs.open(path, mode="rb")`

Open a file-like object. Mode `"rb"` returns a readable, seekable file. Mode `"wb"` returns a writable file that commits on close (or context manager exit).

```python
with fs.open("data.bin", "rb") as f:
    header = f.read(4)

with fs.open("out.bin", "wb") as f:
    f.write(b"data")
new_fs = f.fs
```

### Write methods

All write methods require a writable snapshot (from a branch). They return a new `FS`; the original is unchanged.

#### `fs.write(path, data, *, message=None, mode=None) -> FS`

Write `data` (bytes) to `path`. Directories are created automatically. Set `mode=0o100755` for executable files.

#### `fs.write_from(path, local_path, *, message=None, mode=None) -> FS`

Write from a file on disk. Avoids loading the entire file into Python memory. Executable permissions are auto-detected from disk unless `mode` is set.

#### `fs.write_symlink(path, target, *, message=None) -> FS`

Create a symbolic link at `path` pointing to `target`.

#### `fs.remove(path, *, message=None) -> FS`

Remove a file. Raises `FileNotFoundError` if missing, `IsADirectoryError` if path is a directory.

### Commit Messages

Write operations automatically generate descriptive commit messages. You can override by passing a custom `message` to any write method.

**Auto-generated format:**

Single operations:
```
+ filename.txt              # add regular file
+ script.sh (E)             # add executable
+ config.json (L)           # add symlink
~ filename.txt              # update file
~ script.sh (E)             # update executable
- filename.txt              # remove file
```

Batch operations:
```
Batch: +3                   # manual batch: 3 additions
Batch: ~2                   # manual batch: 2 updates
Batch: -5                   # manual batch: 5 deletions
Batch: +1 ~1 -1             # manual batch: mixed operations
Batch cp: +3                # copy operation: 3 additions
Batch cp: +1 ~2 -1          # copy operation: mixed
Batch ar: +10               # archive extraction: 10 additions
```

**Symbols:**
- **`+`** = additions
- **`~`** = updates/modifications
- **`-`** = deletions

**Operation prefixes (batch only):**
- **`Batch:`** = manual `fs.batch()` call
- **`Batch cp:`** = copy/sync operation (`copy_to_repo`, `copy_from_repo`, `sync_to_repo`, `sync_from_repo`)
- **`Batch ar:`** = archive extraction (`unzip`, `untar`, `unarchive`)

**Type annotations:**
- **`(E)`** = executable file (mode 0o100755)
- **`(L)`** = symbolic link
- Regular files have no annotation

**Custom messages:**
```python
fs = fs.write("config.json", b"{}", message="Reset configuration")
fs = fs.write("deploy.sh", script, message="feat: update deployment script")

with fs.batch(message="Import dataset v2") as b:
    b.write("data.csv", csv_data)
    b.write("meta.json", metadata)
```

**Message placeholders:**

Custom messages can include placeholders that expand at commit time:

| Placeholder | Expands to | Example |
|-------------|------------|---------|
| `{default}` | Full auto-generated message | `Batch cp: +3 ~1` |
| `{add_count}` | Number of added files | `3` |
| `{update_count}` | Number of updated files | `1` |
| `{delete_count}` | Number of deleted files | `0` |
| `{total_count}` | Total changed files | `4` |
| `{op}` | Operation name (`cp`, `ar`, or empty) | `cp` |

```python
from gitstore import copy_to_repo

new_fs = copy_to_repo(fs, ["src/"], "deploy",
                       message="Deploy v2: {default}")
# Commit message: "Deploy v2: Batch cp: +3 ~1"
```

A message without `{` is returned as-is (backward compatible). Unknown placeholders raise `KeyError`.

### Batch

#### `fs.batch(message=None) -> Batch`

Context manager for multiple writes/removes in a single commit. See [Batch](#batch) below.

### History

#### `fs.parent -> FS | None`

The parent snapshot, or `None` for the initial commit.

#### `fs.log(path=None, *, match=None, before=None) -> Iterator[FS]`

Walk the commit log. All filters are optional and combine with AND:

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str \| PathLike \| None` | Only commits that changed this file. |
| `match` | `str \| None` | Commit message pattern (`*` and `?` wildcards). |
| `before` | `datetime \| None` | Only commits on or before this time. |

```python
for snapshot in fs.log(path="config.json", match="fix*"):
    print(snapshot.hash, snapshot.message)
```

#### `fs.undo(steps=1) -> FS`

Move the branch back N commits. Walks back through parent commits and updates the branch pointer. Automatically writes a reflog entry.

**Returns:** New `FS` snapshot at the previous state.

**Raises:** `PermissionError` (called on read-only tag), `ValueError` (not enough history).

```python
fs = repo.branches["main"]
fs = fs.undo()      # Back 1 commit
fs = fs.undo(3)     # Back 3 commits
```

#### `fs.redo(steps=1) -> FS`

Move the branch forward N steps using the reflog. Reads the reflog to find where the branch was before the last N movements. Can resurrect "orphaned" commits after undo.

Each redo step moves back one entry in the reflog (backwards through the log, forward in commit history).

**Returns:** New `FS` snapshot at the forward position.

**Raises:** `PermissionError` (called on read-only tag), `ValueError` (not enough redo history or no reflog).

```python
fs = fs.undo(2)     # Go back 2 commits
fs = fs.redo()      # Redo 1 step (forward in reflog)
fs = fs.redo(2)     # Redo 2 steps
```

**Note:** Undo creates one reflog entry that records the branch movement. To redo an `undo(N)`, you typically need `redo(1)`, not `redo(N)`.

### Export

#### `fs.dump(path) -> None`

Write the entire tree to a directory on disk. Creates directories as needed. Symlinks are recreated as symlinks.

---

## Working with Old Snapshots

When you write to an FS, you get back a new snapshot while the old reference remains valid. Old snapshots are **read-only bookmarks** into history.

### Old Snapshots Are Readable

```python
fs1 = fs.write("a.txt", b"version 1")
fs2 = fs1.write("b.txt", b"version 2")
fs3 = fs2.write("c.txt", b"version 3")

# fs1 and fs2 remain readable
print(fs1.read("a.txt"))           # Works!
print(fs1.ls())                     # ["a.txt"]
print(fs2.exists("b.txt"))          # True
print(fs2.exists("c.txt"))          # False
```

Use cases:
- **Compare versions** - Read old and new states side-by-side
- **Audit changes** - See what files existed at different points
- **Extract data** - Get specific files from history without full checkout

### Old Snapshots Cannot Write

Old snapshots raise `StaleSnapshotError` if you try to write from them, because the branch has moved forward:

```python
fs1 = fs.write("a.txt", b"a")
fs2 = fs1.write("b.txt", b"b")

# fs1 is now stale - the branch moved to fs2
fs1.write("c.txt", b"c")  # StaleSnapshotError!
```

This prevents confusion about which branch state you're modifying. To continue writing, use the latest snapshot.

### Resetting Branches

You can reset a branch to an old snapshot (like `git reset --hard`):

```python
fs1 = fs.write("a.txt", b"a")
fs2 = fs1.write("b.txt", b"b")
fs3 = fs2.write("c.txt", b"c")

# Reset main back to fs1
repo.branches["main"] = fs1

# Branch now points to fs1's commit
current = repo.branches["main"]
print(current.ls())  # ["a.txt"]
```

This updates the branch pointer but doesn't delete commits - they remain in the reflog and can be recovered with `redo()`.

### Creating Branches from Old Snapshots

You can create a new branch from any old snapshot (like `git checkout -b feature <commit>`):

```python
fs1 = fs.write("a.txt", b"a")
fs2 = fs1.write("b.txt", b"b")
fs3 = fs2.write("c.txt", b"c")

# Create new branch from fs1 and get writable FS
exp = repo.branches.set("experiment", fs1)
exp = exp.write("x.txt", b"x")  # Works!
```

**Alternative (two statements):**
```python
repo.branches["experiment"] = fs1  # Set branch
exp = repo.branches["experiment"]   # Get writable FS
```

**⚠️ Warning - Chained assignment doesn't work:**
```python
# ❌ WRONG - exp is still bound to old branch!
exp = repo.branches["experiment"] = fs1
exp.branch  # NOT "experiment"!

# ✓ CORRECT - use .set() instead
exp = repo.branches.set("experiment", fs1)
exp.branch  # "experiment" ✓
```

**Pattern:**
1. Keep old snapshot as read-only bookmark
2. Use `.set()` to create branch and get writable FS in one step
3. Or use bracket notation in two separate statements

---

## Batch

Accumulates writes and removes, then commits once when the context manager exits. If an exception occurs inside the block, nothing is committed.

```python
with fs.batch(message="Import v2") as b:
    b.write("a.txt", b"alpha")
    b.write_from("big.bin", "/data/big.bin")
    b.write_symlink("link.txt", "a.txt")
    b.remove("old.txt")
    with b.open("c.txt", "wb") as f:
        f.write(b"charlie")

new_fs = b.fs  # new snapshot, or None if exception occurred
```

### Methods

#### `b.write(path, data, *, mode=None)`

Stage a file write. Set `mode` to `GIT_FILEMODE_BLOB_EXECUTABLE` (or `0o100755`) for executables.

#### `b.write_from(path, local_path, *, mode=None)`

Stage a write from a file on disk.

#### `b.write_symlink(path, target)`

Stage a symbolic link.

#### `b.remove(path)`

Stage a file removal. Raises `FileNotFoundError` if the file doesn't exist (in the base tree or pending writes), `IsADirectoryError` if path is a directory.

#### `b.open(path, mode="wb")`

Open a writable file-like object that stages its content on close.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `b.fs` | `FS \| None` | The new snapshot after commit, or `None` if uncommitted/aborted. |

---

## Copy and sync functions

These functions copy files between local disk and a gitstore repo. They support files, directories, trailing-slash "contents" mode, and glob patterns.

All path arguments use forward slashes. Glob patterns (`*`, `?`) do not match a leading `.` (Unix convention).

### Disk to repo

#### `copy_to_repo(fs, sources, dest, *, follow_symlinks=False, message=None, mode=None, ignore_existing=False, delete=False, ignore_errors=False) -> FS`

Copy local files/directories/globs into the repo.

| Parameter | Type | Description |
|-----------|------|-------------|
| `fs` | `FS` | Writable snapshot to copy into. |
| `sources` | `list[str]` | Local source paths. Trailing `/` means "contents of". |
| `dest` | `str` | Repo destination path (empty string for root). |
| `follow_symlinks` | `bool` | Dereference symlinks instead of preserving them. |
| `message` | `str \| None` | Custom commit message (supports [placeholders](#message-placeholders)). |
| `mode` | `int \| None` | Override file mode for all files. |
| `ignore_existing` | `bool` | Skip files that already exist in the repo. |
| `delete` | `bool` | Remove repo files not in source (rsync `--delete`). |
| `ignore_errors` | `bool` | Collect per-file errors instead of aborting. |

**Returns:** New `FS` snapshot. The operation report is available via `fs.report` (a `CopyReport` or `None` when nothing was done).

#### `copy_to_repo_dry_run(fs, sources, dest, *, follow_symlinks=False, ignore_existing=False, delete=False) -> CopyReport | None`

Preview what `copy_to_repo` would do without writing.

#### `sync_to_repo(fs, local_path, repo_path, *, message=None, ignore_errors=False) -> FS`

Make `repo_path` identical to `local_path` (includes deletes). Returns new `FS` snapshot with report available via `fs.report`.

#### `sync_to_repo_dry_run(fs, local_path, repo_path) -> CopyReport | None`

Preview what `sync_to_repo` would do.

### Repo to disk

#### `copy_from_repo(fs, sources, dest, *, ignore_existing=False, delete=False, ignore_errors=False) -> CopyReport | None`

Copy repo files/directories/globs to local disk.

| Parameter | Type | Description |
|-----------|------|-------------|
| `fs` | `FS` | Snapshot to copy from. |
| `sources` | `list[str]` | Repo source paths. |
| `dest` | `str` | Local destination directory. |
| `ignore_existing` | `bool` | Skip files that already exist locally. |
| `delete` | `bool` | Remove local files not in source. |
| `ignore_errors` | `bool` | Collect per-file errors instead of aborting. |

**Returns:** `CopyReport` with details of what was copied, or `None` when nothing was done.

#### `copy_from_repo_dry_run(fs, sources, dest, *, ignore_existing=False, delete=False) -> CopyReport | None`

Preview what `copy_from_repo` would do.

#### `sync_from_repo(fs, repo_path, local_path, *, ignore_errors=False) -> CopyReport | None`

Make `local_path` identical to `repo_path` (includes deletes).

#### `sync_from_repo_dry_run(fs, repo_path, local_path) -> CopyReport | None`

Preview what `sync_from_repo` would do.

---

## Data classes

### CopyReport

Result of a copy/sync operation (dry-run or real). All copy and sync functions return `CopyReport | None` — `None` when there is nothing to report (no actions, no errors, no warnings).

| Field | Type | Description |
|-------|------|-------------|
| `add` | `list[str]` | Paths added (or to add, for dry-run). |
| `update` | `list[str]` | Paths updated (or to update). |
| `delete` | `list[str]` | Paths deleted (or to delete). |
| `errors` | `list[CopyError]` | Per-file errors (only when `ignore_errors=True`). |
| `warnings` | `list[CopyError]` | Non-fatal warnings (e.g. overlapping sources). |

| Property | Type | Description |
|----------|------|-------------|
| `in_sync` | `bool` | `True` if no add/update/delete actions. |
| `total` | `int` | Total number of add/update/delete actions. |

| Method | Returns | Description |
|--------|---------|-------------|
| `actions()` | `list[CopyAction]` | All actions sorted by path. |

`CopyPlan` and `SyncPlan` are backward-compatible aliases for `CopyReport`.

### CopyAction

A single action within a `CopyReport`.

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Relative path. |
| `action` | `str` | `"add"`, `"update"`, or `"delete"`. |

`SyncAction` is a backward-compatible alias for `CopyAction`.

### CopyError

A file that failed during a copy operation.

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Path of the failed file. |
| `error` | `str` | Error message. |

### SyncDiff

Describes what a backup or restore operation changed (or would change).

| Field | Type | Description |
|-------|------|-------------|
| `create` | `list[RefChange]` | Refs to create. |
| `update` | `list[RefChange]` | Refs to update. |
| `delete` | `list[RefChange]` | Refs to delete. |

| Property | Type | Description |
|----------|------|-------------|
| `in_sync` | `bool` | `True` if no changes. |
| `total` | `int` | Total number of ref changes. |

### RefChange

A single ref change within a `SyncDiff`.

| Field | Type | Description |
|-------|------|-------------|
| `ref` | `str` | Ref name (e.g. `refs/heads/main`). |
| `src_sha` | `str \| None` | Source SHA (`None` for deletes). |
| `dest_sha` | `str \| None` | Destination SHA (`None` for creates). |

---

## Exceptions

### StaleSnapshotError

Raised when writing from a snapshot whose branch has advanced since the snapshot was obtained.

```python
from gitstore import StaleSnapshotError

fs = repo.branches["main"]
_ = fs.write("a.txt", b"a")     # advances the branch

try:
    fs.write("b.txt", b"b")     # stale -- branch moved past it
except StaleSnapshotError:
    fs = repo.branches["main"]  # re-fetch and retry
```

See the [README](../README.md#error-handling) for the full error table.

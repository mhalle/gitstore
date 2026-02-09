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

### `GitStore.open(path, create=None, *, branch=None, author="gitstore", email="gitstore@localhost")`

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str \| Path` | Path to the bare repository. |
| `create` | `str \| bool \| None` | `None` -- open existing (fail if missing). `True` -- create empty bare repo. `str` -- create bare repo and bootstrap a branch with that name. |
| `branch` | `str \| None` | Initial branch name. Shorthand: `create=True, branch="main"` is equivalent to `create="main"`. |
| `author` | `str` | Default author name for commits. |
| `email` | `str` | Default author email for commits. |

**Returns:** `GitStore`

**Raises:** `FileNotFoundError` (missing repo when `create=None`), `FileExistsError` (path exists when creating), `ValueError` (`create=False` or conflicting `create`+`branch`).

```python
repo = GitStore.open("data.git", create="main")
repo = GitStore.open("data.git", create=True, branch="main")  # equivalent
repo = GitStore.open("data.git")                                # open existing
```

### `repo.branches`

A `MutableMapping[str, FS]` of branches. Supports `[]`, `del`, `in`, `len`, iteration, `.get`, `.keys`, `.values`, `.items`.

```python
fs = repo.branches["main"]
repo.branches["dev"] = fs       # fork
del repo.branches["dev"]        # delete
"main" in repo.branches         # True
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

### Export

#### `fs.dump(path) -> None`

Write the entire tree to a directory on disk. Creates directories as needed. Symlinks are recreated as symlinks.

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
| `message` | `str \| None` | Custom commit message. |
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

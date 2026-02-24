# API Reference

```python
from gitstore import GitStore, FS, WriteEntry, StaleSnapshotError, retry_write
from gitstore import ChangeReport, ChangeAction, ChangeError, FileEntry, FileType
from gitstore import MirrorDiff, RefChange, ReflogEntry, WalkEntry
```

---

## GitStore.open

Open or create a bare Git repository.

### Synopsis

```python
repo = GitStore.open(path, *, create=True, branch="main",
                     author="gitstore", email="gitstore@localhost")
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path` | | Path to bare repository. |
| `create` | `bool` | `True` | Create the repo if missing. `False` raises `FileNotFoundError`. |
| `branch` | `str \| None` | `"main"` | Initial branch on creation. `None` = branchless bare repo. |
| `author` | `str` | `"gitstore"` | Default author name. |
| `email` | `str` | `"gitstore@localhost"` | Default author email. |

**Returns:** `GitStore`

Idempotent: if the repo already exists, `create` and `branch` are ignored.

### Examples

```python
repo = GitStore.open("data.git")                  # create or open
repo = GitStore.open("data.git", create=False)     # open only
repo = GitStore.open("data.git", branch="dev")     # create with "dev"
repo = GitStore.open("data.git", branch=None)      # branchless
```

---

## repo.branches

`MutableMapping[str, FS]` of branches. Supports `[]`, `del`, `in`, `len`, iteration.

```python
fs = repo.branches["main"]
repo.branches["dev"] = fs          # fork
del repo.branches["dev"]           # delete
```

### branches.set(name, fs) -> FS

Set branch and return a writable FS bound to it. Avoids the chained-assignment footgun.

```python
fs_dev = repo.branches.set("dev", fs)   # correct
# fs_dev = repo.branches["dev"] = fs    # WRONG: fs_dev not bound to "dev"
```

### branches.default

Read/write property. Returns the default branch name (`str`), or `None` if HEAD is dangling.

Setting validates the branch exists; raises `KeyError` if not. Raises `ValueError` on `repo.tags`.

```python
repo.branches.default              # "main"
repo.branches.default = "dev"      # set default branch
```

### branches.reflog(name) -> list[ReflogEntry]

Reflog entries (chronological). Each `ReflogEntry` has fields: `old_sha`, `new_sha`, `committer`, `timestamp`, `message`.

Raises `KeyError` (missing branch), `FileNotFoundError` (no reflog).

---

## repo.tags

`MutableMapping[str, FS]` of tags. Overwriting an existing tag raises `KeyError`. Tag snapshots are read-only.

```python
repo.tags["v1.0"] = fs
snapshot = repo.tags["v1.0"]       # read-only FS
del repo.tags["v1.0"]
```

---

## FS -- Reading

An immutable committed snapshot. Read operations never mutate state.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `commit_hash` | `str` | 40-char commit SHA. |
| `branch` | `str \| None` | Branch name (`None` for tags). |
| `message` | `str` | Commit message. |
| `time` | `datetime` | Timezone-aware commit timestamp. |
| `author_name` | `str` | Author name. |
| `author_email` | `str` | Author email. |
| `changes` | `ChangeReport \| None` | Report from the last operation that produced this snapshot. |

### fs.read(path) -> bytes

Read file contents. Raises `FileNotFoundError`, `IsADirectoryError`.

### fs.read_text(path, encoding="utf-8") -> str

Read file contents as a string. Shorthand for `fs.read(path).decode(encoding)`.

### fs.ls(path=None) -> list[str]

List entries at *path* (or root). Raises `NotADirectoryError` if *path* is a file.

### fs.exists(path) -> bool

`True` if *path* exists (file or directory).

### fs.file_type(path) -> FileType

Return the `FileType` of *path*: `BLOB`, `EXECUTABLE`, `LINK`, or `TREE`. Raises `FileNotFoundError`.

### fs.size(path) -> int

Return the size in bytes of the object at *path*. Works without reading the full blob into memory. Raises `FileNotFoundError`.

### fs.object_hash(path) -> str

Return the 40-character hex SHA of the object at *path*. For files this is the blob SHA; for directories the tree SHA. Raises `FileNotFoundError`.

### fs.is_dir(path) -> bool

`True` if *path* is a directory. `False` if missing.

### fs.walk(path=None) -> Iterator[tuple[str, list[str], list[WalkEntry]]]

Walk the tree like `os.walk`. Yields `(dirpath, dirnames, file_entries)`.

Each file entry is a `WalkEntry` named tuple with fields `name`, `oid`, and `filemode`. Access `entry.file_type` to get a `FileType` enum value.

### fs.glob(pattern) -> list[str]

Expand a glob pattern (`*`, `?`, `**`). Wildcards do not match a leading `.`. Returns sorted list.

### fs.iglob(pattern) -> Iterator[str]

Like `glob` but returns an unordered iterator instead of a sorted list. Useful when you only need to iterate once.

### fs.open(path, mode="rb")

File-like access. `"rb"` = readable/seekable. `"wb"` = writable, commits on close.

```python
with fs.open("data.bin", "rb") as f:
    header = f.read(4)

with fs.open("out.bin", "wb") as f:
    f.write(b"data")
new_fs = f.fs
```

### fs.readlink(path) -> str

Read symlink target. Raises `FileNotFoundError`, `ValueError` (not a symlink).

---

## FS -- Writing

Write methods require a writable snapshot (from a branch). They return a **new** FS; the original is unchanged.

### fs.write(path, data, *, message=None, mode=None) -> FS

Write *data* (bytes). Set `mode=FileType.EXECUTABLE` or `mode=0o100755` for executables. Directories auto-created.

### fs.write_text(path, text, *, encoding="utf-8", message=None, mode=None) -> FS

Write *text* (str). Shorthand for `fs.write(path, text.encode(encoding), ...)`.

### fs.write_from_file(path, local_path, *, message=None, mode=None) -> FS

Write from a file on disk. Auto-detects executable permission unless *mode* is set.

### fs.write_symlink(path, target, *, message=None) -> FS

Create a symbolic link.

### fs.apply(writes=None, removes=None, *, message=None, operation=None) -> FS

Apply multiple writes and removes in a single atomic commit. Returns new FS with `.changes` set.

```python
fs.apply(
    writes={
        "data.txt": b"raw bytes",
        "hello.txt": "hello world",
        "large.bin": Path("/local/large-file"),
        "script.sh": WriteEntry(data=Path("/local/script.sh"), mode=FileType.EXECUTABLE),
        "link": WriteEntry(target="symlink-target"),
    },
    removes=["old.txt", "stale.log"],
    message="bulk update",
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `writes` | `dict[str, WriteEntry \| bytes \| str \| Path] \| None` | `None` | Map of repo paths to content. |
| `removes` | `str \| list[str] \| set[str] \| None` | `None` | Repo paths to delete. |
| `message` | `str \| None` | `None` | Commit message (supports [placeholders](#commit-messages)). |
| `operation` | `str \| None` | `None` | Operation name for auto-generated messages. |

**Write values** -- bare values are shorthand for `WriteEntry`:

| Value | Meaning |
|-------|---------|
| `b"..."` (bytes) | Raw blob data. |
| `"..."` (str) | UTF-8 text (encoded automatically). |
| `Path(...)` | Read from local file; mode auto-detected from disk. |
| `WriteEntry(data=..., mode=...)` | Explicit source with optional mode override. |
| `WriteEntry(target="...")` | Symbolic link to target. |

Identical writes (same content and mode as existing file) produce no commit.

### fs.remove(sources, *, recursive=False, dry_run=False, glob=True, message=None) -> FS

Remove files matching *sources* (string or list of strings) from the repo. With `recursive=True`, directories are removed recursively. With `dry_run=True`, no changes are written; the result FS has `.changes` set. Raises `FileNotFoundError` if no matches.

---

## Batch

Multiple writes/removes in one commit. Nothing is committed if an exception occurs.

### Synopsis

```python
with fs.batch(message="Import v2") as b:
    b.write("a.txt", b"alpha")
    b.write_from_file("big.bin", "/data/big.bin")
    b.write_symlink("link.txt", "a.txt")
    b.remove("old.txt")
    with b.open("c.txt", "wb") as f:
        f.write(b"charlie")
new_fs = b.fs
```

### Methods

| Method | Description |
|--------|-------------|
| `b.write(path, data, *, mode=None)` | Stage a file write. |
| `b.write_from_file(path, local_path, *, mode=None)` | Stage a write from disk. |
| `b.write_symlink(path, target)` | Stage a symlink. |
| `b.remove(path)` | Stage a removal. |
| `b.open(path, mode="wb")` | Writable file-like, stages on close. |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `b.fs` | `FS \| None` | New snapshot after commit, or `None` if uncommitted/aborted. |

---

## History

### fs.parent -> FS | None

Parent snapshot, or `None` for the initial commit.

### fs.back(n) -> FS

Return the FS at the *n*-th ancestor commit. Raises `ValueError` if history is too short.

### fs.log(path=None, *, match=None, before=None) -> Iterator[FS]

Walk the commit log. All filters are optional and combine with AND.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str \| None` | Only commits that changed this file. |
| `match` | `str \| None` | Message pattern (`*`, `?` wildcards). |
| `before` | `datetime \| None` | Commits on or before this time. |

### fs.undo(steps=1) -> FS

Move branch back *N* commits. Raises `PermissionError` (tag), `ValueError` (not enough history).

### fs.redo(steps=1) -> FS

Move branch forward *N* reflog steps. Raises `PermissionError` (tag), `ValueError` (not enough history).

Undo creates one reflog entry. To redo `undo(N)`, use `redo(1)`.

---

## Copy, Sync, and Move

Copy files between local disk and a gitstore repo, sync directories, and move/rename within the repo. Supports files, directories, trailing-slash contents mode, glob patterns, and `/./` pivot markers.

### fs.copy_in (disk -> repo)

```python
fs.copy_in(sources, dest, *, dry_run=False, glob=True,
           follow_symlinks=False, message=None, mode=None,
           ignore_existing=False, delete=False, ignore_errors=False,
           checksum=True, exclude=None) -> FS
```

Copy local files/dirs/globs into the repo. Returns new FS with `.changes` set.

| Parameter | Type | Description |
|-----------|------|-------------|
| `sources` | `str \| list[str]` | Local paths. Trailing `/` = contents. `/./` = pivot. |
| `dest` | `str` | Repo destination (empty string for root). |
| `dry_run` | `bool` | Preview only; no changes written. Result FS has `.changes` set. |
| `glob` | `bool` | Expand glob patterns in sources (default `True`). |
| `follow_symlinks` | `bool` | Dereference symlinks. |
| `message` | `str \| None` | Commit message (supports [placeholders](#commit-messages)). |
| `mode` | `int \| None` | Override file mode for all files. |
| `ignore_existing` | `bool` | Skip existing files. |
| `delete` | `bool` | Remove repo files not in source. |
| `ignore_errors` | `bool` | Collect errors instead of aborting. |
| `checksum` | `bool` | Compare files by content hash (default `True`). |
| `exclude` | `ExcludeFilter \| None` | Exclude filter (gitignore-style patterns). |

### fs.copy_out (repo -> disk)

```python
fs.copy_out(sources, dest, *, dry_run=False, glob=True,
            ignore_existing=False, delete=False, ignore_errors=False,
            checksum=True) -> FS
```

Copy repo files/dirs/globs to local disk. Returns FS with `.changes` set.

| Parameter | Type | Description |
|-----------|------|-------------|
| `sources` | `str \| list[str]` | Repo paths. Trailing `/` = contents. `/./` = pivot. |
| `dest` | `str` | Local destination directory. |
| `dry_run` | `bool` | Preview only; no changes written. Result FS has `.changes` set. |
| `glob` | `bool` | Expand glob patterns in sources (default `True`). |
| `ignore_existing` | `bool` | Skip existing files. |
| `delete` | `bool` | Remove local files not in source. |
| `ignore_errors` | `bool` | Collect errors instead of aborting. |
| `checksum` | `bool` | Compare files by content hash (default `True`). |

### fs.sync_in (disk -> repo)

```python
fs.sync_in(local_path, repo_path, *, dry_run=False, message=None,
           ignore_errors=False, checksum=True, exclude=None) -> FS
```

Make *repo_path* identical to *local_path* (includes deletes). Returns new FS with `.changes` set.

| Parameter | Type | Description |
|-----------|------|-------------|
| `local_path` | `str` | Local directory to sync from. |
| `repo_path` | `str` | Repo directory to sync to. |
| `dry_run` | `bool` | Preview only; no changes written. Result FS has `.changes` set. |
| `message` | `str \| None` | Commit message (supports [placeholders](#commit-messages)). |
| `ignore_errors` | `bool` | Collect errors instead of aborting. |
| `checksum` | `bool` | Compare files by content hash (default `True`). |
| `exclude` | `ExcludeFilter \| None` | Exclude filter (gitignore-style patterns). |

### fs.sync_out (repo -> disk)

```python
fs.sync_out(repo_path, local_path, *, dry_run=False,
            ignore_errors=False, checksum=True) -> FS
```

Make *local_path* identical to *repo_path* (includes deletes). Returns FS with `.changes` set.

| Parameter | Type | Description |
|-----------|------|-------------|
| `repo_path` | `str` | Repo directory to sync from. |
| `local_path` | `str` | Local directory to sync to. |
| `dry_run` | `bool` | Preview only; no changes written. Result FS has `.changes` set. |
| `ignore_errors` | `bool` | Collect errors instead of aborting. |
| `checksum` | `bool` | Compare files by content hash (default `True`). |

### fs.move (within repo)

```python
fs.move(sources, dest, *, recursive=False, dry_run=False, glob=True,
        message=None) -> FS
```

Move/rename files within the repo. All *sources* and *dest* are repo paths. Directories require `recursive=True`. The operation is atomic -- writes and deletes happen in a single commit. Returns new FS with `.changes` set.

| Parameter | Type | Description |
|-----------|------|-------------|
| `sources` | `str \| list[str]` | Repo paths to move. |
| `dest` | `str` | Repo destination path. |
| `recursive` | `bool` | Allow moving directories. |
| `dry_run` | `bool` | Preview only; no changes written. Result FS has `.changes` set. |
| `glob` | `bool` | Expand glob patterns in sources (default `True`). |
| `message` | `str \| None` | Commit message (supports [placeholders](#commit-messages)). |

### Source path modes

| Pattern | Meaning |
|---------|---------|
| `file.txt` | Single file. |
| `dir` | Directory (name preserved at dest). |
| `dir/` | Contents of directory (trailing `/`). |
| `*.py` | Glob expansion (`*`, `?`; no leading-`.` match). |
| `/base/./rest` | Pivot: `/base` locates files, `rest` preserved at dest. |

### /./  pivot marker

An embedded `/./` in a source path (rsync `-R` style) controls which part of the path is preserved at the destination. Everything before `/./` locates files on disk; everything after becomes the destination-relative path.

```python
# /home/user/./projects/app -> dest/projects/app/...
fs.copy_in(["/home/user/./projects/app"], "dest")

# /home/user/./projects/app/ -> dest/projects/...  (contents mode)
fs.copy_in(["/home/user/./projects/app/"], "dest")
```

A leading `./` (e.g. `./mydir`) is a normal relative path and does **not** trigger pivot mode.

---

## Backup and Restore

### repo.backup(url, *, dry_run=False) -> MirrorDiff

Push all refs to *url*, creating an exact mirror. Remote-only refs are deleted.

### repo.restore(url, *, dry_run=False) -> MirrorDiff

Fetch all refs from *url*, overwriting local state. Local-only refs are deleted.

---

## Commit Messages

Write operations auto-generate commit messages. Override with `message=` on any write method.

### Auto-generated format

```
+ filename.txt              # add
+ script.sh (executable)    # add executable
+ config.json (link)        # add symlink
~ filename.txt              # update
- filename.txt              # remove
Batch: +3 ~1                # manual batch
Batch cp: +3 ~1 -2          # copy
Batch sync: +3 ~1 -2        # sync
Batch ar: +10               # archive extraction
Batch mv: +2 -2             # move
Batch rm: -3                # remove
```

### Placeholders

Custom messages support placeholders that expand at commit time:

| Placeholder | Expands to |
|-------------|------------|
| `{default}` | Full auto-generated message. |
| `{add_count}` | Number of additions. |
| `{update_count}` | Number of updates. |
| `{delete_count}` | Number of deletions. |
| `{total_count}` | Total changed files. |
| `{op}` | Operation name (`cp`, `ar`, `mv`, `rm`, etc.). |

A message without `{` is used as-is. Unknown placeholders raise `KeyError`.

---

## Data Classes

### ChangeReport

Result of a copy/sync/move/remove operation.

| Field | Type | Description |
|-------|------|-------------|
| `add` | `list[FileEntry]` | Files added. |
| `update` | `list[FileEntry]` | Files updated. |
| `delete` | `list[FileEntry]` | Files deleted. |
| `errors` | `list[ChangeError]` | Per-file errors (with `ignore_errors`). |
| `warnings` | `list[ChangeError]` | Non-fatal warnings. |

| Property/Method | Returns | Description |
|-----------------|---------|-------------|
| `in_sync` | `bool` | No add/update/delete actions. |
| `total` | `int` | Total action count. |
| `actions()` | `list[ChangeAction]` | All actions sorted by path. |

### FileEntry

```python
@dataclass
class FileEntry:
    path: str
    type: FileType    # FileType.BLOB, .EXECUTABLE, .LINK
    src: str | None   # source path or None
```

### FileType

```python
class FileType(str, Enum):
    BLOB = "blob"
    EXECUTABLE = "executable"
    LINK = "link"
    TREE = "tree"
```

`FileType.from_filemode(mode)` converts a git filemode integer. `entry.filemode` converts back.

### WriteEntry

Describes a single file write for `fs.apply()`. Frozen (immutable) dataclass.

```python
@dataclass(frozen=True, slots=True)
class WriteEntry:
    data: bytes | str | Path | None = None
    mode: FileType | int | None = None
    target: str | None = None
```

Exactly one of `data` or `target` must be provided. `mode` cannot be combined with `target` (symlinks have no mode).

### WalkEntry

Named tuple yielded by `fs.walk()` in the file-entries list.

```python
class WalkEntry(NamedTuple):
    name: str
    oid: Oid
    filemode: int
```

`entry.file_type` returns the corresponding `FileType`.

### ChangeAction

```python
@dataclass
class ChangeAction:
    path: str       # relative path
    action: str     # "add", "update", "delete"
```

### ChangeError

```python
@dataclass
class ChangeError:
    path: str
    error: str
```

### MirrorDiff

Result of backup/restore operations.

| Field | Type | Description |
|-------|------|-------------|
| `create` | `list[RefChange]` | Refs to create. |
| `update` | `list[RefChange]` | Refs to update. |
| `delete` | `list[RefChange]` | Refs to delete. |

| Property | Returns | Description |
|----------|---------|-------------|
| `in_sync` | `bool` | No changes. |
| `total` | `int` | Total ref changes. |

### RefChange

```python
@dataclass
class RefChange:
    ref: str            # e.g. "refs/heads/main"
    src_sha: str | None
    dest_sha: str | None
```

### ReflogEntry

```python
@dataclass
class ReflogEntry:
    old_sha: str
    new_sha: str
    committer: str
    timestamp: float
    message: str
```

---

## Exceptions

### StaleSnapshotError

Raised when writing from a snapshot whose branch has moved.

```python
fs1 = fs.write("a.txt", b"a")     # branch advances
fs.write("b.txt", b"b")           # StaleSnapshotError -- fs is stale
```

Fix: re-fetch `repo.branches["main"]` and retry -- or use `retry_write` (below).

---

## retry_write

Write a single file with automatic retry on concurrent modification.  Re-fetches the branch FS on each attempt and uses exponential backoff with jitter.

### Synopsis

```python
retry_write(store, branch, path, data, *, message=None, mode=None, retries=5) -> FS
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `store` | `GitStore` | | Open repository. |
| `branch` | `str` | | Branch name. |
| `path` | `str \| PathLike` | | Destination path in the repo. |
| `data` | `bytes` | | File contents. |
| `message` | `str \| None` | `None` | Commit message. |
| `mode` | `FileType \| int \| None` | `None` | File mode (e.g. `FileType.EXECUTABLE` or `0o100755`). |
| `retries` | `int` | `5` | Maximum attempts before raising. |

**Returns:** `FS` -- new snapshot after successful write.

**Raises:** `StaleSnapshotError` if all attempts are exhausted. `KeyError` if the branch does not exist.

### Example

```python
from gitstore import GitStore, retry_write

repo = GitStore.open("data.git")
fs = retry_write(repo, "main", "log.txt", b"new data")
```

### Backoff strategy

Base delay 10 ms, factor 2x, cap 200 ms, with uniform jitter. Delays per attempt: 0--10 ms, 0--20 ms, 0--40 ms, 0--80 ms, then raise.

---

## Stale Snapshot Semantics

Old snapshots remain **readable** -- you can call `read`, `ls`, `exists`, `walk`, `glob`, `log` on them. They raise `StaleSnapshotError` on any write because the branch has moved past them.

To write from an old state, reset the branch or create a new one:

```python
repo.branches["main"] = old_fs        # reset
exp = repo.branches.set("exp", old_fs) # fork
```

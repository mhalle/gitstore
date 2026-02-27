# API Reference -- Kotlin

The Kotlin port of vost uses [JGit](https://www.eclipse.org/jgit/) and targets JVM 21+.
All classes reside in the `vost` package.

---

## Classes Overview

| Class | Description |
|---|---|
| `GitStore` | Open/create a bare git repository and access branches, tags, and notes |
| `RefDict` | Dict-like access to branches or tags |
| `Fs` | Immutable snapshot of a committed tree; supports reads, writes, history, copy/sync |
| `Batch` | Accumulates writes/removes and commits them atomically |
| `FsWriter` | Streaming byte/text writer that commits on close |
| `BatchWriter` | Streaming byte/text writer that stages to a Batch on close |
| `NoteDict` | Container for git notes namespaces |
| `NoteNamespace` | One git notes namespace mapping commit hashes to text |
| `NotesBatch` | Batches note writes/deletes into a single commit |
| `ExcludeFilter` | Gitignore-style exclude filter for copy/sync operations |
| `RepoLock` | Advisory repo lock serializing ref mutations across threads and processes |

### Type Classes

| Type | Description |
|---|---|
| `FileType` | Enum: `BLOB`, `EXECUTABLE`, `LINK`, `TREE` |
| `FileEntry` | File path with `FileType`, used in `ChangeReport` |
| `StatResult` | POSIX-like stat result for a repo path |
| `WalkEntry` | Directory entry with name, OID, and mode |
| `WalkDirEntry` | os.walk-style entry: dirpath, dirnames, files |
| `WriteEntry` | Describes a single file write for `Fs.apply()` |
| `ChangeReport` | Result of a write/copy/sync/move/remove operation |
| `ChangeAction` | A single add/update/delete action in a `ChangeReport` |
| `ChangeActionKind` | Enum: `ADD`, `UPDATE`, `DELETE` |
| `ChangeError` | A file that failed during an operation |
| `Signature` | Author/committer identity for commits |
| `ReflogEntry` | A single reflog entry recording a branch movement |
| `MirrorDiff` | Describes ref changes from a mirror (backup/restore) operation |
| `RefChange` | A single ref change in a mirror operation |
| `BlobOid` | Inline value class wrapping a pre-hashed blob OID hex string |

---

## GitStore

A versioned filesystem backed by a bare git repository.
Implements `AutoCloseable`.

### Static Factory

```kotlin
companion object {
    fun open(
        path: String,
        create: Boolean = true,
        branch: String? = "main",
        author: String = "vost",
        email: String = "vost@localhost",
    ): GitStore
}
```

Open or create a bare git repository at `path`. When `create` is true (default) and the
directory does not exist, a new bare repo is created with an initial empty commit on
`branch`. Pass `branch = null` to create a repo with no branches. Throws
`FileNotFoundException` if `create` is false and the repo does not exist.

### Properties

```kotlin
val branches: RefDict    // Dict-like access to branches
val tags: RefDict         // Dict-like access to tags
val notes: NoteDict       // Git notes namespaces
val signature: Signature  // Default author identity for commits
```

### Methods

```kotlin
fun backup(url: String, dryRun: Boolean = false): MirrorDiff
```
Push all refs to `url`, creating an exact mirror (backup). When `dryRun` is true, computes
the diff but does not push.

```kotlin
fun restore(url: String, dryRun: Boolean = false): MirrorDiff
```
Fetch all refs from `url`, overwriting local state (restore). When `dryRun` is true,
computes the diff but does not fetch.

```kotlin
override fun close()
```
Close the underlying JGit repository. Idempotent.

---

## RefDict

Dict-like access to branches or tags. `store.branches` and `store.tags` are both `RefDict`
instances.

### Get / Set / Delete

```kotlin
operator fun get(name: String): Fs
```
Get an `Fs` snapshot for the named branch or tag. For tags, peels through annotated tags to
the underlying commit. Throws `NoSuchElementException` if the ref does not exist.

```kotlin
operator fun set(name: String, fs: Fs)
```
Set a branch or tag to point at `fs`'s commit. For tags, throws `IllegalStateException` if
the tag already exists. Throws `IllegalArgumentException` for invalid ref names or if `fs`
belongs to a different repository.

```kotlin
fun delete(name: String)
```
Delete a branch or tag. Throws `NoSuchElementException` if the ref does not exist.

```kotlin
fun setAndGet(name: String, fs: Fs): Fs
```
Set branch to `fs` and return a new writable `Fs` bound to it. Convenience for
`set` followed by `get`.

### Query

```kotlin
operator fun contains(name: String): Boolean
```
Check if a branch or tag exists. Supports Kotlin `in` operator: `"main" in store.branches`.

```kotlin
fun exists(name: String): Boolean
```
Alias for `contains`.

```kotlin
fun list(): List<String>
```
List all branch or tag names (without the `refs/heads/` or `refs/tags/` prefix).

```kotlin
val size: Int
```
The number of branches or tags.

```kotlin
operator fun iterator(): Iterator<String>
```
Iterate over ref names.

### Current Branch (branches only)

```kotlin
val currentName: String?
```
The repository's current (HEAD) branch name, or null if HEAD is dangling. Throws
`IllegalStateException` if called on a tags `RefDict`.

```kotlin
val current: Fs?
```
The `Fs` for the current (HEAD) branch, or null if HEAD is dangling. Throws
`IllegalStateException` if called on a tags `RefDict`.

```kotlin
fun setCurrent(name: String)
```
Set the repository's current (HEAD) branch. Throws `IllegalArgumentException` if the branch
does not exist. Throws `IllegalStateException` if called on tags.

### Reflog

```kotlin
fun reflog(name: String): List<ReflogEntry>
```
Read reflog entries for a branch in reverse chronological order. Throws
`IllegalStateException` if called on tags. Throws `NoSuchElementException` if the branch
does not exist. Throws `FileNotFoundException` if no reflog is found.

---

## Fs

An immutable snapshot of a committed tree. Read-only when `writable` is false (tag
snapshots or detached); writable when `writable` is true -- writes auto-commit and return a
new `Fs`.

### Properties

```kotlin
val refName: String?       // Branch or tag name, or null for detached snapshots
val writable: Boolean      // True for branches, false for tags/detached
val commitHash: String     // 40-char hex SHA of this snapshot's commit
val treeHash: String       // 40-char hex SHA of the root tree
val message: String        // Commit message (trailing newline stripped)
val time: ZonedDateTime    // Timezone-aware commit timestamp
val authorName: String     // Commit author's name
val authorEmail: String    // Commit author's email address
var changes: ChangeReport? // Report of the operation that created this snapshot (read-only externally)
```

### Read Operations

```kotlin
fun read(path: String, offset: Int = 0, size: Int? = null): ByteArray
```
Read file contents as bytes. Supports partial reads via `offset` and `size`. Throws
`FileNotFoundException` if the path does not exist. Throws `IsADirectoryError` if the
path is a directory.

```kotlin
fun readText(path: String, encoding: String = "UTF-8"): String
```
Read file contents as a decoded string.

```kotlin
fun readByHash(hash: String, offset: Int = 0, size: Int? = null): ByteArray
```
Read raw blob data by its 40-char hex SHA, bypassing tree lookup. Supports partial reads.

```kotlin
fun readlink(path: String): String
```
Read the target of a symlink. Throws `FileNotFoundException` if the path does not exist.
Throws `IllegalStateException` if the path is not a symlink.

```kotlin
fun ls(path: String? = null): List<String>
```
List entry names at `path` (or root if null). Returns name strings only. Throws
`NotADirectoryError` if the path is a file.

```kotlin
fun listdir(path: String? = null): List<WalkEntry>
```
List directory entries with name, OID, and mode. Suitable for FUSE readdir.

```kotlin
fun walk(path: String? = null): List<WalkDirEntry>
```
Walk the repo tree recursively, like Python's `os.walk`. Returns a list of `WalkDirEntry`
with `dirpath`, `dirnames`, and `files`. Throws `NotADirectoryError` if the path is a file.

```kotlin
fun exists(path: String): Boolean
```
Return true if `path` exists (file, directory, or symlink).

```kotlin
fun isDir(path: String): Boolean
```
Return true if `path` is a directory (tree) in the repo.

```kotlin
fun fileType(path: String): FileType
```
Return the `FileType` of the path. Throws `FileNotFoundException` if the path does not exist.

```kotlin
fun size(path: String): Long
```
Return the size in bytes of the object at the path. Throws `FileNotFoundException` if the
path does not exist.

```kotlin
fun objectHash(path: String): String
```
Return the 40-char hex SHA of the object at the path. Throws `FileNotFoundException` if the
path does not exist.

```kotlin
fun stat(path: String? = null): StatResult
```
Return a `StatResult` for the path (or root if null). Includes mode, fileType, size, hash,
nlink, and mtime.

### Glob Operations

```kotlin
fun glob(pattern: String): List<String>
```
Expand a glob pattern against the repo tree. Returns a sorted, deduplicated list of matching
paths. Supports `*`, `?`, and `**`. Wildcards do not match a leading `.` unless the pattern
segment itself starts with `.`.

```kotlin
fun iglob(pattern: String): List<String>
```
Same as `glob` but returns results in unordered (discovery) order.

### Write Operations

All write methods throw `PermissionError` if the snapshot is read-only and
`StaleSnapshotError` if the branch has advanced since this snapshot was created.

```kotlin
fun write(
    path: String,
    data: ByteArray,
    message: String? = null,
    mode: FileType? = null,
): Fs
```
Write raw bytes to `path` and commit, returning a new `Fs`.

```kotlin
fun writeText(
    path: String,
    text: String,
    encoding: String = "UTF-8",
    message: String? = null,
    mode: FileType? = null,
): Fs
```
Write text to `path` and commit, returning a new `Fs`.

```kotlin
fun writeFromFile(
    path: String,
    localPath: String,
    message: String? = null,
    mode: FileType? = null,
): Fs
```
Write a local file into the repo and commit. Executable permission is auto-detected from
disk unless `mode` is set.

```kotlin
fun writeSymlink(path: String, target: String, message: String? = null): Fs
```
Create a symbolic link entry and commit, returning a new `Fs`.

```kotlin
fun apply(
    writes: Map<String, Any>? = null,
    removes: Collection<String>? = null,
    message: String? = null,
    operation: String? = null,
): Fs
```
Apply multiple writes and removes in a single atomic commit. Values in the `writes` map can
be `ByteArray`, `String`, or `WriteEntry`.

```kotlin
fun remove(paths: List<String>, message: String? = null): Fs
```
Remove files from the repo and commit, returning a new `Fs`.

```kotlin
fun batch(message: String? = null, operation: String? = null): Batch
```
Return a `Batch` for accumulating multiple writes in one commit.

```kotlin
fun writer(path: String, mode: String = "wb"): FsWriter
```
Return a streaming `FsWriter` that commits on close. Mode `"wb"` for binary, `"w"` for
text.

### Rename / Move

```kotlin
fun rename(src: String, dest: String, message: String? = null): Fs
```
Rename a file or directory within the repo.

```kotlin
fun move(sources: List<String>, dest: String, message: String? = null): Fs
```
Move files/directories within the repo using POSIX mv semantics. Supports multiple sources
into a directory destination.

### Copy / Sync

```kotlin
fun copyIn(
    sources: List<String>,
    dest: String,
    message: String? = null,
    delete: Boolean = false,
    exclude: ExcludeFilter? = null,
): Fs
```
Copy local files into the repo. Trailing `/` on a source path copies its contents. When
`delete` is true, removes repo files under `dest` that are not in the source.

```kotlin
fun copyOut(
    sources: List<String>,
    dest: String,
    delete: Boolean = false,
): Fs
```
Copy repo files to local disk. Trailing `/` on a source path copies its contents. When
`delete` is true, removes local files under `dest` that are not in the source.

```kotlin
fun syncIn(
    localPath: String,
    repoPath: String,
    message: String? = null,
    exclude: ExcludeFilter? = null,
): Fs
```
Sync local disk into the repo: copies contents and deletes extras in the repo under
`repoPath`.

```kotlin
fun syncOut(repoPath: String, localPath: String): Fs
```
Sync from the repo to local disk: copies contents and deletes extras on disk under
`localPath`.

```kotlin
fun copyFromRef(
    source: String,
    sources: List<String> = listOf(""),
    dest: String = "",
    delete: Boolean = false,
    message: String? = null,
): Fs
```
Copy files from a named branch or tag into this branch. Resolves `source` to an `Fs` (tries
branches first, then tags). Throws `IllegalArgumentException` if `source` is not a known
branch or tag.

```kotlin
fun copyFromRef(
    source: Fs,
    sources: List<String> = listOf(""),
    dest: String = "",
    delete: Boolean = false,
    message: String? = null,
): Fs
```
Copy files from another `Fs` snapshot into this branch in a single atomic commit. Since both
snapshots share the same object store, blobs are referenced by OID with no data copying.
Throws `IllegalArgumentException` if `source` belongs to a different repo.

### History

```kotlin
val parent: Fs?
```
The parent snapshot, or null for the initial commit.

```kotlin
fun back(n: Int = 1): Fs
```
Return the `Fs` at the n-th ancestor commit. Throws `IllegalArgumentException` if `n < 0`
or history is shorter than `n`.

```kotlin
fun log(path: String? = null): List<Fs>
```
Walk the commit history, returning ancestor `Fs` snapshots. When `path` is provided, only
yields commits that changed that file.

```kotlin
fun undo(steps: Int = 1): Fs
```
Undo the last `steps` commits by resetting the branch to its ancestor. Uses an atomic CAS
ref update. Throws `PermissionError` on read-only snapshots, `StaleSnapshotError` if the
branch advanced, and `IllegalArgumentException` if there is insufficient history.

```kotlin
fun redo(steps: Int = 1): Fs
```
Redo the last `steps` undone commits using the reflog. Uses an atomic CAS ref update. Throws
`PermissionError` on read-only snapshots, `StaleSnapshotError` if the branch advanced, and
`IllegalStateException` if no redo history is found.

---

## Batch

Accumulates writes and removes, committing them in a single atomic commit. Implements
`AutoCloseable` -- closing commits any staged changes. Obtain via `fs.batch()`.

### Properties

```kotlin
var fs: Fs?   // The resulting Fs after commit, or null if uncommitted/aborted (read-only)
```

### Methods

```kotlin
fun write(path: String, data: ByteArray, mode: FileType? = null)
```
Stage a file write with raw bytes.

```kotlin
fun writeText(path: String, text: String, encoding: String = "UTF-8", mode: FileType? = null)
```
Stage a text write. Convenience wrapper around `write`.

```kotlin
fun writeFromFile(path: String, localPath: String, mode: FileType? = null)
```
Stage a write from a local file. Executable permission is auto-detected unless `mode` is
set.

```kotlin
fun writeSymlink(path: String, target: String)
```
Stage a symbolic link entry.

```kotlin
fun remove(path: String)
```
Stage a file removal. Throws `FileNotFoundException` if the path does not exist. Throws
`IsADirectoryError` if the path is a directory.

```kotlin
fun writer(path: String, mode: String = "wb"): BatchWriter
```
Return a `BatchWriter` that stages to this batch on close. Mode `"wb"` for binary, `"w"`
for text.

```kotlin
fun commit(): Fs
```
Explicitly commit the batch. After calling this, the batch is closed and no further writes
are allowed. Returns the resulting `Fs`.

```kotlin
override fun close()
```
Close the batch, committing any staged changes. Idempotent.

---

## FsWriter

Streaming writable file-like object that commits on close. Implements `AutoCloseable`.
Obtain via `fs.writer(path)`.

### Properties

```kotlin
var fs: Fs?        // Resulting Fs after close, or null if still open (read-only)
val closed: Boolean
```

### Methods

```kotlin
fun write(data: ByteArray): Int   // Write bytes (binary mode only); returns bytes written
fun write(text: String): Int      // Write text (text mode only); returns bytes written
override fun close()              // Commit the accumulated data
```

---

## BatchWriter

Streaming writable file-like object that stages to a `Batch` on close. Implements
`AutoCloseable`. Obtain via `batch.writer(path)`.

### Properties

```kotlin
val closed: Boolean
```

### Methods

```kotlin
fun write(data: ByteArray): Int   // Write bytes (binary mode only); returns bytes written
fun write(text: String): Int      // Write text (text mode only); returns bytes written
override fun close()              // Stage the accumulated data to the batch
```

---

## NoteDict

Container for git notes namespaces on a `GitStore`. Access via `store.notes`.

### Properties

```kotlin
val commits: NoteNamespace   // The default refs/notes/commits namespace
```

### Methods

```kotlin
operator fun get(namespace: String): NoteNamespace
```
Get a `NoteNamespace` by name. Maps to `refs/notes/<namespace>`.

---

## NoteNamespace

One git notes namespace, backed by `refs/notes/<name>`. Maps commit targets to UTF-8 note
text. Targets can be 40-char hex commit hashes, branch names, or tag names.

### Get / Set / Delete

```kotlin
operator fun get(target: String): String
operator fun get(fs: Fs): String
```
Get the note text for a commit hash, branch/tag name, or `Fs` snapshot. Throws
`NoSuchElementException` if no note exists. Throws `IllegalArgumentException` if the target
cannot be resolved.

```kotlin
operator fun set(target: String, text: String)
operator fun set(fs: Fs, text: String)
```
Set the note text. Resolves the target to a commit hash. Throws `IllegalArgumentException`
if the target cannot be resolved.

```kotlin
fun delete(target: String)
fun delete(fs: Fs)
```
Delete a note. Throws `NoSuchElementException` if no note exists. Throws
`IllegalArgumentException` if the target cannot be resolved.

### Query

```kotlin
operator fun contains(target: String): Boolean
operator fun contains(fs: Fs): Boolean
```
Check if a note exists. Supports the Kotlin `in` operator.

```kotlin
fun keys(): List<String>
```
Return all commit hashes that have notes in this namespace.

```kotlin
fun size(): Int
```
Return the number of notes.

### Current Branch

```kotlin
fun getForCurrentBranch(): String
```
Get the note for the current HEAD commit. Throws `IllegalStateException` if HEAD is
dangling.

```kotlin
fun setForCurrentBranch(text: String)
```
Set the note for the current HEAD commit. Throws `IllegalStateException` if HEAD is
dangling.

### Batch

```kotlin
fun batch(): NotesBatch
```
Return a `NotesBatch` that batches writes/deletes into a single commit.

---

## NotesBatch

Batches note writes and deletes into a single commit. Implements `AutoCloseable` -- closing
commits any pending changes.

### Methods

```kotlin
operator fun set(target: String, text: String)
operator fun set(fs: Fs, text: String)
```
Stage a note write. Resolves the target to a commit hash.

```kotlin
fun delete(target: String)
fun delete(fs: Fs)
```
Stage a note deletion.

```kotlin
fun commit()
```
Explicitly commit the batch. Throws `IllegalStateException` if already closed.

```kotlin
override fun close()
```
Close the batch, committing any pending changes. Idempotent.

---

## Types

### FileType

```kotlin
enum class FileType {
    BLOB,          // Regular file (mode 0o100644)
    EXECUTABLE,    // Executable file (mode 0o100755)
    LINK,          // Symbolic link (mode 0o120000)
    TREE;          // Directory (mode 0o040000)

    fun filemode(): Int                          // Git filemode integer
    companion object {
        fun fromMode(mode: Int): FileType        // Convert git filemode to FileType
    }
}
```

### FileEntry

```kotlin
data class FileEntry(
    val path: String,         // Relative path (forward slashes)
    val fileType: FileType,   // FileType of the entry
) {
    companion object {
        fun fromMode(path: String, mode: Int): FileEntry
    }
}
```

### StatResult

```kotlin
data class StatResult(
    val mode: Int,            // Raw git filemode (e.g. 0o100644, 0o040000)
    val fileType: FileType,   // FileType enum value
    val size: Long,           // Object size in bytes (0 for directories)
    val hash: String,         // 40-char hex SHA of the object
    val nlink: Int,           // 1 for files/symlinks, 2 + subdirs for directories
    val mtime: Long,          // Commit timestamp as POSIX epoch seconds
)
```

### WalkEntry

```kotlin
data class WalkEntry(
    val name: String,   // Entry name (basename)
    val oid: String,    // 40-char hex object ID
    val mode: Int,      // Git filemode integer
) {
    val fileType: FileType   // Derived from mode
}
```

### WalkDirEntry

```kotlin
data class WalkDirEntry(
    val dirpath: String,           // Directory path relative to walk root
    val dirnames: List<String>,    // Subdirectory names
    val files: List<WalkEntry>,    // File entries
)
```

### WriteEntry

```kotlin
data class WriteEntry(
    val data: ByteArray? = null,   // Raw bytes (mutually exclusive with target)
    val mode: FileType? = null,    // File mode override
    val target: String? = null,    // Symlink target (mutually exclusive with data)
)
```
Exactly one of `data` or `target` must be provided. Mode cannot be set for symlinks.

### ChangeReport

```kotlin
data class ChangeReport(
    val add: List<FileEntry> = emptyList(),
    val update: List<FileEntry> = emptyList(),
    val delete: List<FileEntry> = emptyList(),
    val errors: List<ChangeError> = emptyList(),
    val warnings: List<ChangeError> = emptyList(),
) {
    val inSync: Boolean       // True if no adds, updates, or deletes
    val total: Int            // Count of add + update + delete
    fun actions(): List<ChangeAction>   // Flat list sorted by path
}
```

### ChangeAction

```kotlin
data class ChangeAction(
    val path: String,
    val action: ChangeActionKind,
)
```

### ChangeActionKind

```kotlin
enum class ChangeActionKind {
    ADD, UPDATE, DELETE
}
```

### ChangeError

```kotlin
data class ChangeError(
    val path: String,
    val error: String,
)
```

### Signature

```kotlin
data class Signature(
    val name: String,
    val email: String,
)
```

### ReflogEntry

```kotlin
data class ReflogEntry(
    val oldSha: String,      // Previous commit SHA
    val newSha: String,      // New commit SHA
    val committer: String,   // "Name <email>" string
    val timestamp: Long,     // POSIX epoch seconds
    val message: String,     // Reflog message
)
```

### MirrorDiff

```kotlin
data class MirrorDiff(
    val add: List<RefChange> = emptyList(),
    val update: List<RefChange> = emptyList(),
    val delete: List<RefChange> = emptyList(),
) {
    val inSync: Boolean   // True if no changes
    val total: Int        // Total number of ref changes
}
```

### RefChange

```kotlin
data class RefChange(
    val refName: String,
    val oldTarget: String?,
    val newTarget: String?,
)
```

### BlobOid

```kotlin
@JvmInline
value class BlobOid(val hex: String)
```
Inline value class wrapping a pre-hashed blob OID hex string.

---

## ExcludeFilter

Gitignore-style exclude filter for disk-to-repo copy/sync operations. Supports `!` negation,
`/` suffix for directory-only patterns, and anchored patterns (containing `/`). Last matching
rule wins.

```kotlin
class ExcludeFilter(
    patterns: List<String>? = null,
    excludeFrom: String? = null,
)
```
Construct with initial patterns and/or a path to a file containing patterns.

### Properties

```kotlin
val active: Boolean   // True if any patterns have been loaded
```

### Methods

```kotlin
fun addPatterns(patterns: List<String>)
```
Add gitignore-style patterns. Blank lines and lines starting with `#` are ignored.

```kotlin
fun loadFromFile(path: String)
```
Load patterns from a file (one per line).

```kotlin
fun isExcluded(relPath: String, isDir: Boolean = false): Boolean
```
Check if a relative path is excluded by the current patterns.

---

## RepoLock

Advisory repo lock: serializes ref mutations across threads and processes. Uses a combination
of in-process `ReentrantLock` (thread safety) and file-based locking via `java.nio`
(cross-process safety). This is a singleton `object`.

```kotlin
object RepoLock {
    fun <T> withLock(repoPath: String, block: () -> T): T
}
```

---

## Top-Level Functions

### retryWrite

```kotlin
fun retryWrite(
    store: GitStore,
    branch: String,
    path: String,
    data: ByteArray,
    message: String? = null,
    mode: FileType? = null,
    retries: Int = 5,
): Fs
```
Write data to a branch with automatic retry on `StaleSnapshotError`. Re-fetches the branch
snapshot on each retry with exponential backoff. Throws `StaleSnapshotError` if all retries
are exhausted.

### diskGlob

```kotlin
fun diskGlob(dir: String, pattern: String): List<String>
```
Expand a glob pattern against the local filesystem, respecting dotfile conventions. Returns a
sorted list of matching relative paths. Supports `*`, `?`, and `**`.

### resolveCredentials

```kotlin
fun resolveCredentials(url: String): String
```
Inject credentials into an HTTPS URL if available. Tries `git credential fill` first, then
falls back to `gh auth token` for GitHub hosts. Non-HTTPS URLs and URLs that already contain
credentials are returned unchanged.

---

## Errors / Exceptions

All vost exceptions extend `VostError`, which extends `Exception`.

| Exception | When Thrown |
|---|---|
| `VostError(message, cause?)` | Base exception for all vost errors |
| `StaleSnapshotError(message)` | Write attempted on a snapshot whose branch has advanced; re-fetch and retry |
| `PermissionError(message)` | Write attempted on a read-only snapshot (tag or detached) |
| `GitError(message)` | Low-level git tree operation failed |
| `IsADirectoryError(path)` | Operation expected a file but found a directory |
| `NotADirectoryError(path)` | Path traversal encountered a non-directory entry |

Standard JDK exceptions are also thrown in certain cases:

| Exception | When Thrown |
|---|---|
| `java.io.FileNotFoundException` | Path does not exist in the repo or on disk |
| `NoSuchElementException` | Ref or note not found |
| `IllegalArgumentException` | Invalid argument (bad ref name, unresolvable target, etc.) |
| `IllegalStateException` | Invalid state (batch closed, tags called with branch-only method, etc.) |

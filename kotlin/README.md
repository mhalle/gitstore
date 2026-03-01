# vost (Kotlin)

A versioned filesystem backed by bare Git repositories. Store, retrieve, and version directory trees of files with text and binary data using an immutable-snapshot API. Every write produces a new commit. Old snapshots remain accessible forever.

This is the Kotlin/JVM port of [vost](https://github.com/mhalle/vost), using [JGit](https://www.eclipse.org/jgit/) (org.eclipse.jgit) as the git backend. The repositories are standard Git repos that can be manipulated with Git tools as well.

## Installation

The Kotlin port is not yet published to Maven Central. Use it as a source dependency or build a local JAR:

```bash
# Build
cd kotlin
./gradlew build

# Run tests
./gradlew test
```

Requires Java 21+ and Kotlin 2.1+.

### Gradle dependency (local project)

```kotlin
dependencies {
    implementation(project(":kotlin"))
}
```

### Dependencies

- `org.eclipse.jgit:org.eclipse.jgit:7.1.0` (runtime)
- JUnit 5 + kotlin-test (test only)

## Quick start

```kotlin
import vost.GitStore

// Create (or open) a repository with a "main" branch
val store = GitStore.open("data.git")

// Get a snapshot of the current branch ("main" by default)
var snap = store.branches.current!!

// Write a file -- returns a new immutable snapshot
snap = snap.writeText("hello.txt", "Hello, world!")

// Read it back
println(snap.readText("hello.txt"))  // "Hello, world!"

// Every write is a commit
println(snap.commitHash)             // full 40-char SHA
println(snap.message)                // "+ hello.txt"

store.close()
```

## Core concepts

**Bare repository.** vost uses a bare Git repository with no working directory. All data lives inside Git's content-addressable object store and is accessed through the vost API.

**`GitStore`** opens or creates a bare repository. It exposes `branches`, `tags`, and `notes` as properties. It implements `AutoCloseable`.

**`Fs`** is an immutable snapshot of a committed tree. Reading methods (`read`, `ls`, `walk`, `exists`) never mutate state. Writing methods (`write`, `writeText`, `remove`, `batch`) return a *new* `Fs` pointing at the new commit -- the original `Fs` is unchanged.

Snapshots from **branches** are writable (`fs.writable == true`). Snapshots from **tags** are read-only (`fs.writable == false`).

**All operations are synchronous** -- no coroutines or suspend functions are used.

## API

### Opening a repository

```kotlin
val store = GitStore.open("data.git")                              // create or open
val store = GitStore.open("data.git", create = false)              // open only
val store = GitStore.open("data.git", branch = "dev")              // custom default branch
val store = GitStore.open("data.git", branch = null)               // branchless
val store = GitStore.open("data.git",
    author = "alice", email = "alice@example.com")                 // custom author
```

`GitStore` implements `AutoCloseable`. Use `store.close()` or Kotlin's `use {}` block to release resources.

### Branches and tags

```kotlin
var snap = store.branches["main"]
store.branches["experiment"] = snap          // fork a branch
store.branches.delete("experiment")          // delete a branch

store.tags["v1.0"] = snap                    // create a tag
val tagged = store.tags["v1.0"]              // read-only Fs

val name = store.branches.currentName        // "main"
snap = store.branches.current!!              // Fs for current branch
store.branches.setCurrent("dev")             // set current branch

for (name in store.branches) {
    println(name)
}
println("main" in store.branches)            // true
println(store.branches.list())               // List<String>
println(store.branches.size)                 // number of branches

// Set and get in one step (returns writable Fs)
val fs = store.branches.setAndGet("feature", snap)
```

### Reading

```kotlin
val data = snap.read("path/to/file.bin")                           // ByteArray
val text = snap.readText("config.json")                            // String (UTF-8)
val chunk = snap.read("big.bin", offset = 100, size = 50)          // partial read
val chunk = snap.readByHash(sha, offset = 0, size = 1024)          // read blob by SHA

val entries = snap.ls()                                            // root listing -- List<String>
val entries = snap.ls("src")                                       // subdirectory listing
val details = snap.listdir("src")                                  // List<WalkEntry> (name, oid, mode)
val exists = snap.exists("path/to/file.bin")                       // Boolean
val info = snap.stat("path/to/file.bin")                           // StatResult
val ftype = snap.fileType("run.sh")                                // FileType.EXECUTABLE
val nbytes = snap.size("path/to/file.bin")                         // Long (bytes)
val sha = snap.objectHash("path/to/file.bin")                      // 40-char hex SHA
val link = snap.readlink("symlink")                                // symlink target String
val isDir = snap.isDir("src")                                      // Boolean
val treeHash = snap.treeHash                                       // root tree SHA

// Walk the tree (like os.walk)
for (entry in snap.walk()) {
    for (file in entry.files) {
        println("${entry.dirpath}/${file.name}")                   // WalkEntry
    }
}

// Glob
val matches = snap.glob("**/*.kt")                                // sorted List<String>
val unsorted = snap.iglob("**/*.kt")                               // unsorted List<String>
```

### Writing

Every write auto-commits and returns a new snapshot:

```kotlin
import vost.FileType

snap = snap.writeText("config.json", """{"key": "value"}""")
snap = snap.writeText("script.sh", "#!/bin/sh\n", mode = FileType.EXECUTABLE)
snap = snap.writeText("config.json", "{}", message = "Reset")
snap = snap.write("image.png", rawBytes)                           // ByteArray
snap = snap.writeFromFile("big.bin", "/data/big.bin")              // from disk
snap = snap.writeSymlink("link", "target")                         // symlink
snap = snap.remove(listOf("old-file.txt"))

// Buffered write (commits on close)
val w = snap.writer("big.bin")
w.write(chunk1)
w.write(chunk2)
w.close()
snap = w.fs!!

// Text mode
val tw = snap.writer("log.txt", "w")
tw.write("line 1\n")
tw.write("line 2\n")
tw.close()
snap = tw.fs!!
```

The original `Fs` is never mutated:

```kotlin
val snap1 = store.branches["main"]
val snap2 = snap1.write("new.txt", "data".toByteArray())
println(snap1.exists("new.txt"))  // false -- snap1 is unchanged
println(snap2.exists("new.txt"))  // true
```

### Batch writes

Multiple writes/removes in a single commit:

```kotlin
val batch = snap.batch(message = "Import dataset v2")
batch.write("a.txt", "alpha".toByteArray())
batch.writeText("b.txt", "beta")
batch.writeFromFile("big.bin", "/data/big.bin")
batch.writeSymlink("link.txt", "a.txt")
batch.remove("old.txt")
snap = batch.commit()  // single atomic commit
```

`Batch` implements `AutoCloseable` -- if you use `use {}`, staged changes are committed on close:

```kotlin
snap.batch(message = "Bulk update").use { batch ->
    batch.writeText("a.txt", "alpha")
    batch.writeText("b.txt", "beta")
}
```

A `BatchWriter` provides buffered writes inside a batch:

```kotlin
val batch = snap.batch()
val w = batch.writer("output.bin")
w.write(chunk1)
w.write(chunk2)
w.close()
snap = batch.commit()
```

After `commit()`, the resulting `Fs` is available via `batch.fs`.

### Atomic apply

Apply multiple writes and removes in a single commit without a batch:

```kotlin
import vost.WriteEntry

snap = snap.apply(
    writes = mapOf(
        "config.json" to """{"v": 2}""".toByteArray(),
        "greeting.txt" to "hello",
        "script.sh" to WriteEntry(
            data = "#!/bin/sh\n".toByteArray(),
            mode = FileType.EXECUTABLE,
        ),
        "link" to WriteEntry(target = "config.json"),
    ),
    removes = listOf("old.txt", "deprecated.txt"),
    message = "Update config and clean up",
)
```

Write values can be `ByteArray`, `String`, or `WriteEntry` (for mode/symlink control).

### History

```kotlin
val parent = snap.parent                                   // Fs? (null for initial commit)
val ancestor = snap.back(3)                                // 3 commits back

for (entry in snap.log()) {                                // full commit log
    println("${entry.commitHash} ${entry.message}")
}

for (entry in snap.log("config.json")) {                   // file history
    println("${entry.commitHash} ${entry.message}")
}

snap = snap.undo()                                         // move branch back 1 commit
snap = snap.redo()                                         // move branch forward 1 reflog step
snap = snap.undo(steps = 3)                                // undo 3 commits
snap = snap.redo(steps = 2)                                // redo 2 steps

// Reflog
val entries = store.branches.reflog("main")
for (entry in entries) {
    println("${entry.oldSha} -> ${entry.newSha}: ${entry.message}")
}
```

### Copy and sync

```kotlin
// Disk to repo
snap = snap.copyIn(listOf("./data/"), "backup")
println(snap.changes?.add)                                 // List<FileEntry>

// Repo to disk
snap.copyOut(listOf("docs"), "./local-docs")

// Copy between branches (atomic, no disk I/O)
var main = store.branches["main"]
var dev = store.branches["dev"]
dev = dev.copyFromRef(main, listOf("config"), "imported")

// Copy by branch/tag name
dev = dev.copyFromRef("main", listOf("config/"), "imported")

// Sync (make identical, including deletes)
snap = snap.syncIn("./local", "data")
snap.syncOut("data", "./local")

// Rename and move within repo
snap = snap.rename("old.txt", "new.txt")
snap = snap.move(listOf("file1.txt", "file2.txt"), "archive")

// ExcludeFilter for copy/sync operations
val filter = ExcludeFilter(patterns = listOf("*.log", "tmp/"))
snap = snap.copyIn(listOf("./data/"), "backup", exclude = filter)
snap = snap.syncIn("./local", "data", exclude = filter)
```

### Snapshot properties

```kotlin
snap.commitHash       // String -- full 40-char commit SHA
snap.refName          // String? -- branch or tag name
snap.writable         // Boolean -- true for branches, false for tags
snap.treeHash         // String -- root tree SHA
snap.changes          // ChangeReport? -- from the operation that created this Fs

// Commit metadata (synchronous property access)
snap.message          // String -- commit message
snap.time             // ZonedDateTime -- commit timestamp
snap.authorName       // String
snap.authorEmail      // String
```

### Git notes

Attach metadata to commits without modifying history. Notes can be addressed by commit hash, branch name, tag name, or `Fs` snapshot:

```kotlin
// Default namespace (refs/notes/commits)
val ns = store.notes.commits

// By commit hash
ns[snap.commitHash] = "reviewed by Alice"
println(ns[snap.commitHash])                  // "reviewed by Alice"

// By Fs snapshot
ns[snap] = "reviewed by Alice"
println(ns[snap])                             // "reviewed by Alice"

// By branch or tag name (resolves to tip commit)
ns["main"] = "deployed to staging"
println(ns["main"])                           // "deployed to staging"

ns.delete(snap.commitHash)
println(snap.commitHash in ns)                // false

// Custom namespaces
val reviews = store.notes["reviews"]
reviews["main"] = "LGTM"

// Current branch shorthand
ns.setForCurrentBranch("note for HEAD")
println(ns.getForCurrentBranch())

// Batch writes (single commit)
ns.batch().use { batch ->
    batch["main"] = "note for main"
    batch["dev"] = "note for dev"
    batch.delete("old-branch")
}

// Enumerate notes
for (hash in ns.keys()) {
    println("$hash -> ${ns[hash]}")
}
println(ns.size())                            // number of notes
```

### Backup and restore

```kotlin
val diff = store.backup("/path/to/backup.git")             // MirrorDiff
val diff = store.restore("/path/to/backup.git")            // MirrorDiff
val diff = store.backup(url, dryRun = true)                // preview only
val diff = store.backup("backup.bundle")                   // bundle file
val diff = store.restore("backup.bundle")                  // import bundle
val diff = store.backup(url, refs = listOf("main", "v1.0"))// specific refs

println(diff.inSync)                                        // true if no changes
println(diff.add)                                           // List<RefChange>
println(diff.update)                                        // List<RefChange>
println(diff.delete)                                        // List<RefChange>
```

### Utility functions

```kotlin
import vost.retryWrite
import vost.diskGlob

// Retry write with automatic backoff on StaleSnapshotError
val fs = retryWrite(store, "main", "file.txt", data, retries = 5)

// Glob local filesystem (dotfile-aware)
val files = diskGlob("/path/to/dir", "**/*.kt")           // sorted List<String>
```

## Concurrency safety

vost uses an advisory file lock (`vost.lock`) to make the stale-snapshot check and ref update atomic. If a branch advances after you obtain a snapshot, writing from the stale snapshot throws `StaleSnapshotError`:

```kotlin
import vost.StaleSnapshotError
import vost.retryWrite

var snap = store.branches["main"]
snap.write("a.txt", "a".toByteArray())       // advances the branch

try {
    snap.write("b.txt", "b".toByteArray())    // snap is now stale
} catch (e: StaleSnapshotError) {
    snap = store.branches["main"]             // re-fetch and retry
}

// Or use retryWrite for automatic retry with backoff
snap = retryWrite(store, "main", "file.txt", data)
```

## Error handling

| Exception | When |
|-----------|------|
| `java.io.FileNotFoundException` | `read`/`remove` on a missing path; `writeFromFile` with a missing local file |
| `IsADirectoryError` | `read` on a directory path |
| `NotADirectoryError` | `ls`/`walk` on a file path |
| `PermissionError` | Writing to a tag snapshot |
| `NoSuchElementException` | Accessing a missing branch, tag, or note |
| `IllegalStateException` | Overwriting an existing tag; batch already closed |
| `IllegalArgumentException` | Invalid ref name; invalid path; invalid arguments |
| `StaleSnapshotError` | Writing from a snapshot whose branch has moved forward |
| `GitError` | Low-level git tree operation failure |

All vost-specific exceptions (`StaleSnapshotError`, `PermissionError`, `GitError`, `IsADirectoryError`, `NotADirectoryError`) extend `VostError`, which extends `Exception`.

## Types reference

| Type | Description |
|------|-------------|
| `Fs` | Immutable snapshot of a committed tree |
| `Batch` | Accumulates writes/removes for a single atomic commit |
| `RefDict` | Dict-like access to branches or tags |
| `NoteDict` | Container for note namespaces |
| `NoteNamespace` | One git notes namespace |
| `NotesBatch` | Batched note writes/deletes |
| `FileType` | Enum: `BLOB`, `EXECUTABLE`, `LINK`, `TREE` |
| `FileEntry` | File path with `FileType` |
| `WalkEntry` | Entry with `name`, `oid`, `mode` |
| `WalkDirEntry` | Directory entry with `dirpath`, `dirnames`, `files` |
| `StatResult` | POSIX-like stat: `mode`, `fileType`, `size`, `hash`, `nlink`, `mtime` |
| `WriteEntry` | Write descriptor for `apply()`: `data`, `mode`, `target` |
| `ChangeReport` | Result of an operation: `add`, `update`, `delete`, `errors` |
| `ChangeAction` | Single action: `path`, `action` (ADD/UPDATE/DELETE) |
| `ChangeError` | Failed file: `path`, `error` |
| `Signature` | Author identity: `name`, `email` |
| `ReflogEntry` | Reflog entry: `oldSha`, `newSha`, `committer`, `timestamp`, `message` |
| `MirrorDiff` | Mirror result: `add`, `update`, `delete` of `RefChange` |
| `RefChange` | Ref change: `refName`, `oldTarget`, `newTarget` |
| `BlobOid` | Inline class wrapping a hex SHA string |
| `ExcludeFilter` | Gitignore-style path filter for copy/sync |
| `FsWriter` | Buffered writer that commits on close |
| `BatchWriter` | Buffered writer that stages to a batch on close |

## Documentation

- [Python version](https://github.com/mhalle/vost) -- the reference implementation with CLI
- [TypeScript version](https://github.com/mhalle/vost/tree/master/ts) -- npm package `@mhalle/vost`

## License

Apache-2.0 -- see [LICENSE](../LICENSE) for details.

# vost -- C++ port

C++17 port of [vost](../README.md), a git-backed versioned object store.

Uses [libgit2](https://libgit2.org/) for all git operations.

## Quick start

```cpp
#include <vost/vost.h>

// Open (or create) a bare repository
auto store = vost::GitStore::open("/path/to/store.git",
                                  {.create = true, .branch = "main"});
// Get a snapshot of the branch
auto fs = store.branches()["main"];

// Read
std::string text = fs.read_text("README.md");
auto entries     = fs.ls();           // list root
auto all         = fs.walk();         // recursive walk

// Write — returns NEW snapshot; reassign to advance
fs = fs.write_text("note.txt", "hello");
fs = fs.write_symlink("link", "note.txt");

// Batch multiple writes into one commit
fs = fs.batch()
       .write_text("a.txt", "A")
       .write_text("b.txt", "B")
       .commit();

// History
auto prev = fs.parent();    // nullopt at root
auto old  = fs.back(3);     // 3 commits back

// Tags (read-only snapshots)
store.tags().set("v1.0", fs);
auto tag = store.tags()["v1.0"];  // writable() == false
```

## Building

### Prerequisites

- CMake >= 3.20
- C++17 compiler
- [vcpkg](https://github.com/microsoft/vcpkg) (for libgit2 + Catch2)

```bash
# Install vcpkg if needed
git clone https://github.com/microsoft/vcpkg.git
./vcpkg/bootstrap-vcpkg.sh

# Configure + build
cmake -B build -S cpp/ \
      -DCMAKE_TOOLCHAIN_FILE=/path/to/vcpkg/scripts/buildsystems/vcpkg.cmake
cmake --build build

# Run tests
ctest --test-dir build --output-on-failure
```

### Without vcpkg

Install libgit2 and Catch2 via your system package manager:

```bash
# macOS
brew install libgit2 catch2

# Ubuntu / Debian
apt install libgit2-dev catch2

# Then configure without vcpkg toolchain
cmake -B build -S cpp/
cmake --build build
```

## API

### Opening a repository

```cpp
#include <vost/vost.h>

// Create or open a bare repository
auto store = vost::GitStore::open("/path/to/store.git",
                                  {.create = true, .branch = "main"});

// Open existing only (throws NotFoundError if missing)
auto store = vost::GitStore::open("/path/to/store.git");

// Custom default branch
auto store = vost::GitStore::open("/path/to/store.git",
                                  {.create = true, .branch = "dev"});

// Custom author identity
auto store = vost::GitStore::open("/path/to/store.git",
                                  {.create = true,
                                   .author = "alice",
                                   .email  = "alice@example.com"});

// Metadata
store.path();       // std::filesystem::path to the bare repo
store.signature();  // Signature{name, email}
```

### Branches and tags

Branches and tags are accessed through `RefDict` objects. Branch snapshots
are writable; tag snapshots are read-only.

```cpp
auto fs = store.branches()["main"];          // get snapshot (throws KeyNotFoundError)
store.branches().set("experiment", fs);      // fork a branch
store.branches().del("experiment");          // delete a branch
store.branches().contains("main");           // true

store.tags().set("v1.0", fs);               // create a tag (throws KeyExistsError on dup)
auto tagged = store.tags()["v1.0"];          // read-only: tagged.writable() == false

// Enumerate all branches
for (auto& name : store.branches().keys()) {
    auto snap = store.branches()[name];
}

// Current branch (HEAD)
auto name = store.branches().current_name(); // std::optional<std::string>
auto snap = store.branches().current();      // std::optional<Fs>
store.branches().set_current("dev");         // point HEAD at "dev"

// Point a ref and get back a writable Fs in one step
auto fs2 = store.branches().set_and_get("new-branch", fs);

// Detached (read-only) snapshot by commit hash
auto detached = store.fs("abc123...");       // 40-char hex SHA
```

### Reading

All read operations are const and never mutate state.

```cpp
// File contents
auto data = fs.read("image.png");                   // std::vector<uint8_t>
auto text = fs.read_text("config.json");            // std::string (UTF-8)

// Partial read (for FUSE / streaming)
auto chunk = fs.read_range("big.bin", 100, 50);     // offset=100, size=50

// Read blob by SHA, bypassing tree lookup
auto blob = fs.read_by_hash(sha, 0, 1024);

// Directory listing
auto names = fs.ls();                               // root listing: vector<string>
auto names = fs.ls("src");                           // subdirectory listing

// Detailed listing (for FUSE readdir)
auto entries = fs.listdir("src");                    // vector<WalkEntry>
for (auto& e : entries) {
    // e.name, e.oid (40-char hex), e.mode
}

// Recursive walk (os.walk style)
for (auto& dir : fs.walk()) {
    // dir.dirpath, dir.dirnames, dir.files (vector<WalkEntry>)
}

// Existence and type checks
fs.exists("path/to/file.txt");                       // bool
fs.is_dir("src");                                    // bool
fs.file_type("run.sh");                              // FileType::Executable
fs.size("data.bin");                                 // uint64_t (bytes)

// Object hash and symlink target
auto sha = fs.object_hash("file.txt");               // 40-char hex SHA
auto target = fs.readlink("symlink");                 // symlink target string

// stat (single-call getattr for FUSE)
auto st = fs.stat("file.txt");
// st.mode, st.file_type, st.size, st.hash, st.nlink, st.mtime

// Glob
auto matches = fs.glob("**/*.cpp");                  // sorted vector<string>
auto matches = fs.iglob("**/*.cpp");                 // unsorted (faster)

// Disk glob (local filesystem, not the repo)
auto files = vost::disk_glob("src/**/*.h");
```

### Writing

Every write auto-commits and returns a **new** `Fs`. The original snapshot
is never mutated.

```cpp
// Text and binary writes
fs = fs.write_text("config.json", R"({"key": "value"})");
fs = fs.write("image.png", raw_bytes);               // vector<uint8_t>

// Custom commit message
fs = fs.write_text("config.json", "{}", {.message = "Reset config"});

// Executable file
fs = fs.write_text("run.sh", "#!/bin/sh\n", {.mode = vost::MODE_BLOB_EXEC});

// Symlink
fs = fs.write_symlink("link", "target.txt");

// Import from local disk
fs = fs.write_from_file("data.bin", "/local/path/data.bin");

// Remove
fs = fs.remove({"old-file.txt", "deprecated/"});
fs = fs.remove({"dir/"}, {.recursive = true});

// Rename
fs = fs.rename("old.txt", "new.txt");

// Move (POSIX mv semantics, multiple sources)
fs = fs.move({"a.txt", "b.txt"}, "dest-dir/");
```

The original `Fs` is never mutated:

```cpp
auto snap1 = store.branches()["main"];
auto snap2 = snap1.write_text("new.txt", "data");
snap1.exists("new.txt");  // false -- snap1 is unchanged
snap2.exists("new.txt");  // true
```

Streaming writes with `FsWriter`:

```cpp
auto w = vost::FsWriter(fs, "big.bin");
w.write(chunk1);
w.write(chunk2);
fs = w.close();
```

### Batch writes

Multiple writes and removes committed atomically in a single commit.
`Batch` methods return `Batch&` for fluent chaining.

```cpp
// Fluent style
fs = fs.batch({.message = "Import dataset v2"})
       .write_text("a.txt", "alpha")
       .write("b.bin", raw_bytes)
       .write_symlink("link", "a.txt")
       .write_from_file("big.bin", "/data/big.bin")
       .remove("old.txt")
       .commit();

// Imperative style
auto batch = fs.batch();
batch.write_text("a.txt", "alpha");
batch.write_with_mode("script.sh", script_bytes, vost::MODE_BLOB_EXEC);  // explicit mode
batch.remove("old.txt");
fs = batch.commit();

// Result and state
batch.closed();          // true after commit()
batch.fs();              // std::optional<Fs> -- the committed snapshot
batch.pending_writes();  // size_t
batch.pending_removes(); // size_t
```

Streaming writes within a batch with `BatchWriter`:

```cpp
auto batch = fs.batch();
{
    auto w = vost::BatchWriter(batch, "log.txt");
    w.write("line 1\n");
    w.write("line 2\n");
    w.close();  // stages to batch (also called by destructor)
}
batch.write_text("other.txt", "done");
fs = batch.commit();
```

### Atomic apply

Apply a set of writes and removes in one commit without creating a `Batch`
object:

```cpp
using vost::WriteEntry;

fs = fs.apply(
    {   // writes: vector<pair<string, WriteEntry>>
        {"config.json", WriteEntry::from_text(R"({"v": 2})")},
        {"script.sh",   WriteEntry{std::vector<uint8_t>{'#','!'},
                                   std::nullopt, vost::MODE_BLOB_EXEC}},
        {"link",        WriteEntry::symlink("config.json")},
    },
    {"old.txt", "deprecated/"},   // removes: vector<string>
    {.message = "Update config and clean up"}
);
```

### History

```cpp
// Parent and ancestor navigation
auto parent = fs.parent();              // std::optional<Fs>
auto ancestor = fs.back(3);             // Fs 3 commits back

// Commit log
auto entries = fs.log();                // vector<CommitInfo>
for (auto& ci : entries) {
    // ci.commit_hash, ci.message, ci.time, ci.author_name, ci.author_email
}

// Filtered log
auto entries = fs.log({.limit = 10, .path = "config.json"});
auto entries = fs.log({.match_pattern = "fix*"});

// Undo / redo
fs = fs.undo();                         // reset branch to parent
fs = fs.undo(3);                        // reset branch 3 commits back
fs = fs.redo();                         // re-advance using reflog

// Reflog
auto reflog = store.branches().reflog("main");
for (auto& entry : reflog) {
    // entry.old_sha, entry.new_sha, entry.committer,
    // entry.timestamp, entry.message
}
```

### Copy and sync

```cpp
// Disk to repo
auto [report, fs2] = fs.copy_in("/local/data/", "backup");
// report.add, report.update, report.del -- vectors of FileEntry

// Repo to disk
auto report = fs.copy_out("docs", "/local/docs");

// With include/exclude filters
auto [report, fs2] = fs.copy_in("/src/", "src",
    {.include = {{"*.cpp", "*.h"}}, .exclude = {{"*.o"}}});

// Dry run (preview without committing)
auto [report, _] = fs.copy_in("/data/", "backup", {.dry_run = true});

// Copy between branches (zero-copy, reuses blob OIDs)
auto main = store.branches()["main"];
auto dev  = store.branches()["dev"];
dev = dev.copy_from_ref(main, {"config/"}, "imported/");

// Copy from a named branch or tag (string overload)
dev = dev.copy_from_ref("main", {"config/"}, "imported/");

// Sync (make destination identical to source, including deletes)
auto [report, fs2] = fs.sync_in("/local/", "data");
auto report = fs.sync_out("data", "/local/");
```

### Snapshot properties

All properties are accessed via methods (no fields):

```cpp
fs.commit_hash();     // std::optional<std::string> -- 40-char hex SHA
fs.tree_hash();       // std::optional<std::string> -- root tree SHA
fs.ref_name();        // std::optional<std::string> -- branch or tag name
fs.writable();        // bool -- true for branches, false for tags/detached
fs.message();         // std::string -- commit message
fs.time();            // uint64_t -- POSIX epoch seconds
fs.author_name();     // std::string
fs.author_email();    // std::string
fs.changes();         // std::optional<ChangeReport>
```

### Git notes

Attach metadata to commits without modifying history. The notes API uses three
classes: `NoteDict` (from `store.notes()`), `NoteNamespace` (a single notes
ref), and `NotesBatch` (for atomic multi-note writes). Notes can be addressed
by commit hash, `Fs` snapshot, or ref name (branch/tag):

```cpp
// Default namespace (refs/notes/commits)
auto ns = store.notes().commits();

// Set and get by commit hash
ns.set(fs.commit_hash().value(), "reviewed by Alice");
auto text = ns.get(fs.commit_hash().value());

// Set and get by Fs snapshot
ns.set(fs, "reviewed by Alice");
auto text = ns.get(fs);

// By branch or tag name (resolves to tip commit)
ns.set("main", "deployed to staging");
auto text = ns.get("main");

// Delete
ns.del(fs);

// Check existence
ns.has(fs);                           // bool

// Iterate
for (auto& hash : ns.list()) {       // vector<string>, sorted
    auto note = ns.get(hash);
}
ns.size();                            // number of notes
ns.empty();                           // true if no notes

// Current branch shortcut
ns.set_for_current_branch("deployed");
auto text = ns.get_for_current_branch();

// Custom namespaces
auto reviews = store.notes().ns("reviews");
auto reviews = store.notes()["reviews"];     // same thing

// Batch writes (single commit)
auto batch = ns.batch();
batch.set("main", "note for main");
batch.set("dev", "note for dev");
batch.del(old_hash);
batch.commit();
```

### Backup and restore

Mirror a repository to or from a local path or remote URL:

```cpp
// Push all refs to a destination
auto diff = store.backup("https://github.com/user/repo.git");
// diff.add, diff.update, diff.del -- vectors of RefChange

// Fetch all refs from a source
auto diff = store.restore("https://github.com/user/repo.git");

// Dry run (preview without pushing/fetching)
auto diff = store.backup(dest, {.dry_run = true});

// Local path
auto diff = store.backup("/backups/store.git");

// Bundle file (auto-detected from .bundle extension)
auto diff = store.backup("backup.bundle");
auto diff = store.restore("backup.bundle");

// Specific refs only
auto diff = store.backup(url, {.refs = {"main", "v1.0"}});

// Resolve credentials for HTTPS URLs
auto url = vost::resolve_credentials("https://github.com/user/repo.git");
```

### Bundle export and import

Create and import bundle files directly:

```cpp
store.bundle_export("backup.bundle");                     // all refs
store.bundle_export("backup.bundle", {"main", "v1.0"});   // specific refs
store.bundle_import("backup.bundle");                     // import all (additive)
store.bundle_import("backup.bundle", {"main"});           // specific refs
```

## Concurrency safety

vost uses an advisory file lock (`vost.lock`) to make the stale-snapshot
check and ref update atomic. If a branch advances after you obtain a
snapshot, writing from the stale snapshot throws `StaleSnapshotError`:

```cpp
auto fs = store.branches()["main"];
fs.write_text("a.txt", "a");                     // advances the branch

try {
    fs.write_text("b.txt", "b");                  // fs is now stale
} catch (const vost::StaleSnapshotError&) {
    fs = store.branches()["main"];                // re-fetch and retry
}
```

Use `retry_write` for automatic retry with exponential backoff (up to 6
attempts):

```cpp
int n = 0;
auto result = vost::retry_write([&]() {
    auto fs = store.branches()["main"];
    return fs.write_text("counter.txt", std::to_string(++n));
});
```

## Error handling

All vost exceptions derive from `VostError`, which itself derives from
`std::runtime_error`. Catch `VostError` for a broad catch-all, or catch
specific subclasses:

```cpp
try {
    auto text = fs.read_text("missing.txt");
} catch (const vost::NotFoundError& e) {
    // e.path() returns the missing path
    // e.what() returns "not found: missing.txt"
} catch (const vost::VostError& e) {
    // catch-all for any vost error
}
```

| Exception | When |
|---|---|
| `NotFoundError` | `read`/`remove` on a missing path; `write_from_file` with a missing local file |
| `IsADirectoryError` | `read` on a directory path |
| `NotADirectoryError` | `ls`/`walk` on a file path |
| `PermissionError` | Writing to a tag or detached snapshot |
| `StaleSnapshotError` | Writing from a snapshot whose branch has moved forward |
| `KeyNotFoundError` | Accessing a missing branch or tag |
| `KeyExistsError` | Overwriting an existing tag |
| `InvalidPathError` | Invalid path (e.g., `..`, empty segments) |
| `InvalidHashError` | Malformed 40-char hex SHA or unresolvable ref name |
| `InvalidRefNameError` | Invalid characters in branch/tag name |
| `BatchClosedError` | Writing to a `Batch` after `commit()` |
| `GitError` | Low-level libgit2 failure |
| `IoError` | Filesystem I/O error |

Full hierarchy:

```
VostError (extends std::runtime_error)
+-- NotFoundError
+-- IsADirectoryError
+-- NotADirectoryError
+-- PermissionError
+-- StaleSnapshotError
+-- KeyNotFoundError
+-- KeyExistsError
+-- InvalidPathError
+-- InvalidHashError
+-- InvalidRefNameError
+-- BatchClosedError
+-- GitError
+-- IoError
```

## Documentation

- [Python version](https://github.com/mhalle/vost) -- the reference implementation with CLI
- [TypeScript port](https://github.com/mhalle/vost/tree/master/ts) -- isomorphic-git backend
- [Rust port](https://github.com/mhalle/vost/tree/master/rs) -- gitoxide backend
- [Kotlin port](https://github.com/mhalle/vost/tree/master/kotlin) -- JGit backend

## License

Apache-2.0 -- see [LICENSE](../LICENSE) for details.

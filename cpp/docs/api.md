# API Reference -- C++

> **Header:** `#include <vost/vost.h>` (umbrella header)
> **Namespace:** `vost`
> **Standard:** C++17
> **Backend:** libgit2

All public symbols live in `namespace vost`.
Include the umbrella header `<vost/vost.h>` to get the entire API, or include
individual headers for finer control.

---

## Classes overview

| Class | Header | Description |
|---|---|---|
| `GitStore` | `gitstore.h` | Entry point -- opens or creates a bare git repository |
| `RefDict` | `gitstore.h` | Transient view over branches or tags |
| `Fs` | `fs.h` | Read-write snapshot of a git tree at a specific commit |
| `Batch` | `batch.h` | Accumulates writes/removes for a single atomic commit |
| `FsWriter` | `fs.h` | RAII streaming writer that commits on close |
| `BatchWriter` | `batch.h` | RAII streaming writer that stages to a Batch on close |
| `NoteDict` | `notes.h` | Access point for all git note namespaces |
| `NoteNamespace` | `notes.h` | Read/write notes under a single `refs/notes/<ns>` ref |
| `NotesBatch` | `notes.h` | Accumulates note writes/deletes for a single commit |
| `ExcludeFilter` | `types.h` | Gitignore-style path exclusion filter |

---

## GitStore

A versioned filesystem backed by a bare git repository.
Cheap to copy -- internally holds a `shared_ptr<GitStoreInner>`.

### Construction

```cpp
static GitStore open(const std::filesystem::path& path,
                     OpenOptions opts = {});
```

Open (or create) a bare git repository at `path`.
Throws `NotFoundError` if the repo does not exist and `opts.create` is false.
Throws `GitError` on libgit2 failures.

### Navigation

```cpp
RefDict branches();
```

Return a `RefDict` for branches (`refs/heads/`).

```cpp
RefDict tags();
```

Return a `RefDict` for tags (`refs/tags/`).

```cpp
Fs fs(const std::string& hash);
```

Return a detached (read-only) `Fs` for a commit identified by its 40-char hex SHA.

```cpp
NoteDict notes();
```

Return a `NoteDict` for accessing git notes.

### Mirror

```cpp
MirrorDiff backup(const std::string& dest, bool dry_run = false);
```

Push all local refs to `dest`, creating an exact mirror.
Supports local paths and remote URLs. Auto-creates a bare repo at local
destinations that do not yet exist.

```cpp
MirrorDiff restore(const std::string& src, bool dry_run = false);
```

Fetch all refs from `src`, overwriting local state.

### Metadata

```cpp
const std::filesystem::path& path() const;
```

Path to the bare repository on disk.

```cpp
const Signature& signature() const;
```

The default signature used for commits.

```cpp
std::shared_ptr<GitStoreInner> inner() const;
```

Access the shared inner state (used internally by `Fs`, `RefDict`, `Batch`).

---

## RefDict

A transient view over a set of git references sharing a common prefix
(`refs/heads/` for branches, `refs/tags/` for tags).

Obtained via `store.branches()` or `store.tags()`.

### Lookup

```cpp
Fs get(const std::string& name);
```

Get the `Fs` snapshot for the named branch or tag.
Throws `NotFoundError` if the ref does not exist.

```cpp
Fs operator[](const std::string& name);
```

Convenience operator -- same as `get()`.

### Mutation

```cpp
void set(const std::string& name, const Fs& fs);
```

Point the named ref at the commit of `fs`.
Throws `InvalidRefNameError` for bad ref names.
Throws `KeyExistsError` when overwriting a tag.

```cpp
Fs set_and_get(const std::string& name, const Fs& fs);
```

Point the named ref at the commit of `fs` and return a new writable `Fs`
bound to it. Equivalent to `set()` followed by `get()`.

```cpp
void del(const std::string& name);
```

Delete the named ref.
Throws `KeyNotFoundError` if the ref does not exist.

### Query

```cpp
bool contains(const std::string& name);
```

Return true if the named ref exists.

```cpp
std::vector<std::string> keys();
```

Return all ref names under this prefix (without the prefix).

```cpp
std::vector<Fs> values();
```

Return `Fs` snapshots for all refs under this prefix.

### Current branch (HEAD)

```cpp
std::optional<std::string> current_name();
```

Get the current branch name (HEAD), or `nullopt` if not set.
Only meaningful for `branches()`.

```cpp
std::optional<Fs> current();
```

Get the current branch `Fs` (HEAD), or `nullopt` if not set.

```cpp
void set_current(const std::string& name);
```

Set HEAD to point at `name`. Only valid for `branches()`.

### Reflog

```cpp
std::vector<ReflogEntry> reflog(const std::string& name);
```

Return the reflog for the named ref (most-recent first).

---

## Fs

A read-only or read-write snapshot of a git tree at a specific commit.
Cheap to copy -- holds a `shared_ptr<GitStoreInner>` plus a few scalar fields.
Write operations return a **new** `Fs` representing the resulting commit.

### Properties

```cpp
std::optional<std::string> commit_hash() const;
```

40-char hex SHA of the commit, or `nullopt` for empty snapshots.

```cpp
std::optional<std::string> tree_hash() const;
```

40-char hex SHA of the root tree, or `nullopt` for empty snapshots.

```cpp
const std::optional<std::string>& ref_name() const;
```

Branch or tag name, or `nullopt` for detached snapshots.

```cpp
bool writable() const;
```

True for branch snapshots, false for tags and detached commits.

```cpp
std::string message() const;
```

Commit message (trailing newline stripped).
Throws `NotFoundError` if no commit.

```cpp
uint64_t time() const;
```

Commit timestamp as POSIX epoch seconds.
Throws `NotFoundError` if no commit.

```cpp
std::string author_name() const;
```

Commit author name.

```cpp
std::string author_email() const;
```

Commit author email.

```cpp
const std::optional<ChangeReport>& changes() const;
```

Change report from the write operation that produced this snapshot.
Returns `nullopt` if the snapshot was not produced by a write.

### Read operations

```cpp
std::vector<uint8_t> read(const std::string& path) const;
```

Read file contents as raw bytes.
Throws `NotFoundError` if path does not exist.
Throws `IsADirectoryError` if path is a directory.

```cpp
std::string read_text(const std::string& path) const;
```

Read file contents as a UTF-8 string.
Throws `NotFoundError` if path does not exist.

```cpp
std::vector<uint8_t> read_range(const std::string& path,
                                size_t offset,
                                std::optional<size_t> size = std::nullopt) const;
```

Read with optional byte-range (for FUSE partial reads).
If `size` is `nullopt`, reads from `offset` to end of file.

```cpp
std::vector<uint8_t> read_by_hash(const std::string& hash,
                                  size_t offset = 0,
                                  std::optional<size_t> size = std::nullopt) const;
```

Read raw blob data by its hex hash, bypassing tree lookup.
Supports optional byte-range selection.

```cpp
std::vector<std::string> ls(const std::string& path = "") const;
```

List entry names at `path` (or root if empty). Returns name strings only.
Throws `NotADirectoryError` if path is a file.

```cpp
std::vector<WalkEntry> listdir(const std::string& path = "") const;
```

List directory entries with name, OID, and mode -- for FUSE readdir.

```cpp
std::vector<WalkDirEntry> walk(const std::string& path = "") const;
```

Recursively walk all directories under `path` (os.walk-style).
Returns one `WalkDirEntry` per directory, each with `dirnames` and `files`.

```cpp
bool exists(const std::string& path) const;
```

Return true if `path` exists (file, directory, or symlink).

```cpp
bool is_dir(const std::string& path) const;
```

Return true if `path` is a directory.

```cpp
FileType file_type(const std::string& path) const;
```

Return the `FileType` of `path`.
Throws `NotFoundError` if path does not exist.

```cpp
uint64_t size(const std::string& path) const;
```

Return the size in bytes of the object at `path`.
Throws `NotFoundError` if path does not exist.
Throws `IsADirectoryError` if path is a directory.

```cpp
std::string object_hash(const std::string& path) const;
```

Return the 40-char hex SHA of the object at `path`.

```cpp
std::string readlink(const std::string& path) const;
```

Read the target of a symlink at `path`.

```cpp
StatResult stat(const std::string& path = "") const;
```

Single-call getattr for FUSE.
Throws `NotFoundError` if path does not exist.

```cpp
std::vector<std::string> glob(const std::string& pattern) const;
```

Glob for matching paths. Returns results sorted.

```cpp
std::vector<std::string> iglob(const std::string& pattern) const;
```

Glob for matching paths. Returns results unsorted (faster).

### Write operations

All write operations require `writable() == true` (branch snapshots).
They throw `PermissionError` for read-only snapshots and
`StaleSnapshotError` if the branch tip has advanced since the snapshot was taken.

```cpp
Fs write(const std::string& path,
         const std::vector<uint8_t>& data,
         WriteOptions opts = {}) const;
```

Write `data` to `path` and commit, returning a new `Fs`.

```cpp
Fs write_text(const std::string& path,
              const std::string& text,
              WriteOptions opts = {}) const;
```

Write a UTF-8 string to `path` and commit, returning a new `Fs`.

```cpp
Fs write_from_file(const std::string& path,
                   const std::filesystem::path& local_path,
                   WriteOptions opts = {}) const;
```

Write a local file from disk into the store.
Throws `IoError` if the local file cannot be read.

```cpp
Fs write_symlink(const std::string& path,
                 const std::string& target,
                 WriteOptions opts = {}) const;
```

Write a symlink at `path` pointing to `target`.

```cpp
Fs apply(const std::vector<std::pair<std::string, WriteEntry>>& writes,
         const std::vector<std::string>& removes = {},
         ApplyOptions opts = {}) const;
```

Apply a batch of writes and removes in a single atomic commit.
Each element of `writes` is a `(path, WriteEntry)` pair.

```cpp
Fs remove(const std::vector<std::string>& paths,
          RemoveOptions opts = {}) const;
```

Remove one or more paths and commit.

```cpp
Fs rename(const std::string& src, const std::string& dest,
          WriteOptions opts = {}) const;
```

Rename a file or directory from `src` to `dest`.
Throws `NotFoundError` if `src` does not exist.

```cpp
Fs move(const std::vector<std::string>& sources,
        const std::string& dest,
        MoveOptions opts = {}) const;
```

Move files/directories within the repo (POSIX mv semantics).
Supports multiple sources into a directory destination.
Throws `NotFoundError` if a source path does not exist.

### Batch

```cpp
Batch batch(BatchOptions opts = {}) const;
```

Return a `Batch` accumulator for this snapshot.

### Copy / Sync

```cpp
Fs copy_from_ref(const Fs& source,
                 const std::vector<std::string>& sources = {""},
                 const std::string& dest = "",
                 CopyFromRefOptions opts = {}) const;
```

Copy files from one ref to another within the same repo.
Reuses blob OIDs for efficiency -- no data is read into memory.
Follows rsync trailing-slash conventions: a trailing slash on a source path
means "contents of" rather than the directory itself.

```cpp
Fs copy_from_ref(const std::string& source_name,
                 const std::vector<std::string>& sources = {""},
                 const std::string& dest = "",
                 CopyFromRefOptions opts = {}) const;
```

Copy files from a named branch or tag into this branch.
Resolves the name to an `Fs` (tries branches first, then tags),
then delegates to the `Fs`-based overload.
Throws `InvalidHashError` if the name is not a known branch or tag.

```cpp
std::pair<ChangeReport, Fs>
copy_in(const std::filesystem::path& src,
        const std::string& dest = "",
        CopyInOptions opts = {}) const;
```

Copy files from local disk `src` into the store at `dest`.
Returns a pair of `ChangeReport` and the new `Fs`.

```cpp
ChangeReport
copy_out(const std::string& src,
         const std::filesystem::path& dest,
         CopyOutOptions opts = {}) const;
```

Copy files from the store at `src` to local disk `dest`.

```cpp
std::pair<ChangeReport, Fs>
sync_in(const std::filesystem::path& src,
        const std::string& dest = "",
        SyncOptions opts = {}) const;
```

Sync local disk `src` into the store at `dest` (copy + delete extras).

```cpp
ChangeReport
sync_out(const std::string& src,
         const std::filesystem::path& dest,
         SyncOptions opts = {}) const;
```

Sync from the store at `src` to local disk `dest` (copy + delete extras).

### History navigation

```cpp
std::optional<Fs> parent() const;
```

Return the parent `Fs`, or `nullopt` if this is an initial commit.

```cpp
Fs back(size_t n) const;
```

Return an `Fs` `n` commits behind HEAD on the same branch.

```cpp
std::vector<CommitInfo> log(LogOptions opts = {}) const;
```

Return commit history matching the given filters.

```cpp
Fs undo(size_t n = 1) const;
```

Undo the last `n` commits by resetting the branch to its n-th ancestor.
Throws `NotFoundError` if there is insufficient history.

```cpp
Fs redo(size_t n = 1) const;
```

Redo the last `n` undone commits using the reflog.
Throws `NotFoundError` if no redo history is found.

### Static factories (internal)

```cpp
static Fs from_commit(std::shared_ptr<GitStoreInner> inner,
                      const std::string& commit_oid_hex,
                      std::optional<std::string> ref_name,
                      bool writable);
```

Construct an `Fs` from a raw commit hex SHA.

```cpp
static Fs empty(std::shared_ptr<GitStoreInner> inner,
                std::string ref_name);
```

Construct an empty `Fs` (no commit, no tree) for a new branch.

---

## Batch

Accumulates writes and removes, then commits them atomically via `commit()`.
Obtain a `Batch` via `Fs::batch()`.

All write methods return `Batch&` for fluent chaining:

```cpp
fs = fs.batch()
    .write("a.txt", data1)
    .write("b.txt", data2)
    .commit();
```

### Construction

```cpp
explicit Batch(Fs fs, BatchOptions opts = {});
```

Construct a Batch from an `Fs` snapshot. Prefer `fs.batch()` over direct construction.

### Write staging

```cpp
Batch& write(const std::string& path, const std::vector<uint8_t>& data);
```

Stage raw bytes at `path` with `MODE_BLOB`.
Throws `BatchClosedError` if already committed.

```cpp
Batch& write_with_mode(const std::string& path,
                       const std::vector<uint8_t>& data,
                       uint32_t mode);
```

Stage raw bytes at `path` with an explicit mode.

```cpp
Batch& write_text(const std::string& path, const std::string& text);
```

Stage a UTF-8 string at `path`.

```cpp
Batch& write_from_file(const std::string& path,
                       const std::filesystem::path& local_path,
                       uint32_t mode = MODE_BLOB);
```

Stage a local file from disk at `path`.
Throws `IoError` if the local file cannot be read.

```cpp
Batch& write_symlink(const std::string& path, const std::string& target);
```

Stage a symlink at `path` pointing to `target`.

```cpp
Batch& remove(const std::string& path);
```

Stage `path` for removal.

### Commit

```cpp
Fs commit();
```

Commit all staged changes and return the resulting `Fs`.
After this call the Batch is closed -- further writes throw `BatchClosedError`.

### State

```cpp
bool closed() const;
```

True if `commit()` has been called.

```cpp
size_t pending_writes() const;
```

Number of staged writes.

```cpp
size_t pending_removes() const;
```

Number of staged removes.

```cpp
const std::optional<Fs>& fs() const;
```

The result `Fs` after `commit()`. Only valid after `commit()` has been called.

---

## FsWriter

RAII streaming writer that accumulates data in memory, then writes to the
repo on `close()`.

### Construction

```cpp
FsWriter(Fs fs, std::string path, WriteOptions opts = {});
```

Create a writer for the given `Fs` and path.
Non-copyable; movable.

### Methods

```cpp
FsWriter& write(const std::vector<uint8_t>& data);
```

Append raw bytes to the internal buffer. Returns `*this` for chaining.

```cpp
FsWriter& write(const std::string& text);
```

Append a UTF-8 string. Returns `*this` for chaining.

```cpp
Fs close();
```

Flush and commit. Returns the resulting `Fs`.

```cpp
const Fs& fs() const;
```

The resulting `Fs` (only valid after `close()`).

---

## BatchWriter

RAII streaming writer that accumulates data in memory, then stages to a
`Batch` on `close()`. Called automatically by the destructor if not already
closed.

### Construction

```cpp
BatchWriter(Batch& batch, std::string path, uint32_t mode = MODE_BLOB);
```

Create a writer bound to an existing `Batch`.
Non-copyable; non-movable (holds a reference to `Batch`).

### Methods

```cpp
BatchWriter& write(const std::vector<uint8_t>& data);
```

Append raw bytes. Returns `*this` for chaining.

```cpp
BatchWriter& write(const std::string& text);
```

Append a UTF-8 string. Returns `*this` for chaining.

```cpp
void close();
```

Flush the accumulated buffer and stage the result to the batch.

---

## NoteDict

Access point for git notes. Obtained via `GitStore::notes()`.

```cpp
NoteNamespace operator[](const std::string& ns_name);
```

Get a `NoteNamespace` by name (e.g. `"commits"`, `"reviews"`).

```cpp
NoteNamespace ns(const std::string& ns_name);
```

Get a `NoteNamespace` by name (same as `operator[]`).

```cpp
NoteNamespace commits();
```

Shortcut for `notes["commits"]`.

---

## NoteNamespace

Access git notes under a single namespace (e.g. `refs/notes/commits`).
Notes are keyed by 40-char hex commit hashes or resolvable ref names
(branch/tag). Each note is a UTF-8 string stored as a blob.

Reads support both flat (40-char filename) and 2/38 fanout layout.
Writes always use flat layout.

### Read

```cpp
std::string get(const std::string& hash) const;
```

Get the note text for a commit hash or ref name.
Throws `KeyNotFoundError` if no note exists.
Throws `InvalidHashError` if target is not a valid hash or resolvable ref.

```cpp
std::string get(const Fs& fs) const;
```

Get the note text for an `Fs` snapshot (uses its commit hash).

```cpp
bool has(const std::string& hash) const;
```

Return true if a note exists for this commit hash or ref name.

```cpp
bool has(const Fs& fs) const;
```

Return true if a note exists for this `Fs` snapshot.

```cpp
std::vector<std::string> list() const;
```

Return all hashes that have notes (sorted).

```cpp
size_t size() const;
```

Return the number of notes in this namespace.

```cpp
bool empty() const;
```

Return true if no notes exist.

### Write

```cpp
void set(const std::string& hash, const std::string& text);
```

Set (or overwrite) the note text for a commit hash or ref name.

```cpp
void set(const Fs& fs, const std::string& text);
```

Set the note text for an `Fs` snapshot.

```cpp
void del(const std::string& hash);
```

Delete the note for a commit hash or ref name.
Throws `KeyNotFoundError` if no note exists.

```cpp
void del(const Fs& fs);
```

Delete the note for an `Fs` snapshot.

### Current branch helpers

```cpp
std::string get_for_current_branch() const;
```

Get the note for the current HEAD branch's tip commit.
Throws `NotFoundError` if HEAD is unresolvable or no note exists.

```cpp
void set_for_current_branch(const std::string& text);
```

Set the note for the current HEAD branch's tip commit.
Throws `NotFoundError` if HEAD is unresolvable.

### Batch

```cpp
NotesBatch batch();
```

Create a batch for accumulating multiple note changes.

### Metadata

```cpp
const std::string& namespace_name() const;
```

The namespace name (e.g. `"commits"`).

```cpp
const std::string& ref_name() const;
```

The full ref name (e.g. `"refs/notes/commits"`).

---

## NotesBatch

Accumulates note writes and deletes, then commits them in a single git commit.

### Construction

```cpp
explicit NotesBatch(NoteNamespace ns);
```

Construct from a `NoteNamespace`. Prefer `ns.batch()`.

### Staging

```cpp
void set(const std::string& hash, const std::string& text);
```

Stage a note write for a commit hash or ref name.

```cpp
void set(const Fs& fs, const std::string& text);
```

Stage a note write for an `Fs` snapshot.

```cpp
void del(const std::string& hash);
```

Stage a note deletion for a commit hash or ref name.

```cpp
void del(const Fs& fs);
```

Stage a note deletion for an `Fs` snapshot.

### Commit

```cpp
void commit();
```

Commit all staged changes as a single commit.
Throws `BatchClosedError` if already committed.

```cpp
bool committed() const;
```

True if `commit()` has been called.

---

## Types

### FileType

```cpp
enum class FileType : uint8_t {
    Blob,        // Regular file      (0o100644)
    Executable,  // Executable file   (0o100755)
    Link,        // Symbolic link     (0o120000)
    Tree,        // Directory/subtree (0o040000)
};
```

### Mode constants

```cpp
constexpr uint32_t MODE_BLOB      = 0100644;  // Regular file
constexpr uint32_t MODE_BLOB_EXEC = 0100755;  // Executable file
constexpr uint32_t MODE_LINK      = 0120000;  // Symbolic link
constexpr uint32_t MODE_TREE      = 0040000;  // Directory/subtree
```

### FileType helpers

```cpp
std::optional<FileType> file_type_from_mode(uint32_t mode);
```

Convert a raw git mode to a `FileType`. Returns `nullopt` for unknown modes.

```cpp
uint32_t file_type_to_mode(FileType ft);
```

Return the raw git filemode for a `FileType`.

```cpp
bool file_type_is_file(FileType ft);
```

True if the `FileType` represents a regular or executable file.

```cpp
bool file_type_is_dir(FileType ft);
```

True if the `FileType` represents a directory (tree).

```cpp
bool file_type_is_link(FileType ft);
```

True if the `FileType` represents a symbolic link.

### WalkEntry

```cpp
struct WalkEntry {
    std::string name;  // Basename of the entry
    std::string oid;   // 40-char hex SHA
    uint32_t    mode;  // Raw git filemode

    std::optional<FileType> file_type() const;
};
```

An entry yielded when listing or walking a tree.

### WalkDirEntry

```cpp
struct WalkDirEntry {
    std::string              dirpath;   // Directory path ("" for root)
    std::vector<std::string> dirnames;  // Subdirectory names
    std::vector<WalkEntry>   files;     // Non-directory entries
};
```

An entry yielded by os.walk-style directory traversal.

### StatResult

```cpp
struct StatResult {
    uint32_t    mode;       // Raw git filemode
    FileType    file_type;  // Parsed file type
    uint64_t    size;       // Bytes (blob) or entry count (dir)
    std::string hash;       // 40-char hex SHA
    uint32_t    nlink;      // Hard links (2 + subdirs for dirs)
    uint64_t    mtime;      // Commit timestamp (POSIX epoch)
};
```

Result of a `stat()` call -- single-call getattr for FUSE.

### WriteEntry

```cpp
struct WriteEntry {
    std::optional<std::vector<uint8_t>> data;    // Raw content (for blobs)
    std::optional<std::string>          target;  // Symlink target
    uint32_t                            mode;    // Git file mode

    static WriteEntry from_bytes(std::vector<uint8_t> d);
    static WriteEntry from_text(std::string text);
    static WriteEntry symlink(std::string t);
};
```

Data to be written to the store. Use the static factory methods for convenience.

### FileEntry

```cpp
struct FileEntry {
    std::string                          path;       // Relative path
    FileType                             file_type;  // Type of the file
    std::optional<std::filesystem::path> src;        // Source path on disk

    bool operator<(const FileEntry& o) const;
};
```

Describes a file in a change report.

### ChangeActionKind

```cpp
enum class ChangeActionKind : uint8_t {
    Add,     // A new file was added
    Update,  // An existing file was modified
    Delete,  // A file was removed
};
```

### ChangeAction

```cpp
struct ChangeAction {
    ChangeActionKind kind;
    std::string      path;

    bool operator<(const ChangeAction& o) const;
};
```

A single change action (kind + path).

### ChangeError

```cpp
struct ChangeError {
    std::string path;
    std::string error;
};
```

An error encountered during a change operation.

### ChangeReport

```cpp
struct ChangeReport {
    std::vector<FileEntry>   add;
    std::vector<FileEntry>   update;
    std::vector<FileEntry>   del;
    std::vector<ChangeError> errors;
    std::vector<ChangeError> warnings;

    bool   in_sync() const;  // True if add, update, del are all empty
    size_t total() const;    // add.size() + update.size() + del.size()
    std::vector<ChangeAction> actions() const;  // All actions, sorted by path
};
```

Report summarising the outcome of a sync/copy/import operation.

### Signature

```cpp
struct Signature {
    std::string name  = "vost";
    std::string email = "vost@localhost";
};
```

Author/committer identity used for commits.

### ReflogEntry

```cpp
struct ReflogEntry {
    std::string old_sha;     // Previous 40-char hex commit SHA
    std::string new_sha;     // New 40-char hex commit SHA
    std::string committer;   // Identity string
    uint64_t    timestamp;   // POSIX epoch seconds
    std::string message;     // Reflog message
};
```

A single reflog entry recording a branch movement.

### RefChange

```cpp
struct RefChange {
    std::string                ref_name;    // Full ref name
    std::optional<std::string> old_target;  // Previous SHA (nullopt = created)
    std::optional<std::string> new_target;  // New SHA (nullopt = deleted)
};
```

Describes a reference change during backup/restore.

### MirrorDiff

```cpp
struct MirrorDiff {
    std::vector<RefChange> add;
    std::vector<RefChange> update;
    std::vector<RefChange> del;

    bool   in_sync() const;
    size_t total() const;
};
```

Summary of differences between two repositories.

### CommitInfo

```cpp
struct CommitInfo {
    std::string                commit_hash;
    std::string                message;
    std::optional<uint64_t>    time;
    std::optional<std::string> author_name;
    std::optional<std::string> author_email;
};
```

Information about a single commit returned by `Fs::log()`.

### OpenOptions

```cpp
struct OpenOptions {
    bool                       create = false;  // Create if not found
    std::optional<std::string> branch;          // Default branch name
    std::optional<std::string> author;          // Default author name
    std::optional<std::string> email;           // Default author email
};
```

### WriteOptions

```cpp
struct WriteOptions {
    std::optional<std::string> message;  // Commit message
    std::optional<uint32_t>    mode;     // Git filemode override
};
```

### ApplyOptions

```cpp
struct ApplyOptions {
    std::optional<std::string> message;
    std::optional<std::string> operation;  // Operation prefix for auto messages
};
```

### RemoveOptions

```cpp
struct RemoveOptions {
    bool                       recursive = false;
    bool                       dry_run   = false;
    std::optional<std::string> message;
};
```

### BatchOptions

```cpp
struct BatchOptions {
    std::optional<std::string> message;
    std::optional<std::string> operation;  // Operation prefix for auto messages
};
```

### LogOptions

```cpp
struct LogOptions {
    std::optional<size_t>      limit;          // Max entries to return
    std::optional<size_t>      skip;           // Skip this many matches
    std::optional<std::string> path;           // Only commits changing this path
    std::optional<std::string> match_pattern;  // Glob pattern on commit message
    std::optional<uint64_t>    before;         // Only commits before this epoch
};
```

### CopyInOptions

```cpp
struct CopyInOptions {
    std::optional<std::vector<std::string>> include;   // Glob include patterns
    std::optional<std::vector<std::string>> exclude;   // Glob exclude patterns
    std::optional<std::string>              message;   // Commit message
    bool                                    dry_run   = false;
    bool                                    checksum  = true;  // Skip unchanged
};
```

### CopyOutOptions

```cpp
struct CopyOutOptions {
    std::optional<std::vector<std::string>> include;
    std::optional<std::vector<std::string>> exclude;
};
```

### SyncOptions

```cpp
struct SyncOptions {
    std::optional<std::vector<std::string>> include;
    std::optional<std::vector<std::string>> exclude;
    std::optional<std::string>              message;
    bool                                    dry_run   = false;
    bool                                    checksum  = true;
};
```

### MoveOptions

```cpp
struct MoveOptions {
    bool                       recursive = false;
    bool                       dry_run   = false;
    std::optional<std::string> message;
};
```

### CopyFromRefOptions

```cpp
struct CopyFromRefOptions {
    bool                       delete_extra = false;  // Delete dest files not in source
    bool                       dry_run      = false;
    std::optional<std::string> message;
};
```

### ExcludeFilter

```cpp
class ExcludeFilter {
public:
    ExcludeFilter() = default;

    void add_patterns(const std::vector<std::string>& patterns);
    void load_from_file(const std::filesystem::path& path);
    bool is_excluded(const std::string& rel_path, bool is_dir = false) const;
    bool active() const;
};
```

Gitignore-style exclude filter for copy/sync operations.

`add_patterns()` accepts gitignore-style patterns (e.g. `"*.log"`, `"build/"`).
`load_from_file()` loads patterns from a file (one per line, gitignore syntax).
`is_excluded()` returns true if the relative path matches an exclude pattern.
`active()` returns true if any patterns have been configured.

---

## Free functions

### retry_write

```cpp
template <typename F>
auto retry_write(F&& f) -> decltype(f());
```

Retry a write operation with exponential backoff on `StaleSnapshotError`.
Calls `f()` up to 6 times (1 initial + 5 retries). On each
`StaleSnapshotError`, sleeps `min(10 * 2^attempt, 200)` ms before retrying.
Rethrows the `StaleSnapshotError` after the 5th retry.

```cpp
auto result = vost::retry_write([&]() {
    auto fs = store.branches()["main"];
    return fs.write_text("counter.txt", std::to_string(++n));
});
```

### disk_glob

```cpp
std::vector<std::string> disk_glob(const std::string& pattern,
                                   const std::string& root = ".");
```

Glob pattern matching against the local filesystem.
Matches files using dotfile-aware glob rules. Returns sorted results.

### resolve_credentials

```cpp
std::string resolve_credentials(const std::string& url);
```

Inject credentials into an HTTPS URL if available.
Tries `git credential fill` first (works with any configured helper:
osxkeychain, wincred, libsecret, `gh auth setup-git`, etc.).
Falls back to `gh auth token` for GitHub hosts.
Non-HTTPS URLs and URLs that already contain credentials are returned unchanged.

---

## Error hierarchy

All exceptions derive from `VostError`, which itself derives from `std::runtime_error`.

```
std::runtime_error
  +-- VostError                  Base for all vost exceptions
        +-- NotFoundError        Path not found in repository tree
        +-- IsADirectoryError    Expected a file, found a directory
        +-- NotADirectoryError   Expected a directory, found a file
        +-- PermissionError      Write to a read-only snapshot
        +-- StaleSnapshotError   CAS ref update failed (concurrent modification)
        +-- KeyNotFoundError     Named ref (branch/tag) not found
        +-- KeyExistsError       Named ref already exists (e.g. duplicate tag)
        +-- InvalidPathError     Path contains invalid segments ("", ".", "..")
        +-- InvalidHashError     Not a valid 40-char hex SHA or resolvable ref
        +-- InvalidRefNameError  Ref name violates git naming rules
        +-- BatchClosedError     Batch used after commit()
        +-- GitError             Low-level libgit2 failure
        +-- IoError              Filesystem I/O error
```

### VostError

```cpp
class VostError : public std::runtime_error {
public:
    explicit VostError(const std::string& msg);
};
```

### NotFoundError

```cpp
class NotFoundError : public VostError {
public:
    explicit NotFoundError(const std::string& path);
    const std::string& path() const;
};
```

Thrown when a file or directory path is not found in the repository tree.

### IsADirectoryError

```cpp
class IsADirectoryError : public VostError {
public:
    explicit IsADirectoryError(const std::string& path);
    const std::string& path() const;
};
```

Thrown when an operation expected a file but encountered a directory.

### NotADirectoryError

```cpp
class NotADirectoryError : public VostError {
public:
    explicit NotADirectoryError(const std::string& path);
    const std::string& path() const;
};
```

Thrown when an operation expected a directory but encountered a file.

### PermissionError

```cpp
class PermissionError : public VostError {
public:
    explicit PermissionError(const std::string& msg);
};
```

Thrown when attempting to write to a read-only snapshot (tag or detached commit).

### StaleSnapshotError

```cpp
class StaleSnapshotError : public VostError {
public:
    explicit StaleSnapshotError(const std::string& msg);
};
```

Thrown when a compare-and-swap (CAS) ref update fails because the branch tip
changed between read and write (concurrent modification).
Use `retry_write()` to handle this automatically.

### KeyNotFoundError

```cpp
class KeyNotFoundError : public VostError {
public:
    explicit KeyNotFoundError(const std::string& key);
    const std::string& key() const;
};
```

Thrown when a named key (branch, tag) is not found in a `RefDict`.

### KeyExistsError

```cpp
class KeyExistsError : public VostError {
public:
    explicit KeyExistsError(const std::string& key);
    const std::string& key() const;
};
```

Thrown when creating a ref that already exists (e.g. overwriting a tag via `RefDict::set`).

### InvalidPathError

```cpp
class InvalidPathError : public VostError {
public:
    explicit InvalidPathError(const std::string& msg);
};
```

Thrown when a repository path contains invalid segments (empty, `.`, `..`).

### InvalidHashError

```cpp
class InvalidHashError : public VostError {
public:
    explicit InvalidHashError(const std::string& hash);
};
```

Thrown when a commit hash string is not a valid 40-char lowercase hex SHA
and cannot be resolved as a branch or tag name.

### InvalidRefNameError

```cpp
class InvalidRefNameError : public VostError {
public:
    explicit InvalidRefNameError(const std::string& msg);
};
```

Thrown when a ref name violates git's naming rules.

### BatchClosedError

```cpp
class BatchClosedError : public VostError {
public:
    BatchClosedError();
};
```

Thrown when a `Batch` or `NotesBatch` is used after `commit()` has already been called.

### GitError

```cpp
class GitError : public VostError {
public:
    explicit GitError(const std::string& msg);
};
```

Thrown when a low-level libgit2 operation fails.

### IoError

```cpp
class IoError : public VostError {
public:
    explicit IoError(const std::string& msg);
};
```

Thrown when a filesystem I/O error occurs (e.g. reading a local file for `write_from_file`).

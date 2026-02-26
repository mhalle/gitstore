#pragma once

#include "error.h"
#include "types.h"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <vector>

struct git_oid;

namespace vost {

struct GitStoreInner;
class Batch;

// ---------------------------------------------------------------------------
// Fs — a snapshot of a git-backed filesystem
// ---------------------------------------------------------------------------

/// A read-only or read-write snapshot of a git tree at a specific commit.
///
/// Cheap to copy — holds a shared_ptr<GitStoreInner> plus a few fields.
/// Write operations return a NEW Fs representing the resulting commit.
///
/// Usage:
/// @code
///     auto fs = store.branches()["main"];
///     auto text = fs.read_text("README.md");
///
///     // Reassign to advance to the new commit
///     fs = fs.write_text("note.txt", "hello");
/// @endcode
class Fs {
public:
    // -- Constructors / factory (internal use; use GitStore / RefDict) -------

    /// Construct an Fs from a raw commit hex SHA (internal).
    static Fs from_commit(std::shared_ptr<GitStoreInner> inner,
                          const std::string& commit_oid_hex,
                          std::optional<std::string> ref_name,
                          bool writable);

    /// Construct an empty Fs (no commit, no tree) for a new branch.
    static Fs empty(std::shared_ptr<GitStoreInner> inner,
                    std::string ref_name);

    // -- Identity / metadata ------------------------------------------------

    /// 40-char hex SHA of the commit, or nullopt for empty snapshots.
    std::optional<std::string> commit_hash() const;

    /// 40-char hex SHA of the root tree, or nullopt for empty snapshots.
    std::optional<std::string> tree_hash() const;

    /// Branch or tag name, or nullopt for detached snapshots.
    const std::optional<std::string>& ref_name() const { return ref_name_; }

    /// True for branch snapshots, false for tags and detached commits.
    bool writable() const { return writable_; }

    /// Commit message (trailing newline stripped).
    /// @throws NotFoundError if no commit.
    std::string message() const;

    /// Commit timestamp as POSIX epoch seconds.
    /// @throws NotFoundError if no commit.
    uint64_t time() const;

    /// Commit author name.
    std::string author_name() const;

    /// Commit author email.
    std::string author_email() const;

    /// Change report from the write operation that produced this snapshot.
    const std::optional<ChangeReport>& changes() const { return changes_; }

    // -- Read ---------------------------------------------------------------

    /// Read file contents as bytes.
    /// @throws NotFoundError if path does not exist.
    /// @throws IsADirectoryError if path is a directory.
    std::vector<uint8_t> read(const std::string& path) const;

    /// Read file contents as a UTF-8 string.
    /// @throws NotFoundError if path does not exist.
    std::string read_text(const std::string& path) const;

    /// List entries at `path` (or root if empty).
    /// @throws NotADirectoryError if path is a file.
    std::vector<WalkEntry> ls(const std::string& path = "") const;

    /// Recursively walk all entries under `path`.
    /// Returns (relative_path, WalkEntry) pairs.
    std::vector<std::pair<std::string, WalkEntry>>
    walk(const std::string& path = "") const;

    /// Return true if `path` exists (file, directory, or symlink).
    bool exists(const std::string& path) const;

    /// Return true if `path` is a directory.
    bool is_dir(const std::string& path) const;

    /// Return the FileType of `path`.
    /// @throws NotFoundError if path does not exist.
    FileType file_type(const std::string& path) const;

    /// Return the size in bytes of the object at `path`.
    /// @throws NotFoundError if path does not exist.
    /// @throws IsADirectoryError if path is a directory.
    uint64_t size(const std::string& path) const;

    /// Return the 40-char hex SHA of the object at `path`.
    std::string object_hash(const std::string& path) const;

    /// Read the target of a symlink at `path`.
    std::string readlink(const std::string& path) const;

    /// stat() — single-call getattr for FUSE.
    /// @throws NotFoundError if path does not exist.
    StatResult stat(const std::string& path = "") const;

    /// Alias for ls() — for FUSE readdir.
    std::vector<WalkEntry> listdir(const std::string& path = "") const;

    /// Read with optional byte-range (for FUSE partial reads).
    std::vector<uint8_t> read_range(const std::string& path,
                                    size_t offset,
                                    std::optional<size_t> size = std::nullopt) const;

    /// Read raw blob data by its hex hash, bypassing tree lookup.
    std::vector<uint8_t> read_by_hash(const std::string& hash,
                                      size_t offset = 0,
                                      std::optional<size_t> size = std::nullopt) const;

    /// Glob for matching paths. Returns results sorted.
    std::vector<std::string> glob(const std::string& pattern) const;

    /// Glob for matching paths. Returns results unsorted (faster).
    std::vector<std::string> iglob(const std::string& pattern) const;

    // -- Write --------------------------------------------------------------

    /// Write `data` to `path` and commit, returning a new Fs.
    /// @throws PermissionError if this snapshot is read-only.
    /// @throws StaleSnapshotError if the branch tip has advanced.
    Fs write(const std::string& path,
             const std::vector<uint8_t>& data,
             WriteOptions opts = {}) const;

    /// Write a UTF-8 string to `path` and commit, returning a new Fs.
    Fs write_text(const std::string& path,
                  const std::string& text,
                  WriteOptions opts = {}) const;

    /// Write a symlink at `path` pointing to `target`.
    Fs write_symlink(const std::string& path,
                     const std::string& target,
                     WriteOptions opts = {}) const;

    /// Apply a batch of writes and removes atomically.
    /// `writes` maps path → WriteEntry; `removes` is a list of paths.
    Fs apply(const std::vector<std::pair<std::string, WriteEntry>>& writes,
             const std::vector<std::string>& removes = {},
             ApplyOptions opts = {}) const;

    /// Remove one or more paths and commit.
    Fs remove(const std::vector<std::string>& paths,
              RemoveOptions opts = {}) const;

    // -- Copy ---------------------------------------------------------------

    /// Copy files from local disk `src` into the store at `dest`.
    /// Returns the ChangeReport and a new Fs with the committed changes.
    std::pair<ChangeReport, Fs>
    copy_in(const std::filesystem::path& src,
            const std::string& dest = "",
            CopyInOptions opts = {}) const;

    /// Copy files from the store at `src` to local disk `dest`.
    ChangeReport
    copy_out(const std::string& src,
             const std::filesystem::path& dest,
             CopyOutOptions opts = {}) const;

    /// Sync local disk `src` into the store at `dest` (copy + delete extras).
    std::pair<ChangeReport, Fs>
    sync_in(const std::filesystem::path& src,
            const std::string& dest = "",
            SyncOptions opts = {}) const;

    /// Sync from the store at `src` to local disk `dest` (copy + delete extras).
    ChangeReport
    sync_out(const std::string& src,
             const std::filesystem::path& dest,
             SyncOptions opts = {}) const;

    // -- Batch --------------------------------------------------------------

    /// Return a Batch accumulator for this snapshot.
    Batch batch(BatchOptions opts = {}) const;

    // -- History navigation -------------------------------------------------

    /// Return the parent Fs, or nullopt if this is an initial commit.
    std::optional<Fs> parent() const;

    /// Return an Fs `n` commits behind HEAD on the same branch.
    Fs back(size_t n) const;

    /// Return commit history matching the given filters.
    std::vector<CommitInfo> log(LogOptions opts = {}) const;

    /// Undo the last `n` commits by resetting the branch to its n-th ancestor.
    /// @throws PermissionError if this snapshot is read-only.
    /// @throws StaleSnapshotError if the branch tip has advanced.
    /// @throws NotFoundError if there is insufficient history.
    Fs undo(size_t n = 1) const;

    /// Rename a file or directory from `src` to `dest`.
    /// @throws PermissionError if this snapshot is read-only.
    /// @throws NotFoundError if `src` does not exist.
    /// @throws StaleSnapshotError if the branch tip has advanced.
    Fs rename(const std::string& src, const std::string& dest,
              WriteOptions opts = {}) const;

    /// Redo the last `n` undone commits using the reflog.
    /// @throws PermissionError if this snapshot is read-only.
    /// @throws StaleSnapshotError if the branch tip has advanced.
    /// @throws NotFoundError if no redo history is found.
    Fs redo(size_t n = 1) const;

    // -- Internal -----------------------------------------------------------

    /// Access the shared store inner (used by Batch, RefDict, tree functions).
    std::shared_ptr<GitStoreInner> inner() const { return inner_; }

    /// Raw commit OID hex (internal — may be empty string for empty snapshots).
    const std::string& commit_oid_hex() const { return commit_oid_hex_; }

    /// Raw tree OID hex (internal — may be empty string).
    const std::string& tree_oid_hex() const { return tree_oid_hex_; }

    // -- Internal factory ---------------------------------------------------

    /// Build an Fs from a raw commit oid hex, resolving tree automatically.
    /// Used by commit_changes() and RefDict::get().
    Fs(std::shared_ptr<GitStoreInner> inner,
       std::string commit_oid_hex,
       std::string tree_oid_hex,
       std::optional<std::string> ref_name,
       bool writable,
       std::optional<ChangeReport> changes = std::nullopt);

    friend class Batch;

private:
    std::shared_ptr<GitStoreInner> inner_;
    std::string                    commit_oid_hex_; ///< 40-char hex or empty.
    std::string                    tree_oid_hex_;   ///< 40-char hex or empty.
    std::optional<std::string>     ref_name_;
    bool                           writable_;
    std::optional<ChangeReport>    changes_;

    // -- Helpers ------------------------------------------------------------

    /// Throw PermissionError + return ref_name if writable.
    const std::string& require_writable(const std::string& verb) const;

    /// Throw NotFoundError("no tree in snapshot") if tree is absent.
    const std::string& require_tree() const;

    /// Commit pending writes/removes and return new Fs.
    Fs commit_changes(
        const std::vector<std::pair<std::string, std::pair<std::vector<uint8_t>, uint32_t>>>& writes,
        const std::vector<std::string>& removes,
        const std::string& message,
        std::optional<ChangeReport> report = std::nullopt) const;
};

} // namespace vost

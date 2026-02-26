#pragma once

#include <stdexcept>
#include <string>

namespace vost {

// ---------------------------------------------------------------------------
// Base exception
// ---------------------------------------------------------------------------

/// Base class for all vost exceptions.
class VostError : public std::runtime_error {
public:
    explicit VostError(const std::string& msg) : std::runtime_error(msg) {}
};

// ---------------------------------------------------------------------------
// Specific exception types (mirror rs/src/error.rs)
// ---------------------------------------------------------------------------

/// A file or directory path was not found in the repository tree.
class NotFoundError : public VostError {
public:
    explicit NotFoundError(const std::string& path)
        : VostError("not found: " + path), path_(path) {}
    const std::string& path() const { return path_; }
private:
    std::string path_;
};

/// An operation expected a file but encountered a directory.
class IsADirectoryError : public VostError {
public:
    explicit IsADirectoryError(const std::string& path)
        : VostError("is a directory: " + path), path_(path) {}
    const std::string& path() const { return path_; }
private:
    std::string path_;
};

/// An operation expected a directory but encountered a file (or nothing).
class NotADirectoryError : public VostError {
public:
    explicit NotADirectoryError(const std::string& path)
        : VostError("not a directory: " + path), path_(path) {}
    const std::string& path() const { return path_; }
private:
    std::string path_;
};

/// The operation is not permitted (e.g. writing to a read-only tag snapshot).
class PermissionError : public VostError {
public:
    explicit PermissionError(const std::string& msg)
        : VostError("permission denied: " + msg) {}
};

/// A compare-and-swap (CAS) ref update failed because the branch tip
/// changed between read and write (concurrent modification).
class StaleSnapshotError : public VostError {
public:
    explicit StaleSnapshotError(const std::string& msg)
        : VostError("stale snapshot: " + msg) {}
};

/// A named key (branch, tag) was not found.
class KeyNotFoundError : public VostError {
public:
    explicit KeyNotFoundError(const std::string& key)
        : VostError("key not found: " + key), key_(key) {}
    const std::string& key() const { return key_; }
private:
    std::string key_;
};

/// A named key already exists (e.g. creating a tag that is already present).
class KeyExistsError : public VostError {
public:
    explicit KeyExistsError(const std::string& key)
        : VostError("key already exists: " + key), key_(key) {}
    const std::string& key() const { return key_; }
private:
    std::string key_;
};

/// A repository path contains invalid segments (empty, `.`, `..`, etc.).
class InvalidPathError : public VostError {
public:
    explicit InvalidPathError(const std::string& msg)
        : VostError("invalid path: " + msg) {}
};

/// A commit hash string is not a valid 40-char lowercase hex SHA.
class InvalidHashError : public VostError {
public:
    explicit InvalidHashError(const std::string& hash)
        : VostError("invalid hash: " + hash) {}
};

/// A ref name violates git's naming rules.
class InvalidRefNameError : public VostError {
public:
    explicit InvalidRefNameError(const std::string& msg)
        : VostError("invalid ref name: " + msg) {}
};

/// A Batch was used after it had already been committed.
class BatchClosedError : public VostError {
public:
    BatchClosedError() : VostError("batch already closed") {}
};

/// A low-level libgit2 operation failed.
class GitError : public VostError {
public:
    explicit GitError(const std::string& msg)
        : VostError("git error: " + msg) {}
};

/// A filesystem I/O error occurred.
class IoError : public VostError {
public:
    explicit IoError(const std::string& msg)
        : VostError("io error: " + msg) {}
};

} // namespace vost

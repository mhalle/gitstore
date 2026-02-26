package vost

/**
 * Base exception for vost errors.
 */
open class VostError(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * Raised when a write is attempted on a snapshot whose branch has advanced.
 *
 * Re-fetch the branch via store.branches["name"] and retry, or use
 * retryWrite for automatic retry with backoff.
 */
class StaleSnapshotError(message: String) : VostError(message)

/**
 * Raised when a write is attempted on a read-only snapshot.
 */
class PermissionError(message: String) : VostError(message)

/**
 * Raised when a low-level git tree operation fails.
 */
class GitError(message: String) : VostError(message)

/** Raised when an operation expected a file but found a directory. */
class IsADirectoryError(path: String) : VostError("Is a directory: $path")

/** Raised when a path traversal encounters a non-directory entry. */
class NotADirectoryError(path: String) : VostError("Not a directory: $path")

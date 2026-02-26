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
class ReadOnlyError(message: String) : VostError(message)

/**
 * Raised when a low-level git tree operation fails.
 */
class GitError(message: String) : VostError(message)

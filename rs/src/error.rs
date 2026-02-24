use std::path::PathBuf;

/// All errors produced by gitstore.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A file or directory path was not found in the repository tree.
    #[error("not found: {0}")]
    NotFound(String),

    /// An operation expected a file but encountered a directory.
    #[error("is a directory: {0}")]
    IsADirectory(String),

    /// An operation expected a directory but encountered a file (or nothing).
    #[error("not a directory: {0}")]
    NotADirectory(String),

    /// The operation is not permitted (e.g. writing to a read-only tag snapshot).
    #[error("permission denied: {0}")]
    Permission(String),

    /// A compare-and-swap (CAS) ref update failed because the branch tip
    /// changed between the read and the write (concurrent modification).
    #[error("stale snapshot: {0}")]
    StaleSnapshot(String),

    /// A named key (branch, tag, or note hash) was not found.
    #[error("key not found: {0}")]
    KeyNotFound(String),

    /// A named key already exists (e.g. creating a tag that is already present).
    #[error("key already exists: {0}")]
    KeyExists(String),

    /// A repository path contains invalid segments (empty, `.`, `..`, etc.).
    #[error("invalid path: {0}")]
    InvalidPath(String),

    /// A commit hash string is not a valid 40-char lowercase hex SHA.
    #[error("invalid hash: {0}")]
    InvalidHash(String),

    /// A ref name violates git's naming rules or contains a colon.
    #[error("invalid ref name: {0}")]
    InvalidRefName(String),

    /// A [`Batch`](crate::batch::Batch) was used after it had already been committed.
    #[error("batch already closed")]
    BatchClosed,

    /// A low-level git/gix operation failed.
    #[error("git error: {0}")]
    Git(#[source] Box<dyn std::error::Error + Send + Sync>),

    /// A filesystem I/O error occurred.
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, Error>;

// ---------------------------------------------------------------------------
// Convenience constructors
// ---------------------------------------------------------------------------

impl Error {
    pub fn not_found(path: impl Into<String>) -> Self {
        Self::NotFound(path.into())
    }

    pub fn is_a_directory(path: impl Into<String>) -> Self {
        Self::IsADirectory(path.into())
    }

    pub fn not_a_directory(path: impl Into<String>) -> Self {
        Self::NotADirectory(path.into())
    }

    pub fn permission(msg: impl Into<String>) -> Self {
        Self::Permission(msg.into())
    }

    pub fn stale_snapshot(msg: impl Into<String>) -> Self {
        Self::StaleSnapshot(msg.into())
    }

    pub fn key_not_found(key: impl Into<String>) -> Self {
        Self::KeyNotFound(key.into())
    }

    pub fn key_exists(key: impl Into<String>) -> Self {
        Self::KeyExists(key.into())
    }

    pub fn invalid_path(path: impl Into<String>) -> Self {
        Self::InvalidPath(path.into())
    }

    pub fn invalid_hash(hash: impl Into<String>) -> Self {
        Self::InvalidHash(hash.into())
    }

    pub fn invalid_ref_name(name: impl Into<String>) -> Self {
        Self::InvalidRefName(name.into())
    }

    pub fn git(err: impl std::error::Error + Send + Sync + 'static) -> Self {
        Self::Git(Box::new(err))
    }

    pub fn git_msg(msg: impl Into<String>) -> Self {
        Self::Git(msg.into().into())
    }

    pub fn io(path: impl Into<PathBuf>, err: std::io::Error) -> Self {
        Self::Io(std::io::Error::new(
            err.kind(),
            format!("{}: {}", path.into().display(), err),
        ))
    }
}

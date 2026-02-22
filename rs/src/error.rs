use std::path::PathBuf;

/// All errors produced by gitstore.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("not found: {0}")]
    NotFound(String),

    #[error("is a directory: {0}")]
    IsADirectory(String),

    #[error("not a directory: {0}")]
    NotADirectory(String),

    #[error("permission denied: {0}")]
    Permission(String),

    #[error("stale snapshot: {0}")]
    StaleSnapshot(String),

    #[error("key not found: {0}")]
    KeyNotFound(String),

    #[error("key already exists: {0}")]
    KeyExists(String),

    #[error("invalid path: {0}")]
    InvalidPath(String),

    #[error("invalid ref name: {0}")]
    InvalidRefName(String),

    #[error("batch already closed")]
    BatchClosed,

    #[error("git error: {0}")]
    Git(#[source] Box<dyn std::error::Error + Send + Sync>),

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

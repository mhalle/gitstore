use std::path::Path;

use crate::error::{Error, Result};

/// Acquire an advisory file lock on the repository, execute `f`, then release.
///
/// Creates `<gitdir>/gitstore.lock` using `gix_lock` with a 30-second
/// backoff timeout. Serializes ref mutations across threads and processes.
///
/// # Arguments
/// * `gitdir` - Path to the bare repository directory.
/// * `f` - Closure to execute while the lock is held.
///
/// # Errors
/// Returns an error if the lock cannot be acquired within the timeout.
pub fn with_repo_lock<F, T>(gitdir: &Path, f: F) -> Result<T>
where
    F: FnOnce() -> Result<T>,
{
    let lock_path = gitdir.join("gitstore.lock");

    // Use gix_lock for cross-process file locking
    let _marker = gix_lock::Marker::acquire_to_hold_resource(
        lock_path,
        gix_lock::acquire::Fail::AfterDurationWithBackoff(std::time::Duration::from_secs(30)),
        None,
    )
    .map_err(Error::git)?;

    f()
    // _marker drops here, releasing the lock
}

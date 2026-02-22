use std::path::Path;

use crate::error::{Error, Result};

/// Acquire a file lock on the repository directory, execute `f`, then release.
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

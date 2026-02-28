use std::fs::OpenOptions;
use std::path::Path;

use fs2::FileExt;

use crate::error::{Error, Result};

/// Acquire an advisory file lock on the repository, execute `f`, then release.
///
/// Creates `<gitdir>/vost.lock` using `fs2` with a blocking exclusive lock.
/// Serializes ref mutations across threads and processes.
///
/// # Arguments
/// * `gitdir` - Path to the bare repository directory.
/// * `f` - Closure to execute while the lock is held.
///
/// # Errors
/// Returns an error if the lock cannot be acquired.
pub fn with_repo_lock<F, T>(gitdir: &Path, f: F) -> Result<T>
where
    F: FnOnce() -> Result<T>,
{
    let lock_path = gitdir.join("vost.lock");

    let file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(&lock_path)
        .map_err(|e| Error::io(&lock_path, e))?;

    file.lock_exclusive()
        .map_err(|e| Error::io(&lock_path, e))?;

    let result = f();

    let _ = file.unlock();

    result
    // file drops here, also releasing the lock
}

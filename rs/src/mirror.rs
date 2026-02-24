use std::path::Path;

use crate::error::{Error, Result};
use crate::types::MirrorDiff;

/// Push all local refs to `dest`, creating an exact mirror.
///
/// **Not yet implemented** -- always returns an error. The Python
/// implementation uses dulwich transport helpers to push all refs
/// and delete remote-only refs.
///
/// # Arguments
/// * `_src` - Path to the local bare repository.
/// * `_dest` - Path (or URL) of the remote repository.
pub fn backup(_src: &Path, _dest: &Path) -> Result<MirrorDiff> {
    // Mirror operations are deferred for initial release
    Err(Error::git_msg("mirror backup not yet implemented"))
}

/// Fetch all refs from `src`, overwriting local state in `dest`.
///
/// **Not yet implemented** -- always returns an error. The Python
/// implementation uses dulwich transport helpers to fetch all refs
/// and delete local-only refs.
///
/// # Arguments
/// * `_src` - Path (or URL) of the remote repository.
/// * `_dest` - Path to the local bare repository.
pub fn restore(_src: &Path, _dest: &Path) -> Result<MirrorDiff> {
    Err(Error::git_msg("mirror restore not yet implemented"))
}

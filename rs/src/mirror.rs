use std::path::Path;

use crate::error::{Error, Result};
use crate::types::MirrorDiff;

/// Back up a bare repository to a target path (mirror push).
pub fn backup(_src: &Path, _dest: &Path) -> Result<MirrorDiff> {
    // Mirror operations are deferred for initial release
    Err(Error::git_msg("mirror backup not yet implemented"))
}

/// Restore a bare repository from a backup (mirror fetch).
pub fn restore(_src: &Path, _dest: &Path) -> Result<MirrorDiff> {
    Err(Error::git_msg("mirror restore not yet implemented"))
}

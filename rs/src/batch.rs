use std::path::Path;

use crate::error::{Error, Result};
use crate::fs::{Fs, TreeWrite};
use crate::tree;
use crate::types::{MODE_BLOB, MODE_LINK};

/// Accumulates writes and commits them atomically when consumed.
///
/// `commit(self)` takes ownership, so the compiler enforces that
/// no further writes happen after committing.
pub struct Batch {
    pub(crate) fs: Fs,
    pub(crate) writes: Vec<(String, Option<TreeWrite>)>,
    pub(crate) removes: Vec<String>,
    pub(crate) message: Option<String>,
    pub(crate) operation: Option<String>,
    pub(crate) closed: bool,
}

impl Batch {
    fn require_open(&self) -> Result<()> {
        if self.closed {
            Err(Error::BatchClosed)
        } else {
            Ok(())
        }
    }

    /// Write raw bytes to `path`.
    pub fn write(&mut self, path: &str, data: &[u8]) -> Result<()> {
        self.write_with_mode(path, data, MODE_BLOB)
    }

    /// Write raw bytes to `path` with an explicit file mode.
    pub fn write_with_mode(&mut self, path: &str, data: &[u8], mode: u32) -> Result<()> {
        self.require_open()?;
        let path = crate::paths::normalize_path(path)?;

        let tw = self.fs.with_repo(|repo| {
            let blob_oid = repo.write_blob(data).map_err(Error::git)?;
            Ok(TreeWrite {
                data: data.to_vec(),
                oid: blob_oid.detach(),
                mode,
            })
        })?;

        // Remove from removes if present
        self.removes.retain(|p| p != &path);
        // Remove existing write for same path
        self.writes.retain(|(p, _)| p != &path);
        self.writes.push((path, Some(tw)));
        Ok(())
    }

    /// Write the contents of a disk file to `path`.
    pub fn write_from_file(&mut self, path: &str, src: &Path) -> Result<()> {
        self.require_open()?;
        let data = std::fs::read(src).map_err(|e| Error::io(src, e))?;
        let mode = tree::mode_from_disk(src).unwrap_or(MODE_BLOB);
        self.write_with_mode(path, &data, mode)
    }

    /// Write a symlink at `path`.
    pub fn write_symlink(&mut self, path: &str, target: &str) -> Result<()> {
        self.require_open()?;
        let path = crate::paths::normalize_path(path)?;

        let tw = self.fs.with_repo(|repo| {
            let blob_oid = repo.write_blob(target.as_bytes()).map_err(Error::git)?;
            Ok(TreeWrite {
                data: target.as_bytes().to_vec(),
                oid: blob_oid.detach(),
                mode: MODE_LINK,
            })
        })?;

        self.removes.retain(|p| p != &path);
        self.writes.retain(|(p, _)| p != &path);
        self.writes.push((path, Some(tw)));
        Ok(())
    }

    /// Mark `path` for removal.
    pub fn remove(&mut self, path: &str) -> Result<()> {
        self.require_open()?;
        let path = crate::paths::normalize_path(path)?;

        // Remove from writes if present
        self.writes.retain(|(p, _)| p != &path);

        if !self.removes.contains(&path) {
            self.removes.push(path);
        }
        Ok(())
    }

    /// Commit all accumulated writes. Consumes the `Batch` and returns the new `Fs` snapshot.
    pub fn commit(mut self) -> Result<Fs> {
        self.closed = true;

        if self.writes.is_empty() && self.removes.is_empty() {
            return Ok(self.fs);
        }

        // Merge removes into writes as (path, None)
        let mut all_writes = self.writes;
        for path in self.removes {
            all_writes.push((path, None));
        }

        let message = self.message.unwrap_or_else(|| {
            crate::paths::format_commit_message(
                self.operation.as_deref().unwrap_or("batch"),
                None,
            )
        });

        self.fs.commit_changes(&all_writes, &message)
    }

    /// Returns `true` if `commit()` has already been called.
    pub fn is_closed(&self) -> bool {
        self.closed
    }
}

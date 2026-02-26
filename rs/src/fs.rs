use std::path::Path;
use std::sync::Arc;

use crate::batch::Batch;
use crate::error::{Error, Result};
use crate::lock::with_repo_lock;
use crate::store::GitStoreInner;
use crate::tree;
use crate::types::{
    ChangeReport, CommitInfo, FileEntry, FileType, StatResult, WalkDirEntry, WalkEntry, WriteEntry,
    MODE_BLOB, MODE_LINK, MODE_TREE,
};

// ---------------------------------------------------------------------------
// TreeWrite — pub(crate) unit of work for tree rebuilding
// ---------------------------------------------------------------------------

/// A pending write within a tree rebuild.
#[derive(Debug, Clone)]
pub struct TreeWrite {
    pub data: Vec<u8>,
    pub oid: gix::ObjectId,
    pub mode: u32,
}

// ---------------------------------------------------------------------------
// Option structs
// ---------------------------------------------------------------------------

/// Options for [`Fs::write`], [`Fs::write_text`], [`Fs::write_from_file`],
/// and [`Fs::write_symlink`].
#[derive(Debug, Clone, Default)]
pub struct WriteOptions {
    /// Commit message. Auto-generated if `None`.
    pub message: Option<String>,
    /// Git filemode override (e.g. `MODE_BLOB`, `MODE_LINK`). Auto-detected if `None`.
    pub mode: Option<u32>,
}

/// Options for [`Fs::apply`].
#[derive(Debug, Clone, Default)]
pub struct ApplyOptions {
    /// Commit message. Auto-generated if `None`.
    pub message: Option<String>,
    /// Operation prefix for auto-generated commit messages (e.g. `"import"`).
    pub operation: Option<String>,
}

/// Options for [`Fs::batch`].
#[derive(Debug, Clone, Default)]
pub struct BatchOptions {
    /// Commit message. Auto-generated if `None`.
    pub message: Option<String>,
    /// Operation prefix for auto-generated commit messages (e.g. `"mv"`).
    pub operation: Option<String>,
}

/// Options for [`Fs::copy_in`].
#[derive(Debug, Clone)]
pub struct CopyInOptions {
    /// Glob patterns to include. `None` means include all.
    pub include: Option<Vec<String>>,
    /// Glob patterns to exclude. `None` means exclude nothing.
    pub exclude: Option<Vec<String>>,
    /// Commit message. Auto-generated if `None`.
    pub message: Option<String>,
    /// Preview only; when `true` the returned `Fs` is unchanged but the
    /// `ChangeReport` reflects what *would* happen.
    pub dry_run: bool,
    /// Compare by content hash to skip unchanged files (default `true`).
    pub checksum: bool,
}

impl Default for CopyInOptions {
    fn default() -> Self {
        Self {
            include: None,
            exclude: None,
            message: None,
            dry_run: false,
            checksum: true,
        }
    }
}

/// Options for [`Fs::copy_out`].
#[derive(Debug, Clone, Default)]
pub struct CopyOutOptions {
    /// Glob patterns to include. `None` means include all.
    pub include: Option<Vec<String>>,
    /// Glob patterns to exclude. `None` means exclude nothing.
    pub exclude: Option<Vec<String>>,
}

/// Options for [`Fs::sync_in`] and [`Fs::sync_out`].
#[derive(Debug, Clone)]
pub struct SyncOptions {
    /// Glob patterns to include. `None` means include all.
    pub include: Option<Vec<String>>,
    /// Glob patterns to exclude. `None` means exclude nothing.
    pub exclude: Option<Vec<String>>,
    /// Commit message (only used by `sync_in`). Auto-generated if `None`.
    pub message: Option<String>,
    /// Preview only; when `true` the store is not modified.
    pub dry_run: bool,
    /// Compare by content hash to skip unchanged files (default `true`).
    pub checksum: bool,
}

impl Default for SyncOptions {
    fn default() -> Self {
        Self {
            include: None,
            exclude: None,
            message: None,
            dry_run: false,
            checksum: true,
        }
    }
}

/// Options for [`Fs::remove`].
#[derive(Debug, Clone, Default)]
pub struct RemoveOptions {
    /// Allow removing directories (and their contents).
    pub recursive: bool,
    /// Preview only; when `true` the store is not modified.
    pub dry_run: bool,
    /// Commit message. Auto-generated if `None`.
    pub message: Option<String>,
}

/// Options for [`Fs::remove_from_disk`].
#[derive(Debug, Clone, Default)]
pub struct RemoveFromDiskOptions {
    /// Glob patterns to include. `None` means include all.
    pub include: Option<Vec<String>>,
    /// Glob patterns to exclude. `None` means exclude nothing.
    pub exclude: Option<Vec<String>>,
}

/// Options for [`Fs::move_paths`].
#[derive(Debug, Clone, Default)]
pub struct MoveOptions {
    /// Allow moving directories (and their contents).
    pub recursive: bool,
    /// Preview only; when `true` the store is not modified.
    pub dry_run: bool,
    /// Commit message. Auto-generated if `None`.
    pub message: Option<String>,
}

/// Options for [`Fs::copy_from_ref`].
#[derive(Debug, Clone, Default)]
pub struct CopyFromRefOptions {
    /// Remove dest files under the target that are not in the source.
    pub delete: bool,
    /// Preview only; when `true` the store is not modified but the returned
    /// `Fs` has its `changes` field set.
    pub dry_run: bool,
    /// Commit message. Auto-generated if `None`.
    pub message: Option<String>,
}

/// Options for [`Fs::log`].
#[derive(Debug, Clone, Default)]
pub struct LogOptions {
    /// Maximum number of entries to return.
    pub limit: Option<usize>,
    /// Number of matching entries to skip before collecting results.
    pub skip: Option<usize>,
    /// Only include commits that changed this path.
    pub path: Option<String>,
    /// Only include commits whose message matches this glob pattern (`*`/`?` wildcards).
    pub match_pattern: Option<String>,
    /// Only include commits with timestamp <= this value (seconds since epoch).
    pub before: Option<u64>,
}

// ---------------------------------------------------------------------------
// Fs
// ---------------------------------------------------------------------------

/// An immutable snapshot of a committed tree.
///
/// Read-only when [`writable()`](Fs::writable) returns `false` (tag or
/// detached snapshot). Writable when `true` -- write methods auto-commit and
/// return a **new** `Fs`.
///
/// Cheap to clone (`Arc` internally). No lifetime parameter -- can be stored
/// in structs, returned from functions, sent across threads.
#[derive(Clone, Debug)]
pub struct Fs {
    pub(crate) inner: Arc<GitStoreInner>,
    pub(crate) commit_oid: Option<gix::ObjectId>,
    pub(crate) tree_oid: Option<gix::ObjectId>,
    pub(crate) ref_name: Option<String>,
    pub(crate) writable: bool,
    pub(crate) changes: Option<ChangeReport>,
}

impl Fs {
    /// Helper: lock the repo mutex and call `f` with the repository.
    pub(crate) fn with_repo<F, T>(&self, f: F) -> Result<T>
    where
        F: FnOnce(&gix::Repository) -> Result<T>,
    {
        let repo = self
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        f(&repo)
    }

    /// The tree OID, or error if there is none.
    fn require_tree(&self) -> Result<gix::ObjectId> {
        self.tree_oid
            .ok_or_else(|| Error::not_found("no tree in snapshot"))
    }

    /// The 40-character hex SHA of this snapshot's commit, or `None` for an
    /// empty (no-commit) snapshot.
    pub fn commit_hash(&self) -> Option<String> {
        self.commit_oid.map(|oid| format!("{}", oid))
    }

    /// The 40-character hex SHA of the root tree, or `None` for an empty
    /// (no-tree) snapshot.
    pub fn tree_hash(&self) -> Option<String> {
        self.tree_oid.map(|oid| format!("{}", oid))
    }

    /// The branch or tag name, or `None` for detached snapshots.
    pub fn ref_name(&self) -> Option<&str> {
        self.ref_name.as_deref()
    }

    /// Whether this snapshot can be written to.
    ///
    /// Returns `true` for branch snapshots, `false` for tags and detached commits.
    pub fn writable(&self) -> bool {
        self.writable
    }

    /// Check that this Fs is writable and return the ref name.
    fn require_writable(&self, verb: &str) -> Result<&str> {
        if !self.writable {
            return Err(match &self.ref_name {
                Some(name) => Error::permission(format!("cannot {} read-only snapshot (ref {:?})", verb, name)),
                None => Error::permission(format!("cannot {} read-only snapshot", verb)),
            });
        }
        self.ref_name.as_deref()
            .ok_or_else(|| Error::permission(format!("cannot {} without a branch", verb)))
    }

    /// The commit message, with trailing newline stripped.
    ///
    /// # Errors
    /// Returns an error if there is no commit in this snapshot.
    pub fn message(&self) -> Result<String> {
        let commit_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;
        self.with_repo(|repo| {
            let obj = repo.find_object(commit_oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let commit_ref =
                gix::objs::CommitRef::from_bytes(&data).map_err(Error::git)?;
            let msg = commit_ref.message.to_string();
            Ok(msg.trim_end_matches('\n').to_string())
        })
    }

    /// The commit timestamp as seconds since the Unix epoch.
    ///
    /// # Errors
    /// Returns an error if there is no commit in this snapshot.
    pub fn time(&self) -> Result<u64> {
        let commit_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;
        self.with_repo(|repo| {
            let obj = repo.find_object(commit_oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let commit_ref =
                gix::objs::CommitRef::from_bytes(&data).map_err(Error::git)?;
            Ok(commit_ref.author.time().map(|t| t.seconds as u64).unwrap_or(0))
        })
    }

    /// The commit author's name.
    ///
    /// # Errors
    /// Returns an error if there is no commit in this snapshot.
    pub fn author_name(&self) -> Result<String> {
        let commit_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;
        self.with_repo(|repo| {
            let obj = repo.find_object(commit_oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let commit_ref =
                gix::objs::CommitRef::from_bytes(&data).map_err(Error::git)?;
            Ok(commit_ref.author.name.to_string())
        })
    }

    /// The commit author's email address.
    ///
    /// # Errors
    /// Returns an error if there is no commit in this snapshot.
    pub fn author_email(&self) -> Result<String> {
        let commit_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;
        self.with_repo(|repo| {
            let obj = repo.find_object(commit_oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let commit_ref =
                gix::objs::CommitRef::from_bytes(&data).map_err(Error::git)?;
            Ok(commit_ref.author.email.to_string())
        })
    }

    /// The change report from the operation that produced this snapshot, if any.
    ///
    /// Set after write, copy, sync, remove, and move operations. `None` for
    /// snapshots obtained directly from a branch or tag.
    pub fn changes(&self) -> Option<&ChangeReport> {
        self.changes.as_ref()
    }

    // -- Read ---------------------------------------------------------------

    /// Read file contents as bytes.
    ///
    /// # Arguments
    /// * `path` - File path in the repo.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    /// Returns [`Error::IsADirectory`] if the path is a directory.
    pub fn read(&self, path: &str) -> Result<Vec<u8>> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| tree::read_blob_at_path(repo, tree_oid, path))
    }

    /// Read file contents as a UTF-8 string.
    ///
    /// # Arguments
    /// * `path` - File path in the repo.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    /// Returns an error if the content is not valid UTF-8.
    pub fn read_text(&self, path: &str) -> Result<String> {
        let data = self.read(path)?;
        String::from_utf8(data).map_err(|e| Error::git_msg(format!("invalid UTF-8: {}", e)))
    }

    /// List entry names at `path` (or root if empty).
    ///
    /// Returns a `Vec<String>` of entry names (basenames). Use
    /// [`listdir`](Fs::listdir) if you need OID and mode information.
    ///
    /// # Errors
    /// Returns [`Error::NotADirectory`] if `path` is a file.
    pub fn ls(&self, path: &str) -> Result<Vec<String>> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let entries = tree::list_tree_at_path(repo, tree_oid, path)?;
            Ok(entries.into_iter().map(|e| e.name).collect())
        })
    }

    /// Recursively walk the tree under `path` (os.walk-style).
    ///
    /// Returns a [`WalkDirEntry`] for each directory, containing subdirectory
    /// names and non-directory [`WalkEntry`] items. Pass an empty string to
    /// walk the entire tree.
    ///
    /// # Errors
    /// Returns [`Error::NotADirectory`] if `path` is a file.
    /// Returns [`Error::NotFound`] if `path` does not exist.
    pub fn walk(&self, path: &str) -> Result<Vec<WalkDirEntry>> {
        let tree_oid = self.require_tree()?;
        let path_norm = crate::paths::normalize_path(path)?;

        self.with_repo(|repo| {
            if path_norm.is_empty() {
                tree::walk_tree_dirs(repo, tree_oid)
            } else {
                // Resolve to subtree first
                let entry = tree::entry_at_path(repo, tree_oid, &path_norm)?
                    .ok_or_else(|| Error::not_found(&path_norm))?;
                if entry.mode != MODE_TREE {
                    return Err(Error::not_a_directory(&path_norm));
                }
                let mut entries = tree::walk_tree_dirs(repo, entry.oid)?;
                // Prefix dirpath values
                for e in &mut entries {
                    if e.dirpath.is_empty() {
                        e.dirpath = path_norm.clone();
                    } else {
                        e.dirpath = format!("{}/{}", path_norm, e.dirpath);
                    }
                }
                Ok(entries)
            }
        })
    }

    /// Return `true` if `path` exists (file, directory, or symlink).
    pub fn exists(&self, path: &str) -> Result<bool> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| tree::exists_at_path(repo, tree_oid, path))
    }

    /// Return `true` if `path` is a directory (tree) in the repo.
    ///
    /// Returns `false` if the path does not exist or is a file/symlink.
    pub fn is_dir(&self, path: &str) -> Result<bool> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            match tree::entry_at_path(repo, tree_oid, path)? {
                Some(entry) => Ok(entry.mode == MODE_TREE),
                None => Ok(false),
            }
        })
    }

    /// Return the [`FileType`] of `path`.
    ///
    /// Returns `FileType::Blob`, `FileType::Executable`, `FileType::Link`,
    /// or `FileType::Tree`.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    pub fn file_type(&self, path: &str) -> Result<FileType> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let entry = tree::entry_at_path(repo, tree_oid, path)?
                .ok_or_else(|| Error::not_found(path))?;
            FileType::from_mode(entry.mode)
                .ok_or_else(|| Error::git_msg(format!("unknown mode: {:#o}", entry.mode)))
        })
    }

    /// Return the size in bytes of the object at `path`.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    /// Returns [`Error::IsADirectory`] if the path is a directory.
    pub fn size(&self, path: &str) -> Result<u64> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let entry = tree::entry_at_path(repo, tree_oid, path)?
                .ok_or_else(|| Error::not_found(path))?;
            if entry.mode == MODE_TREE {
                return Err(Error::is_a_directory(path));
            }
            let obj = repo.find_object(entry.oid).map_err(Error::git)?;
            Ok(obj.data.len() as u64)
        })
    }

    /// Return the 40-character hex SHA of the object at `path`.
    ///
    /// For files this is the blob SHA; for directories the tree SHA.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    pub fn object_hash(&self, path: &str) -> Result<String> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let entry = tree::entry_at_path(repo, tree_oid, path)?
                .ok_or_else(|| Error::not_found(path))?;
            Ok(format!("{}", entry.oid))
        })
    }

    /// Read the target of a symlink at `path`.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    /// Returns an error if `path` is not a symlink.
    pub fn readlink(&self, path: &str) -> Result<String> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let entry = tree::entry_at_path(repo, tree_oid, path)?
                .ok_or_else(|| Error::not_found(path))?;
            if entry.mode != MODE_LINK {
                return Err(Error::invalid_path(format!(
                    "{} is not a symlink",
                    path
                )));
            }
            let obj = repo.find_object(entry.oid).map_err(Error::git)?;
            String::from_utf8(obj.data.to_vec())
                .map_err(|e| Error::git_msg(format!("invalid UTF-8 in symlink: {}", e)))
        })
    }

    // -- FUSE-readiness API -------------------------------------------------

    /// Return a [`StatResult`] for `path` (pass `""` for the root).
    ///
    /// Combines file type, size, OID, nlink, and mtime in a single call --
    /// the hot path for FUSE `getattr`.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    pub fn stat(&self, path: &str) -> Result<StatResult> {
        let tree_oid = self.require_tree()?;
        let mtime = self.time()?;

        self.with_repo(|repo| {
            let path_norm = crate::paths::normalize_path(path)?;

            if path_norm.is_empty() {
                // Root directory
                let nlink = 2 + tree::count_subdirs(repo, tree_oid)?;
                return Ok(StatResult {
                    mode: MODE_TREE,
                    file_type: FileType::Tree,
                    size: 0,
                    hash: format!("{}", tree_oid),
                    nlink,
                    mtime,
                });
            }

            let entry = tree::entry_at_path(repo, tree_oid, &path_norm)?
                .ok_or_else(|| Error::not_found(&path_norm))?;
            let ft = FileType::from_mode(entry.mode)
                .ok_or_else(|| Error::git_msg(format!("unknown mode: {:#o}", entry.mode)))?;

            if entry.mode == MODE_TREE {
                let nlink = 2 + tree::count_subdirs(repo, entry.oid)?;
                Ok(StatResult {
                    mode: entry.mode,
                    file_type: ft,
                    size: 0,
                    hash: format!("{}", entry.oid),
                    nlink,
                    mtime,
                })
            } else {
                let obj = repo.find_object(entry.oid).map_err(Error::git)?;
                Ok(StatResult {
                    mode: entry.mode,
                    file_type: ft,
                    size: obj.data.len() as u64,
                    hash: format!("{}", entry.oid),
                    nlink: 1,
                    mtime,
                })
            }
        })
    }

    /// List directory entries with name, OID, and mode.
    ///
    /// Unlike [`ls()`](Fs::ls) which returns just names, `listdir` returns full
    /// [`WalkEntry`] objects. Useful for FUSE `readdir` where you need `d_type`
    /// information alongside names.
    pub fn listdir(&self, path: &str) -> Result<Vec<WalkEntry>> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| tree::list_tree_at_path(repo, tree_oid, path))
    }

    /// Read file contents as bytes with optional offset and size.
    ///
    /// Separate method from [`read()`](Fs::read) so the base `read` signature
    /// stays simple (no breaking change).
    ///
    /// # Arguments
    /// * `path` - File path in the repo.
    /// * `offset` - Byte offset to start reading from.
    /// * `size` - Maximum number of bytes to return (`None` for all remaining).
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the path does not exist.
    /// Returns [`Error::IsADirectory`] if the path is a directory.
    pub fn read_range(&self, path: &str, offset: usize, size: Option<usize>) -> Result<Vec<u8>> {
        let data = self.read(path)?;
        let start = offset.min(data.len());
        let end = match size {
            Some(s) => (start + s).min(data.len()),
            None => data.len(),
        };
        Ok(data[start..end].to_vec())
    }

    /// Read raw blob data by its hex hash, bypassing tree lookup.
    ///
    /// FUSE pattern: `stat()` to cache the hash, then `read_by_hash(hash)`
    /// for subsequent reads without re-walking the tree.
    ///
    /// # Arguments
    /// * `hash` - 40-character hex SHA of the blob.
    /// * `offset` - Byte offset to start reading from.
    /// * `size` - Maximum number of bytes to return (`None` for all remaining).
    ///
    /// # Errors
    /// Returns an error if the hash is invalid or the object is not found.
    pub fn read_by_hash(
        &self,
        hash: &str,
        offset: usize,
        size: Option<usize>,
    ) -> Result<Vec<u8>> {
        let oid = gix::ObjectId::from_hex(hash.as_bytes())
            .map_err(|e| Error::git_msg(format!("invalid hash: {}", e)))?;
        self.with_repo(|repo| {
            let obj = repo.find_object(oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let start = offset.min(data.len());
            let end = match size {
                Some(s) => (start + s).min(data.len()),
                None => data.len(),
            };
            Ok(data[start..end].to_vec())
        })
    }

    // -- Glob ---------------------------------------------------------------

    /// Expand a glob pattern against the repo tree.
    ///
    /// Supports `*`, `?`, and `**`. `*` and `?` do not match a leading `.`
    /// unless the pattern segment itself starts with `.`. `**` matches zero or
    /// more directory levels, skipping directories whose names start with `.`.
    ///
    /// Returns a sorted, deduplicated list of matching paths.
    pub fn glob(&self, pattern: &str) -> Result<Vec<String>> {
        let mut paths = self.iglob(pattern)?;
        paths.sort();
        Ok(paths)
    }

    /// Expand a glob pattern against the repo tree (unsorted).
    ///
    /// Like [`glob()`](Fs::glob) but skips the final sort, which is cheaper
    /// when you only need to iterate once.
    pub fn iglob(&self, pattern: &str) -> Result<Vec<String>> {
        let tree_oid = self.require_tree()?;
        let segments: Vec<&str> = pattern.split('/').collect();

        self.with_repo(|repo| {
            let mut results = Vec::new();
            iglob_recursive(repo, tree_oid, &segments, "", &mut results)?;
            Ok(results)
        })
    }

    // -- Write --------------------------------------------------------------

    /// Write `data` to `path` and commit, returning a new [`Fs`].
    ///
    /// # Arguments
    /// * `path` - Destination path in the repo.
    /// * `data` - Raw bytes to write.
    /// * `opts` - [`WriteOptions`] for commit message and mode override.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    /// Returns [`Error::StaleSnapshot`] if the branch has advanced since this snapshot.
    pub fn write(
        &self,
        path: &str,
        data: &[u8],
        opts: WriteOptions,
    ) -> Result<Fs> {
        let path = crate::paths::normalize_path(path)?;
        let mode = opts.mode.unwrap_or(MODE_BLOB);
        let message = opts
            .message
            .unwrap_or_else(|| crate::paths::format_commit_message("write", Some(&path)));

        let tw = self.with_repo(|repo| {
            let blob_oid = repo.write_blob(data).map_err(Error::git)?;
            Ok(TreeWrite {
                data: data.to_vec(),
                oid: blob_oid.detach(),
                mode,
            })
        })?;

        let writes = vec![(path, Some(tw))];
        self.commit_changes(&writes, &message)
    }

    /// Write `text` to `path` and commit, returning a new [`Fs`].
    ///
    /// Convenience wrapper around [`write()`](Fs::write) that encodes the
    /// string as UTF-8.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    /// Returns [`Error::StaleSnapshot`] if the branch has advanced since this snapshot.
    pub fn write_text(
        &self,
        path: &str,
        text: &str,
        opts: WriteOptions,
    ) -> Result<Fs> {
        self.write(path, text.as_bytes(), opts)
    }

    /// Write a local file into the repo and commit, returning a new [`Fs`].
    ///
    /// Executable permission is auto-detected from disk unless
    /// `opts.mode` is set.
    ///
    /// # Arguments
    /// * `path` - Destination path in the repo.
    /// * `src` - Path to the local file on disk.
    /// * `opts` - [`WriteOptions`] for commit message and mode override.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    /// Returns [`Error::StaleSnapshot`] if the branch has advanced since this snapshot.
    /// Returns an I/O error if the local file cannot be read.
    pub fn write_from_file(
        &self,
        path: &str,
        src: &Path,
        opts: WriteOptions,
    ) -> Result<Fs> {
        let data = std::fs::read(src).map_err(|e| Error::io(src, e))?;
        let mode = opts
            .mode
            .unwrap_or_else(|| tree::mode_from_disk(src).unwrap_or(MODE_BLOB));
        let opts = WriteOptions {
            mode: Some(mode),
            ..opts
        };
        self.write(path, &data, opts)
    }

    /// Create a symbolic link entry and commit, returning a new [`Fs`].
    ///
    /// # Arguments
    /// * `path` - Symlink path in the repo.
    /// * `target` - The symlink target string.
    /// * `opts` - [`WriteOptions`] (the `mode` field is ignored; symlinks
    ///   always use `MODE_LINK`).
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    /// Returns [`Error::StaleSnapshot`] if the branch has advanced since this snapshot.
    pub fn write_symlink(
        &self,
        path: &str,
        target: &str,
        opts: WriteOptions,
    ) -> Result<Fs> {
        let opts = WriteOptions {
            mode: Some(MODE_LINK),
            ..opts
        };
        self.write(path, target.as_bytes(), opts)
    }

    /// Apply multiple writes and removes in a single atomic commit.
    ///
    /// `entries` maps repo paths to [`WriteEntry`] values describing the
    /// content and mode. `removes` lists repo paths to delete.
    ///
    /// Returns the new [`Fs`] snapshot with the changes committed.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    /// Returns [`Error::StaleSnapshot`] if the branch has advanced since this snapshot.
    pub fn apply(
        &self,
        entries: &[(&str, WriteEntry)],
        removes: &[&str],
        opts: ApplyOptions,
    ) -> Result<Fs> {
        let mut writes = Vec::new();
        for (path, entry) in entries {
            entry.validate()?;
            let path = crate::paths::normalize_path(path)?;
            let (data, mode) = if entry.mode == MODE_LINK {
                (
                    entry.target.as_ref().unwrap().as_bytes().to_vec(),
                    MODE_LINK,
                )
            } else {
                (entry.data.as_ref().unwrap().clone(), entry.mode)
            };
            let tw = self.with_repo(|repo| {
                let blob_oid = repo.write_blob(&data).map_err(Error::git)?;
                Ok(TreeWrite {
                    data,
                    oid: blob_oid.detach(),
                    mode,
                })
            })?;
            writes.push((path, Some(tw)));
        }

        // Append removes
        for path in removes {
            let path = crate::paths::normalize_path(path)?;
            writes.push((path, None));
        }

        let op = opts.operation.as_deref().unwrap_or("apply");
        let message = opts
            .message
            .unwrap_or_else(|| crate::paths::format_commit_message(op, None));
        self.commit_changes(&writes, &message)
    }

    /// Return a [`Batch`] for accumulating multiple writes in one commit.
    ///
    /// Call [`Batch::commit()`] (or use it as a scope guard) to flush
    /// accumulated changes atomically.
    ///
    /// # Errors
    /// The batch itself is infallible; errors surface at commit time.
    pub fn batch(&self, opts: BatchOptions) -> Batch {
        Batch {
            fs: self.clone(),
            writes: vec![],
            removes: vec![],
            message: opts.message,
            operation: opts.operation,
            closed: false,
        }
    }

    /// Return a buffered [`FsWriter`](crate::fileobj::FsWriter) that commits
    /// on close.
    ///
    /// The writer implements [`std::io::Write`], so you can use `write_all` etc.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    pub fn writer(&self, path: &str) -> Result<crate::fileobj::FsWriter> {
        self.require_writable("write to")?;
        let normalized = crate::paths::normalize_path(path)?;
        Ok(crate::fileobj::FsWriter::new(self.clone(), normalized))
    }

    // -- Copy / sync --------------------------------------------------------

    /// Copy local files from disk into the repo.
    ///
    /// Returns `(report, new_fs)` where `report` describes what changed and
    /// `new_fs` is the committed snapshot (or an unchanged clone when
    /// `dry_run` is set).
    ///
    /// # Arguments
    /// * `src` - Local directory or file to copy from.
    /// * `dest` - Destination path in the repo.
    /// * `opts` - [`CopyInOptions`] for filtering, dry-run, and checksum.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    pub fn copy_in(
        &self,
        src: &Path,
        dest: &str,
        opts: CopyInOptions,
    ) -> Result<(ChangeReport, Fs)> {
        let tree_oid = self.require_tree()?;
        let checksum = opts.checksum;
        let (writes, report) = self.with_repo(|repo| {
            let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            crate::copy::copy_in(repo, tree_oid, src, dest, inc.as_deref(), exc.as_deref(), checksum)
        })?;
        if opts.dry_run {
            return Ok((report, self.clone()));
        }
        let new_fs = if !writes.is_empty() {
            let tw_writes: Vec<(String, Option<TreeWrite>)> = writes
                .into_iter()
                .map(|(p, tw)| (p, Some(tw)))
                .collect();
            let msg = opts.message.unwrap_or_else(|| crate::paths::format_commit_message("copy_in", None));
            self.commit_changes(&tw_writes, &msg)?
        } else {
            self.clone()
        };
        Ok((report, new_fs))
    }

    /// Copy repo files to local disk.
    ///
    /// Returns a [`ChangeReport`] describing what was written.
    ///
    /// # Arguments
    /// * `src` - Repo path to copy from.
    /// * `dest` - Local destination directory.
    /// * `opts` - [`CopyOutOptions`] for include/exclude filtering.
    pub fn copy_out(
        &self,
        src: &str,
        dest: &Path,
        opts: CopyOutOptions,
    ) -> Result<ChangeReport> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            crate::copy::copy_out(repo, tree_oid, src, dest, inc.as_deref(), exc.as_deref())
        })
    }

    /// Make `dest` in the repo identical to the local `src` directory.
    ///
    /// Unlike [`copy_in()`](Fs::copy_in), this also deletes files in the
    /// destination that are not present on disk, making the two trees mirror
    /// each other exactly.
    ///
    /// Returns `(report, new_fs)`.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    pub fn sync_in(
        &self,
        src: &Path,
        dest: &str,
        opts: SyncOptions,
    ) -> Result<(ChangeReport, Fs)> {
        let tree_oid = self.require_tree()?;
        let checksum = opts.checksum;
        let (writes, report) = self.with_repo(|repo| {
            let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            crate::copy::sync_in(repo, tree_oid, src, dest, inc.as_deref(), exc.as_deref(), checksum)
        })?;
        if opts.dry_run {
            return Ok((report, self.clone()));
        }
        let new_fs = if !writes.is_empty() {
            let msg = opts.message.unwrap_or_else(|| crate::paths::format_commit_message("sync_in", None));
            self.commit_changes(&writes, &msg)?
        } else {
            self.clone()
        };
        Ok((report, new_fs))
    }

    /// Make the local `dest` directory identical to `src` in the repo.
    ///
    /// Deletes extra local files and prunes empty directories so the local
    /// tree mirrors the repo subtree exactly.
    ///
    /// Returns a [`ChangeReport`] describing what was written and deleted.
    pub fn sync_out(
        &self,
        src: &str,
        dest: &Path,
        opts: SyncOptions,
    ) -> Result<ChangeReport> {
        let tree_oid = self.require_tree()?;
        let checksum = opts.checksum;
        self.with_repo(|repo| {
            let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            crate::copy::sync_out(repo, tree_oid, src, dest, inc.as_deref(), exc.as_deref(), checksum)
        })
    }

    /// Remove files from local disk that match the include/exclude filters.
    ///
    /// Returns a [`ChangeReport`] describing what was deleted.
    pub fn remove_from_disk(
        &self,
        path: &Path,
        opts: RemoveFromDiskOptions,
    ) -> Result<ChangeReport> {
        let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
        let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
        crate::copy::remove_from_disk(path, inc.as_deref(), exc.as_deref())
    }

    /// Remove files from the repo and commit, returning a new [`Fs`].
    ///
    /// Sources must be literal paths; use [`glob()`](Fs::glob) to expand
    /// patterns before calling.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    /// Returns [`Error::NotFound`] if a source path does not exist.
    /// Returns [`Error::IsADirectory`] if a source is a directory and
    /// `opts.recursive` is `false`.
    pub fn remove(
        &self,
        sources: &[&str],
        opts: RemoveOptions,
    ) -> Result<Fs> {
        let tree_oid = self.require_tree()?;
        let mut writes: Vec<(String, Option<TreeWrite>)> = Vec::new();
        let mut report = ChangeReport::new();

        self.with_repo(|repo| {
            for src in sources {
                let path = crate::paths::normalize_path(src)?;
                let entry = tree::entry_at_path(repo, tree_oid, &path)?
                    .ok_or_else(|| Error::not_found(&path))?;

                if entry.mode == MODE_TREE {
                    if !opts.recursive {
                        return Err(Error::is_a_directory(&path));
                    }
                    // Walk subtree and collect all leaf paths for removal
                    let sub_entries = tree::walk_tree(repo, entry.oid)?;
                    for (rel_path, we) in &sub_entries {
                        let full_path = format!("{}/{}", path, rel_path);
                        let ft = FileType::from_mode(we.mode).unwrap_or(FileType::Blob);
                        if !opts.dry_run {
                            writes.push((full_path.clone(), None));
                        }
                        report.delete.push(FileEntry::new(&full_path, ft));
                    }
                } else {
                    let ft = FileType::from_mode(entry.mode).unwrap_or(FileType::Blob);
                    if !opts.dry_run {
                        writes.push((path.clone(), None));
                    }
                    report.delete.push(FileEntry::new(&path, ft));
                }
            }
            Ok(())
        })?;

        if opts.dry_run || writes.is_empty() {
            let mut fs = self.clone();
            fs.changes = Some(report);
            return Ok(fs);
        }

        let msg = opts.message.unwrap_or_else(|| {
            crate::paths::format_commit_message("remove", None)
        });
        let mut new_fs = self.commit_changes(&writes, &msg)?;
        new_fs.changes = Some(report);
        Ok(new_fs)
    }

    /// Rename a single path within the repo and commit, returning a new [`Fs`].
    ///
    /// # Arguments
    /// * `src` - Current path in the repo.
    /// * `dest` - New path in the repo.
    /// * `opts` - [`WriteOptions`] for commit message (mode is ignored).
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    pub fn rename(
        &self,
        src: &str,
        dest: &str,
        opts: WriteOptions,
    ) -> Result<Fs> {
        let tree_oid = self.require_tree()?;
        let writes = self.with_repo(|repo| crate::copy::rename(repo, tree_oid, src, dest))?;
        if !writes.is_empty() {
            let msg = opts.message.unwrap_or_else(|| {
                crate::paths::format_commit_message("rename", Some(&format!("{} -> {}", src, dest)))
            });
            self.commit_changes(&writes, &msg)
        } else {
            Ok(self.clone())
        }
    }

    /// Move or rename files within the repo, following POSIX `mv` semantics.
    ///
    /// - Single source to a non-existing destination: rename.
    /// - Multiple sources: destination must be an existing directory.
    ///
    /// Returns the new [`Fs`] snapshot.
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if this snapshot is read-only.
    /// Returns [`Error::NotFound`] if a source does not exist.
    /// Returns [`Error::NotADirectory`] if multiple sources are given but
    /// `dest` is not an existing directory.
    /// Returns [`Error::IsADirectory`] if a source is a directory and
    /// `opts.recursive` is `false`.
    pub fn move_paths(
        &self,
        sources: &[&str],
        dest: &str,
        opts: MoveOptions,
    ) -> Result<Fs> {
        let tree_oid = self.require_tree()?;
        let dest_norm = crate::paths::normalize_path(dest)?;

        // Check if dest is an existing directory
        let dest_is_dir = self.with_repo(|repo| {
            match tree::entry_at_path(repo, tree_oid, &dest_norm)? {
                Some(entry) => Ok(entry.mode == MODE_TREE),
                None => Ok(false),
            }
        })?;

        if sources.len() > 1 && !dest_is_dir {
            return Err(Error::not_a_directory(&dest_norm));
        }

        let mut all_writes: Vec<(String, Option<TreeWrite>)> = Vec::new();

        self.with_repo(|repo| {
            for src in sources {
                let src_norm = crate::paths::normalize_path(src)?;
                let entry = tree::entry_at_path(repo, tree_oid, &src_norm)?
                    .ok_or_else(|| Error::not_found(&src_norm))?;

                // Determine final destination path
                let final_dest = if dest_is_dir {
                    // Move into directory: use source basename
                    let basename = src_norm.rsplit('/').next().unwrap_or(&src_norm);
                    format!("{}/{}", dest_norm, basename)
                } else {
                    dest_norm.clone()
                };

                if entry.mode == MODE_TREE {
                    if !opts.recursive {
                        return Err(Error::is_a_directory(&src_norm));
                    }
                    let sub_entries = tree::walk_tree(repo, entry.oid)?;
                    for (rel_path, we) in &sub_entries {
                        let old_path = format!("{}/{}", src_norm, rel_path);
                        let new_path = format!("{}/{}", final_dest, rel_path);
                        let obj = repo.find_object(we.oid).map_err(Error::git)?;
                        all_writes.push((old_path, None));
                        all_writes.push((
                            new_path,
                            Some(TreeWrite {
                                data: obj.data.to_vec(),
                                oid: we.oid,
                                mode: we.mode,
                            }),
                        ));
                    }
                } else {
                    let obj = repo.find_object(entry.oid).map_err(Error::git)?;
                    all_writes.push((src_norm, None));
                    all_writes.push((
                        final_dest,
                        Some(TreeWrite {
                            data: obj.data.to_vec(),
                            oid: entry.oid,
                            mode: entry.mode,
                        }),
                    ));
                }
            }
            Ok(())
        })?;

        if opts.dry_run || all_writes.is_empty() {
            return Ok(self.clone());
        }

        let msg = opts.message.unwrap_or_else(|| {
            crate::paths::format_commit_message("move", None)
        });
        self.commit_changes(&all_writes, &msg)
    }

    /// Copy files from another branch, tag, or detached commit into this
    /// branch in a single atomic commit.
    ///
    /// Follows the same rsync trailing-slash conventions as
    /// [`copy_in`](Fs::copy_in)/[`copy_out`](Fs::copy_out):
    ///
    /// - `"config"` → directory mode — copies `config/` *as* `config/` under dest.
    /// - `"config/"` → contents mode — pours the *contents* of `config/` into dest.
    /// - `"file.txt"` → file mode — copies the single file into dest.
    /// - `""` or `"/"` → root contents mode — copies everything.
    ///
    /// Since both snapshots share the same object store, blobs are referenced
    /// by OID — no data is read into memory regardless of file size.
    ///
    /// # Arguments
    /// * `source` - Any `Fs` (branch, tag, detached). Read-only; not modified.
    /// * `sources` - Source path(s) in *source*. Follows rsync conventions.
    /// * `dest` - Destination path in this branch. `""` = root.
    /// * `opts` - [`CopyFromRefOptions`] for delete, dry-run, and message.
    ///
    /// # Errors
    /// Returns an error if `source` belongs to a different repo.
    /// Returns [`Error::NotFound`] if a source path does not exist.
    /// Returns [`Error::Permission`] if this `Fs` is read-only.
    pub fn copy_from_ref(
        &self,
        source: &Fs,
        sources: &[&str],
        dest: &str,
        opts: CopyFromRefOptions,
    ) -> Result<Fs> {
        self.require_writable("write to")?;

        // Validate same repo
        let same = Arc::ptr_eq(&self.inner, &source.inner) || {
            let self_canon = std::fs::canonicalize(&self.inner.path).ok();
            let src_canon = std::fs::canonicalize(&source.inner.path).ok();
            self_canon.is_some() && self_canon == src_canon
        };
        if !same {
            return Err(Error::invalid_path(
                "source must belong to the same repo as self".to_string(),
            ));
        }

        let dest_norm = crate::paths::normalize_path(dest)?;
        let src_tree = source.require_tree()?;
        let dest_tree = self.require_tree()?;

        // Resolve sources and enumerate files → BTreeMap<dest_path, (oid, mode)>
        let mut src_mapped = std::collections::BTreeMap::<String, (gix::ObjectId, u32)>::new();
        // Track dest prefixes for walking the dest tree
        let mut dest_prefixes = std::collections::BTreeSet::<String>::new();

        self.with_repo(|repo| {
            for &src in sources {
                let contents_mode = src.ends_with('/');
                let stripped = src.trim_end_matches('/');
                let normalized = if stripped.is_empty() {
                    String::new()
                } else {
                    crate::paths::normalize_path(stripped)?
                };

                // Determine mode: file, dir, or contents
                enum SrcMode { File(gix::ObjectId, u32), Dir, Contents }

                let mode = if contents_mode {
                    // Trailing slash or root
                    if !normalized.is_empty() {
                        let entry = tree::entry_at_path(repo, src_tree, &normalized)?;
                        match entry {
                            Some(e) if e.mode == MODE_TREE => {},
                            Some(_) => return Err(Error::not_a_directory(
                                format!("Not a directory in repo: {}", normalized),
                            )),
                            None => return Err(Error::not_found(
                                format!("File not found in repo: {}", normalized),
                            )),
                        }
                    }
                    SrcMode::Contents
                } else if normalized.is_empty() {
                    SrcMode::Contents
                } else {
                    let entry = tree::entry_at_path(repo, src_tree, &normalized)?;
                    match entry {
                        Some(e) if e.mode == MODE_TREE => SrcMode::Dir,
                        Some(e) => SrcMode::File(e.oid, e.mode),
                        None => return Err(Error::not_found(
                            format!("File not found in repo: {}", normalized),
                        )),
                    }
                };

                match mode {
                    SrcMode::File(oid, fmode) => {
                        let name = normalized.rsplit('/').next().unwrap_or(&normalized);
                        let dest_file = if dest_norm.is_empty() {
                            name.to_string()
                        } else {
                            format!("{}/{}", dest_norm, name)
                        };
                        src_mapped.insert(dest_file, (oid, fmode));
                        dest_prefixes.insert(dest_norm.clone());
                    }
                    SrcMode::Dir => {
                        let dirname = normalized.rsplit('/').next().unwrap_or(&normalized);
                        let target = if dest_norm.is_empty() {
                            dirname.to_string()
                        } else {
                            format!("{}/{}", dest_norm, dirname)
                        };
                        let entries = walk_subtree(repo, src_tree, &normalized)?;
                        for (rel, (oid, fmode)) in entries {
                            let dest_file = format!("{}/{}", target, rel);
                            src_mapped.insert(dest_file, (oid, fmode));
                        }
                        dest_prefixes.insert(target);
                    }
                    SrcMode::Contents => {
                        let entries = walk_subtree(repo, src_tree, &normalized)?;
                        for (rel, (oid, fmode)) in entries {
                            let dest_file = if dest_norm.is_empty() {
                                rel
                            } else {
                                format!("{}/{}", dest_norm, rel)
                            };
                            src_mapped.insert(dest_file, (oid, fmode));
                        }
                        dest_prefixes.insert(dest_norm.clone());
                    }
                }
            }
            Ok(())
        })?;

        // Walk dest subtree(s)
        let dest_files = self.with_repo(|repo| {
            let mut dest_files = std::collections::BTreeMap::<String, (gix::ObjectId, u32)>::new();
            for dp in &dest_prefixes {
                let walked = walk_subtree(repo, dest_tree, dp)?;
                for (rel, entry) in walked {
                    let full = if dp.is_empty() {
                        rel
                    } else {
                        format!("{}/{}", dp, rel)
                    };
                    dest_files.insert(full, entry);
                }
            }
            Ok(dest_files)
        })?;

        // Build writes and removes
        let mut writes: Vec<(String, Option<TreeWrite>)> = Vec::new();
        let mut report = ChangeReport::new();

        for (dest_path, (src_oid, src_mode)) in &src_mapped {
            let dest_entry = dest_files.get(dest_path);
            match dest_entry {
                None => {
                    let ft = FileType::from_mode(*src_mode).unwrap_or(FileType::Blob);
                    report.add.push(FileEntry::new(dest_path, ft));
                    writes.push((
                        dest_path.clone(),
                        Some(TreeWrite {
                            data: vec![],
                            oid: *src_oid,
                            mode: *src_mode,
                        }),
                    ));
                }
                Some((d_oid, d_mode)) if d_oid != src_oid || d_mode != src_mode => {
                    let ft = FileType::from_mode(*src_mode).unwrap_or(FileType::Blob);
                    report.update.push(FileEntry::new(dest_path, ft));
                    writes.push((
                        dest_path.clone(),
                        Some(TreeWrite {
                            data: vec![],
                            oid: *src_oid,
                            mode: *src_mode,
                        }),
                    ));
                }
                _ => {} // identical
            }
        }

        if opts.delete {
            for (full, (_, mode)) in &dest_files {
                if !src_mapped.contains_key(full) {
                    let ft = FileType::from_mode(*mode).unwrap_or(FileType::Blob);
                    report.delete.push(FileEntry::new(full, ft));
                    writes.push((full.clone(), None));
                }
            }
        }

        if opts.dry_run || writes.is_empty() {
            let mut fs = self.clone();
            fs.changes = Some(report);
            return Ok(fs);
        }

        let msg = opts.message.unwrap_or_else(|| {
            crate::paths::format_commit_message("cp", None)
        });
        let mut new_fs = self.commit_changes(&writes, &msg)?;
        new_fs.changes = Some(report);
        Ok(new_fs)
    }

    // -- History ------------------------------------------------------------

    /// The parent snapshot, or `None` for the initial commit.
    pub fn parent(&self) -> Result<Option<Fs>> {
        let commit_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;

        self.with_repo(|repo| {
            let obj = repo.find_object(commit_oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let commit_ref =
                gix::objs::CommitRef::from_bytes(&data).map_err(Error::git)?;
            let parent_oid = commit_ref.parents().next();
            match parent_oid {
                Some(pid) => {
                    let parent_id: gix::ObjectId = pid;
                    // Drop the repo lock before calling from_commit (which re-locks)
                    Ok(Some(parent_id))
                }
                None => Ok(None),
            }
        })?
        .map(|parent_id| {
            Fs::from_commit(Arc::clone(&self.inner), parent_id, self.ref_name.clone(), Some(self.writable))
        })
        .transpose()
    }

    /// Return the `Fs` at the *n*-th ancestor commit.
    ///
    /// # Errors
    /// Returns an error if the history is shorter than `n` commits.
    pub fn back(&self, n: usize) -> Result<Fs> {
        let mut current = self.clone();
        for _ in 0..n {
            match current.parent()? {
                Some(parent) => current = parent,
                None => {
                    return Err(Error::not_found("not enough history"));
                }
            }
        }
        Ok(current)
    }

    /// Move the branch pointer back `n` commits (soft reset).
    ///
    /// Walks back through parent commits and updates the branch ref.
    /// A reflog entry is written automatically so the change can be
    /// reversed with [`redo()`](Fs::redo).
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if called on a read-only snapshot (tag).
    /// Returns [`Error::StaleSnapshot`] if the branch has advanced since this snapshot.
    /// Returns an error if there are fewer than `n` commits in the history.
    pub fn undo(&self, n: usize) -> Result<Fs> {
        let branch = self.require_writable("undo")?;

        // Walk back n parents
        let mut target = self.clone();
        for _ in 0..n {
            target = target
                .parent()?
                .ok_or_else(|| Error::not_found("no parent commit to undo to"))?;
        }

        let target_oid = target
            .commit_oid
            .ok_or_else(|| Error::not_found("target has no commit"))?;

        let refname = format!("refs/heads/{}", branch);
        let inner = Arc::clone(&self.inner);

        let current_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;

        use gix::refs::transaction::PreviousValue;
        with_repo_lock(&inner.path, || {
            let repo = inner
                .repo
                .lock()
                .map_err(|e| Error::git_msg(e.to_string()))?;

            // Stale snapshot check
            let current_ref = repo
                .find_reference(refname.as_str())
                .map_err(|_| Error::not_found(format!("branch '{}' not found", branch)))?;
            let actual_oid = current_ref.id().detach();
            if actual_oid != current_oid {
                return Err(Error::stale_snapshot(format!(
                    "branch '{}' has moved: expected {}, found {}",
                    branch, current_oid, actual_oid
                )));
            }

            repo.reference(
                refname.as_str(),
                target_oid,
                PreviousValue::Any,
                "undo: move back",
            )
            .map_err(Error::git)?;

            // Write reflog entry for undo
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default();
            let _ = crate::reflog::write_reflog_entry(
                &inner.path,
                &refname,
                &crate::types::ReflogEntry {
                    old_sha: format!("{}", current_oid),
                    new_sha: format!("{}", target_oid),
                    committer: format!(
                        "{} <{}>",
                        inner.signature.name, inner.signature.email
                    ),
                    timestamp: now.as_secs(),
                    message: "undo: move back".to_string(),
                },
            );

            Ok(())
        })?;

        Ok(target)
    }

    /// Move the branch pointer forward `n` steps using the reflog.
    ///
    /// Reads the reflog to find where the branch was before the last `n`
    /// movements, resurrecting "orphaned" commits after an [`undo()`](Fs::undo).
    ///
    /// # Errors
    /// Returns [`Error::Permission`] if called on a read-only snapshot (tag).
    /// Returns [`Error::StaleSnapshot`] if the branch has advanced since this snapshot.
    /// Returns an error if not enough redo history exists.
    pub fn redo(&self, n: usize) -> Result<Fs> {
        let branch = self.require_writable("redo")?;
        let refname = format!("refs/heads/{}", branch);

        let current_hex = self
            .commit_oid
            .map(|oid| format!("{}", oid))
            .unwrap_or_default();

        let current_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;

        // Read reflog to find forward commits
        let reflog_entries = crate::reflog::read_reflog(&self.inner.path, &refname)?;

        let mut forward_sha = current_hex.clone();
        for _ in 0..n {
            // Find entry where new_sha matches current — old_sha is the "forward" one
            let next = reflog_entries
                .iter()
                .rev()
                .find(|e| e.new_sha == forward_sha)
                .map(|e| e.old_sha.clone())
                .ok_or_else(|| Error::not_found("no redo target found in reflog"))?;
            forward_sha = next;
        }

        let forward_oid =
            gix::ObjectId::from_hex(forward_sha.as_bytes()).map_err(Error::git)?;

        let inner = Arc::clone(&self.inner);

        use gix::refs::transaction::PreviousValue;
        with_repo_lock(&inner.path, || {
            let repo = inner
                .repo
                .lock()
                .map_err(|e| Error::git_msg(e.to_string()))?;

            // Stale snapshot check
            let current_ref = repo
                .find_reference(refname.as_str())
                .map_err(|_| Error::not_found(format!("branch '{}' not found", branch)))?;
            let actual_oid = current_ref.id().detach();
            if actual_oid != current_oid {
                return Err(Error::stale_snapshot(format!(
                    "branch '{}' has moved: expected {}, found {}",
                    branch, current_oid, actual_oid
                )));
            }

            repo.reference(
                refname.as_str(),
                forward_oid,
                PreviousValue::Any,
                "redo: move forward",
            )
            .map_err(Error::git)?;

            // Write reflog entry for redo
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default();
            let _ = crate::reflog::write_reflog_entry(
                &inner.path,
                &refname,
                &crate::types::ReflogEntry {
                    old_sha: current_hex.clone(),
                    new_sha: forward_sha.clone(),
                    committer: format!(
                        "{} <{}>",
                        inner.signature.name, inner.signature.email
                    ),
                    timestamp: now.as_secs(),
                    message: "redo: move forward".to_string(),
                },
            );

            Ok(())
        })?;

        Fs::from_commit(inner, forward_oid, self.ref_name.clone(), Some(self.writable))
    }

    /// Walk the commit history, returning [`CommitInfo`] entries.
    ///
    /// All filters in [`LogOptions`] are optional and combine with AND:
    /// `path` restricts to commits that changed the given file, `match_pattern`
    /// filters by commit message glob, and `before` caps the timestamp.
    pub fn log(&self, opts: LogOptions) -> Result<Vec<CommitInfo>> {
        let mut commit_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;

        let skip = opts.skip.unwrap_or(0);
        let limit = opts.limit.unwrap_or(usize::MAX);
        let filter_path = opts.path.as_deref().map(crate::paths::normalize_path).transpose()?;
        let match_pattern = opts.match_pattern.as_deref();
        let before = opts.before;

        let repo = self
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        let mut results = Vec::new();
        let mut matched = 0usize;

        loop {
            let obj = repo.find_object(commit_oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let commit_ref =
                gix::objs::CommitRef::from_bytes(&data).map_err(Error::git)?;

            let timestamp = commit_ref.author.time().map(|t| t.seconds as u64).unwrap_or(0);
            let message = commit_ref.message.to_string();
            let tree_oid: gix::ObjectId = commit_ref.tree();
            let parent_oid: Option<gix::ObjectId> =
                commit_ref.parents().next();

            // Apply filters
            let mut include = true;

            // before filter
            if let Some(cutoff) = before {
                if timestamp > cutoff {
                    include = false;
                }
            }

            // match_pattern filter (glob on message)
            if include {
                if let Some(pat) = match_pattern {
                    if !crate::glob::glob_match(pat, &message) {
                        include = false;
                    }
                }
            }

            // path filter: skip if the path has the same OID in this commit and its parent
            if include {
                if let Some(ref filter) = filter_path {
                    let this_entry = tree::entry_at_path(&repo, tree_oid, filter)?;
                    let parent_entry = if let Some(pid) = parent_oid {
                        let pobj = repo.find_object(pid).map_err(Error::git)?;
                        let pdata = pobj.data.to_vec();
                        let parent_commit =
                            gix::objs::CommitRef::from_bytes(&pdata).map_err(Error::git)?;
                        let parent_tree: gix::ObjectId = parent_commit.tree();
                        tree::entry_at_path(&repo, parent_tree, filter)?
                    } else {
                        None
                    };

                    let same = match (&this_entry, &parent_entry) {
                        (Some(a), Some(b)) => a.oid == b.oid && a.mode == b.mode,
                        (None, None) => true,
                        _ => false,
                    };
                    if same {
                        include = false;
                    }
                }
            }

            if include {
                matched += 1;
                if matched > skip {
                    results.push(CommitInfo {
                        commit_hash: format!("{}", commit_oid),
                        message,
                        time: Some(timestamp),
                        author_name: Some(commit_ref.author.name.to_string()),
                        author_email: Some(commit_ref.author.email.to_string()),
                    });
                }
            }

            if results.len() >= limit {
                break;
            }

            match parent_oid {
                Some(parent) => commit_oid = parent,
                None => break,
            }
        }

        Ok(results)
    }

    // -- Internal -----------------------------------------------------------

    /// Build an `Fs` from a known commit oid.
    pub(crate) fn from_commit(
        inner: Arc<GitStoreInner>,
        commit_oid: gix::ObjectId,
        ref_name: Option<String>,
        writable: Option<bool>,
    ) -> Result<Self> {
        let writable = writable.unwrap_or(ref_name.is_some());
        let tree_oid = {
            let repo = inner
                .repo
                .lock()
                .map_err(|e| Error::git_msg(e.to_string()))?;
            let obj = repo.find_object(commit_oid).map_err(Error::git)?;
            let data = obj.data.to_vec();
            let commit_ref =
                gix::objs::CommitRef::from_bytes(&data).map_err(Error::git)?;
            let tree_oid: gix::ObjectId = commit_ref.tree();
            tree_oid
        };

        Ok(Fs {
            inner,
            commit_oid: Some(commit_oid),
            tree_oid: Some(tree_oid),
            ref_name,
            writable,
            changes: None,
        })
    }

    /// Commit accumulated changes and return the new `Fs` snapshot.
    pub(crate) fn commit_changes(
        &self,
        writes: &[(String, Option<TreeWrite>)],
        message: &str,
    ) -> Result<Fs> {
        let branch = self.require_writable("commit")?;
        let refname = format!("refs/heads/{}", branch);

        let repo = self
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        let (new_commit_oid, new_tree_oid) = with_repo_lock(&self.inner.path, || {
            // Stale snapshot check
            let current_ref = repo
                .find_reference(refname.as_str())
                .map_err(|_| Error::not_found(format!("branch '{}' not found", branch)))?;
            let current_oid = current_ref.id().detach();

            if let Some(our_oid) = self.commit_oid {
                if current_oid != our_oid {
                    return Err(Error::stale_snapshot(format!(
                        "branch '{}' has moved: expected {}, found {}",
                        branch, our_oid, current_oid
                    )));
                }
            }

            // Rebuild tree
            let base_tree = self.tree_oid.unwrap_or_else(|| gix::ObjectId::null(gix::hash::Kind::Sha1));
            let new_tree_oid = tree::rebuild_tree(&repo, base_tree, writes)?;

            // No-op check: if tree didn't change, skip
            if Some(new_tree_oid) == self.tree_oid {
                return Ok((current_oid, self.tree_oid.unwrap()));
            }

            // Build commit
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default();
            let time =
                gix::date::Time::new(now.as_secs() as gix::date::SecondsSinceUnixEpoch, 0);
            let actor = gix::actor::Signature {
                name: self.inner.signature.name.clone().into(),
                email: self.inner.signature.email.clone().into(),
                time,
            };

            let parents: Vec<gix::ObjectId> = if let Some(oid) = self.commit_oid {
                vec![oid]
            } else {
                vec![]
            };

            let commit = gix::objs::Commit {
                tree: new_tree_oid,
                parents: parents.into(),
                author: actor.clone(),
                committer: actor,
                encoding: None,
                message: message.into(),
                extra_headers: vec![],
            };
            let new_commit_oid = repo.write_object(&commit).map_err(Error::git)?;

            // Update ref
            use gix::refs::transaction::PreviousValue;
            let msg: String = format!("commit: {}", message);
            repo.reference(
                refname.as_str(),
                new_commit_oid,
                PreviousValue::Any,
                msg.as_str(),
            )
            .map_err(Error::git)?;

            // Write reflog entry manually (gix doesn't write reflogs for bare repos)
            let _ = crate::reflog::write_reflog_entry(
                &self.inner.path,
                &refname,
                &crate::types::ReflogEntry {
                    old_sha: format!("{}", current_oid),
                    new_sha: format!("{}", new_commit_oid),
                    committer: format!(
                        "{} <{}>",
                        self.inner.signature.name, self.inner.signature.email
                    ),
                    timestamp: now.as_secs(),
                    message: msg,
                },
            );

            Ok((new_commit_oid.detach(), new_tree_oid))
        })?;

        Ok(Fs {
            inner: Arc::clone(&self.inner),
            commit_oid: Some(new_commit_oid),
            tree_oid: Some(new_tree_oid),
            ref_name: self.ref_name.clone(),
            writable: self.writable,
            changes: None,
        })
    }
}

impl std::fmt::Display for Fs {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let short = self.commit_oid.map(|o| format!("{}", o)).unwrap_or_default();
        let short = &short[..short.len().min(7)];
        let mut parts = Vec::new();
        if let Some(ref name) = self.ref_name {
            parts.push(format!("ref_name={:?}", name));
        }
        parts.push(format!("commit={}", short));
        if !self.writable {
            parts.push("readonly".into());
        }
        write!(f, "Fs({})", parts.join(", "))
    }
}

/// Retry a write operation with automatic back-off on stale-snapshot errors.
///
/// Calls `f` up to 5 times. Uses exponential back-off with a base of 10 ms,
/// factor 2x, and a cap of 200 ms to avoid thundering-herd problems.
///
/// # Errors
/// Returns [`Error::StaleSnapshot`] if all attempts are exhausted.
/// Returns any other error immediately.
pub fn retry_write<F, T>(mut f: F) -> Result<T>
where
    F: FnMut() -> Result<T>,
{
    let mut attempt = 0u32;
    loop {
        match f() {
            Ok(v) => return Ok(v),
            Err(Error::StaleSnapshot(_)) if attempt < 5 => {
                let backoff = std::time::Duration::from_millis(
                    (10 * 2u64.pow(attempt)).min(200),
                );
                std::thread::sleep(backoff);
                attempt += 1;
            }
            Err(e) => return Err(e),
        }
    }
}

// ---------------------------------------------------------------------------
// walk_subtree helper for copy_from_ref
// ---------------------------------------------------------------------------

use std::collections::BTreeMap;

/// Walk a subtree at `path` within a tree, returning `{rel: (oid, mode)}`.
fn walk_subtree(
    repo: &gix::Repository,
    root_tree: gix::ObjectId,
    path: &str,
) -> Result<BTreeMap<String, (gix::ObjectId, u32)>> {
    let mut result = BTreeMap::new();

    if path.is_empty() {
        // Walk entire tree
        let entries = tree::walk_tree(repo, root_tree)?;
        for (rel, we) in entries {
            result.insert(rel, (we.oid, we.mode));
        }
    } else {
        // Resolve to subtree
        let entry = tree::entry_at_path(repo, root_tree, path)?;
        match entry {
            Some(e) if e.mode == MODE_TREE => {
                let entries = tree::walk_tree(repo, e.oid)?;
                for (rel, we) in entries {
                    result.insert(rel, (we.oid, we.mode));
                }
            }
            _ => {
                // Path doesn't exist or isn't a directory — return empty
            }
        }
    }

    Ok(result)
}

// ---------------------------------------------------------------------------
// Glob helper (internal)
// ---------------------------------------------------------------------------

fn iglob_recursive(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    segments: &[&str],
    prefix: &str,
    results: &mut Vec<String>,
) -> Result<()> {
    if segments.is_empty() {
        return Ok(());
    }

    let seg = segments[0];
    let rest = &segments[1..];

    let tree_data = repo.find_object(tree_oid).map_err(Error::git)?;
    let data = tree_data.data.to_vec();
    let tree_ref = gix::objs::TreeRef::from_bytes(&data).map_err(Error::git)?;

    if seg == "**" {
        // Match zero or more directory levels
        iglob_recursive(repo, tree_oid, rest, prefix, results)?;

        for entry in &tree_ref.entries {
            let name = String::from_utf8_lossy(entry.filename).into_owned();
            if name.starts_with('.') {
                continue;
            }
            let full = if prefix.is_empty() {
                name.clone()
            } else {
                format!("{}/{}", prefix, name)
            };
            let entry_mode = tree::mode_to_u32(entry.mode);
            if entry_mode == MODE_TREE {
                iglob_recursive(repo, entry.oid.to_owned(), segments, &full, results)?;
            }
        }
    } else {
        for entry in &tree_ref.entries {
            let name = String::from_utf8_lossy(entry.filename).into_owned();
            if !crate::glob::glob_match(seg, &name) {
                continue;
            }
            let full = if prefix.is_empty() {
                name.clone()
            } else {
                format!("{}/{}", prefix, name)
            };
            let entry_mode = tree::mode_to_u32(entry.mode);

            if rest.is_empty() {
                if entry_mode != MODE_TREE {
                    results.push(full);
                }
            } else if entry_mode == MODE_TREE {
                iglob_recursive(repo, entry.oid.to_owned(), rest, &full, results)?;
            }
        }
    }

    Ok(())
}

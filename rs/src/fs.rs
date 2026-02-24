use std::path::Path;
use std::sync::Arc;

use crate::batch::Batch;
use crate::error::{Error, Result};
use crate::lock::with_repo_lock;
use crate::store::GitStoreInner;
use crate::tree;
use crate::types::{
    ChangeReport, CommitInfo, FileEntry, FileType, StatResult, WalkEntry, WriteEntry, MODE_BLOB,
    MODE_LINK, MODE_TREE,
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

#[derive(Debug, Clone, Default)]
pub struct WriteOptions {
    pub message: Option<String>,
    pub mode: Option<u32>,
}

#[derive(Debug, Clone, Default)]
pub struct ApplyOptions {
    pub message: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct BatchOptions {
    pub message: Option<String>,
}

#[derive(Debug, Clone)]
pub struct CopyInOptions {
    pub include: Option<Vec<String>>,
    pub exclude: Option<Vec<String>>,
    pub message: Option<String>,
    pub dry_run: bool,
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

#[derive(Debug, Clone, Default)]
pub struct CopyOutOptions {
    pub include: Option<Vec<String>>,
    pub exclude: Option<Vec<String>>,
}

#[derive(Debug, Clone)]
pub struct SyncOptions {
    pub include: Option<Vec<String>>,
    pub exclude: Option<Vec<String>>,
    pub message: Option<String>,
    pub dry_run: bool,
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

#[derive(Debug, Clone, Default)]
pub struct RemoveOptions {
    pub recursive: bool,
    pub dry_run: bool,
    pub message: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct RemoveFromDiskOptions {
    pub include: Option<Vec<String>>,
    pub exclude: Option<Vec<String>>,
}

#[derive(Debug, Clone, Default)]
pub struct MoveOptions {
    pub recursive: bool,
    pub dry_run: bool,
    pub message: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct CopyRefOptions {
    pub delete: bool,
    pub dry_run: bool,
    pub message: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct LogOptions {
    pub limit: Option<usize>,
    pub skip: Option<usize>,
    /// Only include commits that changed this path.
    pub path: Option<String>,
    /// Only include commits whose message matches this glob pattern.
    pub match_pattern: Option<String>,
    /// Only include commits with timestamp <= this value (seconds since epoch).
    pub before: Option<u64>,
}

// ---------------------------------------------------------------------------
// Fs
// ---------------------------------------------------------------------------

/// A snapshot view of a branch in the store.
///
/// Cheap to clone (`Arc` internally). No lifetime parameter — can be stored
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

    /// The commit hash as hex string.
    pub fn commit_hash(&self) -> Option<String> {
        self.commit_oid.map(|oid| format!("{}", oid))
    }

    /// The root tree hash as hex string.
    pub fn tree_hash(&self) -> Option<String> {
        self.tree_oid.map(|oid| format!("{}", oid))
    }

    /// The ref name (branch or tag name), if this Fs is attached to a ref.
    pub fn ref_name(&self) -> Option<&str> {
        self.ref_name.as_deref()
    }

    /// Whether this Fs is writable (true for branches, false for tags/detached).
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

    /// The commit message (trailing newline stripped).
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

    /// The commit timestamp (seconds since epoch).
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

    /// The commit author name.
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

    /// The commit author email.
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

    /// The change report from the last operation, if any.
    pub fn changes(&self) -> Option<&ChangeReport> {
        self.changes.as_ref()
    }

    // -- Read ---------------------------------------------------------------

    /// Read raw bytes at `path`.
    pub fn read(&self, path: &str) -> Result<Vec<u8>> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| tree::read_blob_at_path(repo, tree_oid, path))
    }

    /// Read UTF-8 text at `path`.
    pub fn read_text(&self, path: &str) -> Result<String> {
        let data = self.read(path)?;
        String::from_utf8(data).map_err(|e| Error::git_msg(format!("invalid UTF-8: {}", e)))
    }

    /// List immediate children at `path`.
    pub fn ls(&self, path: &str) -> Result<Vec<WalkEntry>> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| tree::list_tree_at_path(repo, tree_oid, path))
    }

    /// Recursively walk the tree under `path`.
    pub fn walk(&self, path: &str) -> Result<Vec<(String, WalkEntry)>> {
        let tree_oid = self.require_tree()?;
        let path_norm = crate::paths::normalize_path(path)?;

        self.with_repo(|repo| {
            if path_norm.is_empty() {
                tree::walk_tree(repo, tree_oid)
            } else {
                // Resolve to subtree first
                let entry = tree::entry_at_path(repo, tree_oid, &path_norm)?
                    .ok_or_else(|| Error::not_found(&path_norm))?;
                if entry.mode != MODE_TREE {
                    return Err(Error::not_a_directory(&path_norm));
                }
                let entries = tree::walk_tree(repo, entry.oid)?;
                // Prefix paths
                Ok(entries
                    .into_iter()
                    .map(|(p, e)| (format!("{}/{}", path_norm, p), e))
                    .collect())
            }
        })
    }

    /// Returns `true` if `path` exists.
    pub fn exists(&self, path: &str) -> Result<bool> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| tree::exists_at_path(repo, tree_oid, path))
    }

    /// Returns `true` if `path` is a directory (tree).
    pub fn is_dir(&self, path: &str) -> Result<bool> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            match tree::entry_at_path(repo, tree_oid, path)? {
                Some(entry) => Ok(entry.mode == MODE_TREE),
                None => Ok(false),
            }
        })
    }

    /// Return the file type at `path`.
    pub fn file_type(&self, path: &str) -> Result<FileType> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let entry = tree::entry_at_path(repo, tree_oid, path)?
                .ok_or_else(|| Error::not_found(path))?;
            FileType::from_mode(entry.mode)
                .ok_or_else(|| Error::git_msg(format!("unknown mode: {:#o}", entry.mode)))
        })
    }

    /// Return the size of the blob at `path`.
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

    /// Return the object hash (hex) at `path`.
    pub fn object_hash(&self, path: &str) -> Result<String> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let entry = tree::entry_at_path(repo, tree_oid, path)?
                .ok_or_else(|| Error::not_found(path))?;
            Ok(format!("{}", entry.oid))
        })
    }

    /// Read the symlink target at `path`.
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

    /// Single-call getattr — returns all stat fields in one call.
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

    /// List immediate children at `path` with entry types (alias for `ls()`).
    pub fn listdir(&self, path: &str) -> Result<Vec<WalkEntry>> {
        self.ls(path)
    }

    /// Read raw bytes at `path` with optional offset and size.
    pub fn read_range(&self, path: &str, offset: usize, size: Option<usize>) -> Result<Vec<u8>> {
        let data = self.read(path)?;
        let start = offset.min(data.len());
        let end = match size {
            Some(s) => (start + s).min(data.len()),
            None => data.len(),
        };
        Ok(data[start..end].to_vec())
    }

    /// Read a blob by its hex hash, bypassing tree walk.
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

    /// Glob the tree, returning sorted matching paths.
    pub fn glob(&self, pattern: &str) -> Result<Vec<String>> {
        let mut paths = self.iglob(pattern)?;
        paths.sort();
        Ok(paths)
    }

    /// Glob the tree, returning matching paths.
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

    /// Write raw bytes to `path`. Returns the new `Fs` snapshot.
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

    /// Write UTF-8 text to `path`. Returns the new `Fs` snapshot.
    pub fn write_text(
        &self,
        path: &str,
        text: &str,
        opts: WriteOptions,
    ) -> Result<Fs> {
        self.write(path, text.as_bytes(), opts)
    }

    /// Write the contents of a file on disk to `path`. Returns the new `Fs` snapshot.
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

    /// Write a symlink at `path`. Returns the new `Fs` snapshot.
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

    /// Apply a map of path → WriteEntry atomically, with optional removes.
    /// Returns the new `Fs` snapshot.
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

        let message = opts
            .message
            .unwrap_or_else(|| crate::paths::format_commit_message("apply", None));
        self.commit_changes(&writes, &message)
    }

    /// Open a `Batch` for accumulating writes.
    pub fn batch(&self, opts: BatchOptions) -> Batch {
        Batch {
            fs: self.clone(),
            writes: vec![],
            removes: vec![],
            message: opts.message,
            operation: None,
            closed: false,
        }
    }

    // -- Copy / sync --------------------------------------------------------

    /// Copy files from disk into the store. Returns `(report, new_fs)`.
    pub fn copy_in(
        &self,
        src: &Path,
        dest: &str,
        opts: CopyInOptions,
    ) -> Result<(ChangeReport, Fs)> {
        let tree_oid = self.require_tree()?;
        let (writes, report) = self.with_repo(|repo| {
            let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            crate::copy::copy_in(repo, tree_oid, src, dest, inc.as_deref(), exc.as_deref())
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

    /// Copy files from the store to disk.
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

    /// Sync files from disk into the store. Returns `(report, new_fs)`.
    ///
    /// Unlike `copy_in`, this also deletes files in the destination that are
    /// not present on disk, and classifies changes as add/update/delete.
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

    /// Sync files from the store to disk.
    pub fn sync_out(
        &self,
        src: &str,
        dest: &Path,
        opts: SyncOptions,
    ) -> Result<ChangeReport> {
        let tree_oid = self.require_tree()?;
        self.with_repo(|repo| {
            let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
            crate::copy::sync_out(repo, tree_oid, src, dest, inc.as_deref(), exc.as_deref())
        })
    }

    /// Remove files from disk that match a pattern.
    pub fn remove_from_disk(
        &self,
        path: &Path,
        opts: RemoveFromDiskOptions,
    ) -> Result<ChangeReport> {
        let inc: Option<Vec<&str>> = opts.include.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
        let exc: Option<Vec<&str>> = opts.exclude.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
        crate::copy::remove_from_disk(path, inc.as_deref(), exc.as_deref())
    }

    /// Remove paths from the git tree. Returns the new `Fs` snapshot.
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

    /// Rename a path within the store. Returns the new `Fs` snapshot.
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

    /// Move multiple source paths to a destination. Follows POSIX mv semantics:
    /// - Single source to non-existing destination: rename
    /// - Multiple sources: destination must be an existing directory
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

    /// Copy files from another branch/tag/commit into this branch in a single
    /// atomic commit. Both snapshots must belong to the same repository so
    /// blobs are referenced by OID — no data is read into memory.
    pub fn copy_ref(
        &self,
        source: &Fs,
        src_path: &str,
        dest_path: Option<&str>,
        opts: CopyRefOptions,
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

        let src_norm = crate::paths::normalize_path(src_path)?;
        let dest_norm = match dest_path {
            Some(p) => crate::paths::normalize_path(p)?,
            None => src_norm.clone(),
        };

        let src_tree = source.require_tree()?;
        let dest_tree = self.require_tree()?;

        // Walk both subtrees
        let (src_files, dest_files) = self.with_repo(|repo| {
            let src_files = walk_subtree(repo, src_tree, &src_norm)?;
            let dest_files = walk_subtree(repo, dest_tree, &dest_norm)?;
            Ok((src_files, dest_files))
        })?;

        // Build writes and removes
        let mut writes: Vec<(String, Option<TreeWrite>)> = Vec::new();
        let mut report = ChangeReport::new();

        for (rel, (src_oid, src_mode)) in &src_files {
            let full = if dest_norm.is_empty() {
                rel.clone()
            } else {
                format!("{}/{}", dest_norm, rel)
            };
            let dest_entry = dest_files.get(rel);
            match dest_entry {
                None => {
                    let ft = FileType::from_mode(*src_mode).unwrap_or(FileType::Blob);
                    report.add.push(FileEntry::new(&full, ft));
                    writes.push((
                        full,
                        Some(TreeWrite {
                            data: vec![],
                            oid: *src_oid,
                            mode: *src_mode,
                        }),
                    ));
                }
                Some((d_oid, d_mode)) if d_oid != src_oid || d_mode != src_mode => {
                    let ft = FileType::from_mode(*src_mode).unwrap_or(FileType::Blob);
                    report.update.push(FileEntry::new(&full, ft));
                    writes.push((
                        full,
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
            for rel in dest_files.keys() {
                if !src_files.contains_key(rel) {
                    let full = if dest_norm.is_empty() {
                        rel.clone()
                    } else {
                        format!("{}/{}", dest_norm, rel)
                    };
                    let (_, mode) = dest_files[rel];
                    let ft = FileType::from_mode(mode).unwrap_or(FileType::Blob);
                    report.delete.push(FileEntry::new(&full, ft));
                    writes.push((full, None));
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

    /// Export the tree to a directory on disk.
    pub fn export(&self, dest: &Path) -> Result<ChangeReport> {
        self.copy_out("", dest, CopyOutOptions::default())
    }

    // -- History ------------------------------------------------------------

    /// Return the parent `Fs` (previous commit on this branch).
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
                    let parent_id: gix::ObjectId = pid.into();
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

    /// Go back `n` commits.
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

    /// Undo the last `n` commits (soft reset).
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
        let repo = inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        let current_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;

        use gix::refs::transaction::PreviousValue;
        with_repo_lock(&inner.path, || {
            repo.reference(
                refname.as_str(),
                target_oid,
                PreviousValue::Any,
                "undo: move back",
            )
            .map_err(Error::git)?;
            Ok(())
        })?;

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

        Ok(target)
    }

    /// Redo `n` undone commits by scanning the reflog forward.
    pub fn redo(&self, n: usize) -> Result<Fs> {
        let branch = self.require_writable("redo")?;
        let refname = format!("refs/heads/{}", branch);

        let current_hex = self
            .commit_oid
            .map(|oid| format!("{}", oid))
            .unwrap_or_default();

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
        let repo = inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        use gix::refs::transaction::PreviousValue;
        with_repo_lock(&inner.path, || {
            repo.reference(
                refname.as_str(),
                forward_oid,
                PreviousValue::Any,
                "redo: move forward",
            )
            .map_err(Error::git)?;
            Ok(())
        })?;

        // Write reflog entry for redo
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        let _ = crate::reflog::write_reflog_entry(
            &inner.path,
            &refname,
            &crate::types::ReflogEntry {
                old_sha: current_hex,
                new_sha: forward_sha,
                committer: format!(
                    "{} <{}>",
                    inner.signature.name, inner.signature.email
                ),
                timestamp: now.as_secs(),
                message: "redo: move forward".to_string(),
            },
        );

        drop(repo);
        Fs::from_commit(inner, forward_oid, self.ref_name.clone(), Some(self.writable))
    }

    /// Return commit log entries, with optional filtering.
    pub fn log(&self, opts: LogOptions) -> Result<Vec<CommitInfo>> {
        let mut commit_oid = self
            .commit_oid
            .ok_or_else(|| Error::not_found("no commit in snapshot"))?;

        let skip = opts.skip.unwrap_or(0);
        let limit = opts.limit.unwrap_or(usize::MAX);
        let filter_path = opts.path.as_deref().map(|p| crate::paths::normalize_path(p)).transpose()?;
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
            let tree_oid: gix::ObjectId = commit_ref.tree().into();
            let parent_oid: Option<gix::ObjectId> =
                commit_ref.parents().next().map(|p| p.into());

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
                        let parent_tree: gix::ObjectId = parent_commit.tree().into();
                        tree::entry_at_path(&repo, parent_tree, filter)?
                    } else {
                        None
                    };

                    let same = match (&this_entry, &parent_entry) {
                        (Some(a), Some(b)) => a.oid == b.oid,
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
            let tree_oid: gix::ObjectId = commit_ref.tree().into();
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

/// Retry a write operation on stale-snapshot errors.
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
// walk_subtree helper for copy_ref
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

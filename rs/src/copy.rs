use std::path::Path;

use crate::error::{Error, Result};
use crate::fs::TreeWrite;
use crate::tree;
use crate::types::{ChangeReport, FileEntry, FileType, MODE_BLOB, MODE_LINK, MODE_TREE};

/// Copy files from a local directory into a git tree.
///
/// Walks `src` on disk, writes blobs to the object store, and returns a list
/// of `(store_path, TreeWrite)` pairs that the caller should apply to
/// the tree, along with a [`ChangeReport`] describing what was added.
///
/// # Arguments
/// * `repo` - The git repository to write blobs into.
/// * `base_tree` - Root tree OID of the current commit (used for checksum dedup).
/// * `src` - Local directory to copy from.
/// * `dest` - Destination path prefix inside the repo (e.g. `"data"` or `""`).
/// * `include` - Optional glob patterns; only matching files are copied.
/// * `exclude` - Optional glob patterns; matching files are skipped.
/// * `checksum` - When `true`, skip files whose blob OID and mode already
///   match the existing tree entry (content-based deduplication).
pub fn copy_in(
    repo: &gix::Repository,
    base_tree: gix::ObjectId,
    src: &Path,
    dest: &str,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
    checksum: bool,
) -> Result<(Vec<(String, TreeWrite)>, ChangeReport)> {
    let mut writes = Vec::new();
    let mut report = ChangeReport::new();
    let dest_norm = crate::paths::normalize_path(dest)?;

    // Build existing entries map when checksum is enabled
    let existing: std::collections::HashMap<String, (gix::ObjectId, u32)> = if checksum {
        let target_oid = if dest_norm.is_empty() {
            base_tree
        } else {
            match tree::entry_at_path(repo, base_tree, &dest_norm)? {
                Some(entry) if entry.mode == MODE_TREE => entry.oid,
                _ => gix::ObjectId::empty_tree(gix::hash::Kind::Sha1),
            }
        };
        if target_oid == gix::ObjectId::empty_tree(gix::hash::Kind::Sha1) {
            std::collections::HashMap::new()
        } else {
            tree::walk_tree(repo, target_oid)?
                .into_iter()
                .map(|(p, e)| (p, (e.oid, e.mode)))
                .collect()
        }
    } else {
        std::collections::HashMap::new()
    };

    let disk_files = disk_glob(src, include, exclude)?;

    for rel_path in &disk_files {
        let full_disk = src.join(rel_path);
        let store_path = if dest_norm.is_empty() {
            rel_path.clone()
        } else {
            format!("{}/{}", dest_norm, rel_path)
        };

        let mode = tree::mode_from_disk(&full_disk).unwrap_or(MODE_BLOB);
        let data = if mode == MODE_LINK {
            let target = std::fs::read_link(&full_disk).map_err(|e| Error::io(&full_disk, e))?;
            target.to_string_lossy().into_owned().into_bytes()
        } else {
            std::fs::read(&full_disk).map_err(|e| Error::io(&full_disk, e))?
        };

        let file_type = FileType::from_mode(mode).unwrap_or(FileType::Blob);
        let blob_oid = repo.write_blob(&data).map_err(Error::git)?;

        // Skip unchanged files when checksum is enabled
        if checksum {
            if let Some((existing_oid, existing_mode)) = existing.get(rel_path) {
                if *existing_oid == blob_oid.detach() && *existing_mode == mode {
                    continue;
                }
            }
        }

        writes.push((
            store_path.clone(),
            TreeWrite {
                data,
                oid: blob_oid.detach(),
                mode,
            },
        ));
        report.add.push(FileEntry::with_src(&store_path, file_type, &full_disk));
    }

    Ok((writes, report))
}

/// Copy files from a git tree to a local directory.
///
/// Reads blobs from the tree rooted at `src` and writes them to `dest` on
/// disk. Symlinks and executable permissions are preserved on Unix.
///
/// # Arguments
/// * `repo` - The git repository to read objects from.
/// * `tree_oid` - Root tree OID of the commit to export from.
/// * `src` - Source path prefix inside the repo (e.g. `"data"` or `""`).
/// * `dest` - Local directory to write files into.
/// * `include` - Optional glob patterns; only matching files are copied.
/// * `exclude` - Optional glob patterns; matching files are skipped.
pub fn copy_out(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    src: &str,
    dest: &Path,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
) -> Result<ChangeReport> {
    let mut report = ChangeReport::new();
    let src_norm = crate::paths::normalize_path(src)?;

    let target_oid = if src_norm.is_empty() {
        tree_oid
    } else {
        let entry = tree::entry_at_path(repo, tree_oid, &src_norm)?
            .ok_or_else(|| Error::not_found(&src_norm))?;
        if entry.mode != MODE_TREE {
            return Err(Error::not_a_directory(&src_norm));
        }
        entry.oid
    };

    let entries = tree::walk_tree(repo, target_oid)?;

    for (rel_path, entry) in &entries {
        if !matches_filters(rel_path, include, exclude) {
            continue;
        }

        let dest_path = dest.join(rel_path);
        if let Some(parent) = dest_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| Error::io(parent, e))?;
        }

        let obj = repo.find_object(entry.oid).map_err(Error::git)?;

        if entry.mode == MODE_LINK {
            let target = String::from_utf8_lossy(&obj.data);
            #[cfg(unix)]
            {
                use std::os::unix::fs::symlink;
                let _ = std::fs::remove_file(&dest_path);
                symlink(target.as_ref(), &dest_path)
                    .map_err(|e| Error::io(&dest_path, e))?;
            }
            #[cfg(not(unix))]
            {
                std::fs::write(&dest_path, target.as_bytes())
                    .map_err(|e| Error::io(&dest_path, e))?;
            }
        } else {
            std::fs::write(&dest_path, &obj.data).map_err(|e| Error::io(&dest_path, e))?;

            #[cfg(unix)]
            if entry.mode == crate::types::MODE_BLOB_EXEC {
                use std::os::unix::fs::PermissionsExt;
                let perms = std::fs::Permissions::from_mode(0o755);
                std::fs::set_permissions(&dest_path, perms)
                    .map_err(|e| Error::io(&dest_path, e))?;
            }
        }

        let file_type = FileType::from_mode(entry.mode).unwrap_or(FileType::Blob);
        report.add.push(FileEntry::with_src(rel_path, file_type, &dest_path));
    }

    Ok(report)
}

/// Sync files from disk into a tree (add + update + delete).
///
/// Makes the tree subtree at `dest` identical to the local directory `src`.
/// Unlike [`copy_in`], this also deletes files in the destination tree that
/// are not present on disk, and classifies changes as add/update/delete in
/// the returned [`ChangeReport`]. Entries with `None` in the returned vec
/// represent deletions.
///
/// # Arguments
/// * `repo` - The git repository.
/// * `base_tree` - Root tree OID of the current commit.
/// * `src` - Local directory to sync from.
/// * `dest` - Destination path prefix inside the repo.
/// * `include` - Optional glob patterns; only matching files are synced.
/// * `exclude` - Optional glob patterns; matching files are skipped.
/// * `checksum` - When `true`, skip unchanged files (OID + mode comparison).
pub fn sync_in(
    repo: &gix::Repository,
    base_tree: gix::ObjectId,
    src: &Path,
    dest: &str,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
    checksum: bool,
) -> Result<(Vec<(String, Option<TreeWrite>)>, ChangeReport)> {
    let mut writes: Vec<(String, Option<TreeWrite>)> = Vec::new();
    let mut report = ChangeReport::new();
    let dest_norm = crate::paths::normalize_path(dest)?;

    // Collect disk files
    let disk_files = disk_glob(src, include, exclude)?;
    let disk_set: std::collections::HashSet<&str> = disk_files.iter().map(|s| s.as_str()).collect();

    // Collect existing tree entries at dest
    let existing = {
        let target_oid = if dest_norm.is_empty() {
            base_tree
        } else {
            match tree::entry_at_path(repo, base_tree, &dest_norm)? {
                Some(entry) if entry.mode == MODE_TREE => entry.oid,
                Some(_) => {
                    // dest exists but is a file — treat as empty subtree
                    gix::ObjectId::empty_tree(gix::hash::Kind::Sha1)
                }
                None => gix::ObjectId::empty_tree(gix::hash::Kind::Sha1),
            }
        };
        if target_oid == gix::ObjectId::empty_tree(gix::hash::Kind::Sha1) {
            Vec::new()
        } else {
            tree::walk_tree(repo, target_oid)?
        }
    };

    let existing_map: std::collections::HashMap<&str, &crate::types::WalkEntry> =
        existing.iter().map(|(p, e)| (p.as_str(), e)).collect();

    // Process disk files: add or update
    for rel_path in &disk_files {
        let full_disk = src.join(rel_path);
        let store_path = if dest_norm.is_empty() {
            rel_path.clone()
        } else {
            format!("{}/{}", dest_norm, rel_path)
        };

        let mode = tree::mode_from_disk(&full_disk).unwrap_or(MODE_BLOB);
        let data = if mode == MODE_LINK {
            let target = std::fs::read_link(&full_disk).map_err(|e| Error::io(&full_disk, e))?;
            target.to_string_lossy().into_owned().into_bytes()
        } else {
            std::fs::read(&full_disk).map_err(|e| Error::io(&full_disk, e))?
        };

        let blob_oid = repo.write_blob(&data).map_err(Error::git)?;
        let file_type = FileType::from_mode(mode).unwrap_or(FileType::Blob);

        // Check if this is an update vs add
        let is_changed = if let Some(existing_entry) = existing_map.get(rel_path.as_str()) {
            if checksum {
                existing_entry.oid != blob_oid.detach() || existing_entry.mode != mode
            } else {
                // Without checksum, always treat as changed
                true
            }
        } else {
            true
        };

        if is_changed {
            writes.push((
                store_path.clone(),
                Some(TreeWrite {
                    data,
                    oid: blob_oid.detach(),
                    mode,
                }),
            ));

            if existing_map.contains_key(rel_path.as_str()) {
                report.update.push(FileEntry::with_src(&store_path, file_type, &full_disk));
            } else {
                report.add.push(FileEntry::with_src(&store_path, file_type, &full_disk));
            }
        }
    }

    // Delete files in tree that are not on disk
    for (rel_path, entry) in &existing {
        if !disk_set.contains(rel_path.as_str()) {
            // Also apply include/exclude filters to deletions
            if !matches_filters(rel_path, include, exclude) {
                continue;
            }
            let store_path = if dest_norm.is_empty() {
                rel_path.clone()
            } else {
                format!("{}/{}", dest_norm, rel_path)
            };
            let file_type = FileType::from_mode(entry.mode).unwrap_or(FileType::Blob);
            writes.push((store_path.clone(), None));
            report.delete.push(FileEntry::new(&store_path, file_type));
        }
    }

    Ok((writes, report))
}

/// Sync files from a tree to disk (add + update + delete).
///
/// Makes the local directory `dest` identical to the tree subtree at `src`.
/// Unlike [`copy_out`], this also deletes local files that are not present
/// in the repo tree, prunes empty directories, and classifies all changes
/// as add/update/delete in the returned [`ChangeReport`].
///
/// # Arguments
/// * `repo` - The git repository.
/// * `tree_oid` - Root tree OID of the commit to export from.
/// * `src` - Source path prefix inside the repo.
/// * `dest` - Local directory to sync into.
/// * `include` - Optional glob patterns; only matching files are synced.
/// * `exclude` - Optional glob patterns; matching files are skipped.
/// * `checksum` - When `true`, skip unchanged files (content comparison).
pub fn sync_out(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    src: &str,
    dest: &Path,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
    checksum: bool,
) -> Result<ChangeReport> {
    let mut report = ChangeReport::new();
    let src_norm = crate::paths::normalize_path(src)?;

    // Walk repo tree to get source files
    let target_oid = if src_norm.is_empty() {
        tree_oid
    } else {
        let entry = tree::entry_at_path(repo, tree_oid, &src_norm)?
            .ok_or_else(|| Error::not_found(&src_norm))?;
        if entry.mode != MODE_TREE {
            return Err(Error::not_a_directory(&src_norm));
        }
        entry.oid
    };

    let repo_entries = tree::walk_tree(repo, target_oid)?;
    let repo_map: std::collections::HashMap<&str, &crate::types::WalkEntry> =
        repo_entries.iter().map(|(p, e)| (p.as_str(), e)).collect();

    // Walk local destination to get existing disk files
    let disk_files = if dest.exists() {
        disk_glob(dest, None, None)?
    } else {
        Vec::new()
    };
    let disk_set: std::collections::HashSet<&str> = disk_files.iter().map(|s| s.as_str()).collect();

    // Process repo files: write new/updated files to disk
    for (rel_path, entry) in &repo_entries {
        if !matches_filters(rel_path, include, exclude) {
            continue;
        }

        let dest_path = dest.join(rel_path);
        let obj = repo.find_object(entry.oid).map_err(Error::git)?;
        let file_type = FileType::from_mode(entry.mode).unwrap_or(FileType::Blob);

        // Check if file exists on disk and whether it's changed
        let needs_write = if disk_set.contains(rel_path.as_str()) {
            if checksum {
                // Compare blob OID of new content vs existing file
                let existing_data = if entry.mode == MODE_LINK {
                    match std::fs::read_link(&dest_path) {
                        Ok(target) => target.to_string_lossy().into_owned().into_bytes(),
                        Err(_) => vec![], // force write if can't read
                    }
                } else {
                    std::fs::read(&dest_path).unwrap_or_default()
                };
                let existing_oid = repo.write_blob(&existing_data).map_err(Error::git)?;
                existing_oid.detach() != entry.oid
            } else {
                true // without checksum, always write
            }
        } else {
            true // file doesn't exist on disk
        };

        if needs_write {
            if let Some(parent) = dest_path.parent() {
                std::fs::create_dir_all(parent).map_err(|e| Error::io(parent, e))?;
            }

            if entry.mode == MODE_LINK {
                let target = String::from_utf8_lossy(&obj.data);
                #[cfg(unix)]
                {
                    use std::os::unix::fs::symlink;
                    let _ = std::fs::remove_file(&dest_path);
                    symlink(target.as_ref(), &dest_path)
                        .map_err(|e| Error::io(&dest_path, e))?;
                }
                #[cfg(not(unix))]
                {
                    std::fs::write(&dest_path, target.as_bytes())
                        .map_err(|e| Error::io(&dest_path, e))?;
                }
            } else {
                std::fs::write(&dest_path, &obj.data).map_err(|e| Error::io(&dest_path, e))?;

                #[cfg(unix)]
                if entry.mode == crate::types::MODE_BLOB_EXEC {
                    use std::os::unix::fs::PermissionsExt;
                    let perms = std::fs::Permissions::from_mode(0o755);
                    std::fs::set_permissions(&dest_path, perms)
                        .map_err(|e| Error::io(&dest_path, e))?;
                }
            }

            if disk_set.contains(rel_path.as_str()) {
                report.update.push(FileEntry::with_src(rel_path, file_type, &dest_path));
            } else {
                report.add.push(FileEntry::with_src(rel_path, file_type, &dest_path));
            }
        }
    }

    // Delete disk files not in repo tree
    for rel_path in &disk_files {
        if !matches_filters(rel_path, include, exclude) {
            continue;
        }
        if !repo_map.contains_key(rel_path.as_str()) {
            let full_path = dest.join(rel_path);
            if full_path.exists() || full_path.symlink_metadata().is_ok() {
                std::fs::remove_file(&full_path).map_err(|e| Error::io(&full_path, e))?;
                report.delete.push(FileEntry::with_src(rel_path, FileType::Blob, &full_path));
            }
        }
    }

    // Prune empty directories
    prune_empty_dirs(dest)?;

    Ok(report)
}

/// Remove empty directories under `root`, bottom-up. Silently skips
/// directories that still contain files.
fn prune_empty_dirs(root: &Path) -> Result<()> {
    if !root.is_dir() {
        return Ok(());
    }
    // Collect all directories first, then try to remove bottom-up
    let mut dirs = Vec::new();
    collect_dirs(root, root, &mut dirs)?;
    // Sort by depth (deepest first) for bottom-up removal
    dirs.sort_by(|a, b| b.len().cmp(&a.len()));
    for dir in dirs {
        let full = root.join(&dir);
        // Try to remove — will fail silently if not empty
        let _ = std::fs::remove_dir(&full);
    }
    Ok(())
}

fn collect_dirs(root: &Path, dir: &Path, results: &mut Vec<String>) -> Result<()> {
    let read_dir = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(_) => return Ok(()),
    };
    for entry in read_dir {
        let entry = entry.map_err(|e| Error::io(dir, e))?;
        let path = entry.path();
        if path.is_dir() {
            let rel = path
                .strip_prefix(root)
                .unwrap_or(&path)
                .to_string_lossy()
                .into_owned();
            results.push(rel);
            collect_dirs(root, &path, results)?;
        }
    }
    Ok(())
}

/// Remove files from disk that match the given include/exclude patterns.
///
/// # Arguments
/// * `dest` - Root directory to scan for files.
/// * `include` - Optional glob patterns; only matching files are removed.
/// * `exclude` - Optional glob patterns; matching files are kept.
pub fn remove_from_disk(
    dest: &Path,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
) -> Result<ChangeReport> {
    let mut report = ChangeReport::new();
    let files = disk_glob(dest, include, exclude)?;
    for rel in &files {
        let full = dest.join(rel);
        if full.exists() {
            std::fs::remove_file(&full).map_err(|e| Error::io(&full, e))?;
            report.delete.push(FileEntry::with_src(rel.as_str(), FileType::Blob, &full));
        }
    }
    Ok(report)
}

/// Rename a path within a tree, returning tree writes for the move.
///
/// Handles both single-file renames and directory renames (moving all
/// children). Each returned entry is either a deletion (`None`) of the
/// old path or a write (`Some(TreeWrite)`) at the new path.
///
/// # Arguments
/// * `repo` - The git repository.
/// * `base_tree` - Root tree OID of the current commit.
/// * `src` - Normalized source path in the tree.
/// * `dest` - Normalized destination path in the tree.
///
/// # Errors
/// Returns [`Error::NotFound`] if `src` does not exist in the tree.
pub fn rename(
    repo: &gix::Repository,
    base_tree: gix::ObjectId,
    src: &str,
    dest: &str,
) -> Result<Vec<(String, Option<TreeWrite>)>> {
    let src_norm = crate::paths::normalize_path(src)?;
    let dest_norm = crate::paths::normalize_path(dest)?;

    let entry = tree::entry_at_path(repo, base_tree, &src_norm)?
        .ok_or_else(|| Error::not_found(&src_norm))?;

    let mut writes = Vec::new();

    if entry.mode == MODE_TREE {
        // Rename directory: move all entries and delete originals
        let sub_entries = tree::walk_tree(repo, entry.oid)?;
        for (rel_path, we) in &sub_entries {
            let old_path = format!("{}/{}", src_norm, rel_path);
            let new_path = format!("{}/{}", dest_norm, rel_path);
            let obj = repo.find_object(we.oid).map_err(Error::git)?;
            // Delete old path
            writes.push((old_path, None));
            // Write new path
            writes.push((
                new_path,
                Some(TreeWrite {
                    data: obj.data.to_vec(),
                    oid: we.oid,
                    mode: we.mode,
                }),
            ));
        }
    } else {
        // Rename single file: delete old, write new
        let obj = repo.find_object(entry.oid).map_err(Error::git)?;
        writes.push((src_norm, None));
        writes.push((
            dest_norm,
            Some(TreeWrite {
                data: obj.data.to_vec(),
                oid: entry.oid,
                mode: entry.mode,
            }),
        ));
    }

    Ok(writes)
}

/// Recursively list all files under `root`, filtered by include/exclude
/// glob patterns. Returns sorted relative paths.
///
/// # Arguments
/// * `root` - Directory to walk.
/// * `include` - Optional glob patterns; only matching files are returned.
/// * `exclude` - Optional glob patterns; matching files are excluded.
pub fn disk_glob(
    root: &Path,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
) -> Result<Vec<String>> {
    let mut results = Vec::new();
    walk_disk(root, root, &mut results)?;

    // Filter by include/exclude
    if include.is_some() || exclude.is_some() {
        results.retain(|path| matches_filters(path, include, exclude));
    }

    results.sort();
    Ok(results)
}

fn walk_disk(root: &Path, dir: &Path, results: &mut Vec<String>) -> Result<()> {
    let read_dir = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(Error::io(dir, e)),
    };

    for entry in read_dir {
        let entry = entry.map_err(|e| Error::io(dir, e))?;
        let path = entry.path();
        let meta = std::fs::symlink_metadata(&path).map_err(|e| Error::io(&path, e))?;

        if meta.is_dir() {
            walk_disk(root, &path, results)?;
        } else {
            let rel = path
                .strip_prefix(root)
                .unwrap_or(&path)
                .to_string_lossy()
                .into_owned();
            results.push(rel);
        }
    }
    Ok(())
}

fn matches_filters(path: &str, include: Option<&[&str]>, exclude: Option<&[&str]>) -> bool {
    if let Some(patterns) = include {
        if !patterns.iter().any(|pat| path_matches_glob(path, pat)) {
            return false;
        }
    }
    if let Some(patterns) = exclude {
        if patterns.iter().any(|pat| path_matches_glob(path, pat)) {
            return false;
        }
    }
    true
}

fn path_matches_glob(path: &str, pattern: &str) -> bool {
    // Simple: match the filename part against the pattern
    let filename = path.rsplit('/').next().unwrap_or(path);
    crate::glob::glob_match(pattern, filename) || crate::glob::glob_match(pattern, path)
}

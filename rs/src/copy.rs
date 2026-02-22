use std::path::Path;

use crate::error::{Error, Result};
use crate::fs::TreeWrite;
use crate::tree;
use crate::types::{ChangeReport, MODE_BLOB, MODE_LINK, MODE_TREE};

/// Copy files from disk into a tree, returning a list of (path, TreeWrite) pairs.
pub fn copy_in(
    repo: &gix::Repository,
    _base_tree: gix::ObjectId,
    src: &Path,
    dest: &str,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
) -> Result<(Vec<(String, TreeWrite)>, ChangeReport)> {
    let mut writes = Vec::new();
    let mut report = ChangeReport::new();
    let dest_norm = crate::paths::normalize_path(dest)?;

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

        let blob_oid = repo.write_blob(&data).map_err(Error::git)?;
        writes.push((
            store_path.clone(),
            TreeWrite {
                data,
                oid: blob_oid.detach(),
                mode,
            },
        ));
        report.add.push(store_path);
    }

    Ok((writes, report))
}

/// Copy files from a tree to disk.
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

        report.add.push(rel_path.clone());
    }

    Ok(report)
}

/// Sync files from disk into a tree (add + update + delete).
pub fn sync_in(
    repo: &gix::Repository,
    base_tree: gix::ObjectId,
    src: &Path,
    dest: &str,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
) -> Result<(Vec<(String, TreeWrite)>, ChangeReport)> {
    // For now, just delegate to copy_in (full sync would also delete)
    copy_in(repo, base_tree, src, dest, include, exclude)
}

/// Sync files from a tree to disk (add + update + delete).
pub fn sync_out(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    src: &str,
    dest: &Path,
    include: Option<&[&str]>,
    exclude: Option<&[&str]>,
) -> Result<ChangeReport> {
    copy_out(repo, tree_oid, src, dest, include, exclude)
}

/// Remove files from disk that match patterns.
pub fn remove(
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
            report.delete.push(rel.clone());
        }
    }
    Ok(report)
}

/// Rename a path within a tree, returning updated tree writes.
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

/// Glob files on disk, respecting include/exclude patterns.
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

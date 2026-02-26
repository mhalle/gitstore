use std::collections::BTreeMap;

use gix::objs::tree::{Entry, EntryKind, EntryMode};

use crate::error::{Error, Result};
use crate::types::{WalkDirEntry, WalkEntry, MODE_BLOB, MODE_BLOB_EXEC, MODE_LINK, MODE_TREE};

/// Result of looking up a single tree entry.
#[derive(Debug, Clone)]
pub struct TreeEntryResult {
    pub oid: gix::ObjectId,
    pub mode: u32,
}

/// Convert an EntryMode to our u32 representation.
pub(crate) fn mode_to_u32(mode: EntryMode) -> u32 {
    mode.value() as u32
}

/// Convert our u32 mode to an EntryMode.
pub(crate) fn u32_to_mode(mode: u32) -> EntryMode {
    EntryMode::try_from(mode).unwrap_or(EntryMode::from(EntryKind::Blob))
}

/// Return the `(oid, mode)` of the entry at `path`, or `None` if missing.
///
/// Walks the tree from `tree_oid` through each path segment. Returns `None`
/// when any segment is not found or an intermediate entry is not a tree.
///
/// # Arguments
/// * `repo` - The git repository.
/// * `tree_oid` - Root tree to search from.
/// * `path` - Normalized forward-slash path (e.g. `"dir/file.txt"`).
pub fn entry_at_path(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    path: &str,
) -> Result<Option<TreeEntryResult>> {
    let path = crate::paths::normalize_path(path)?;
    if path.is_empty() {
        return Ok(Some(TreeEntryResult {
            oid: tree_oid,
            mode: MODE_TREE,
        }));
    }

    let segments: Vec<&str> = path.split('/').collect();
    let mut current_oid = tree_oid;

    for (i, segment) in segments.iter().enumerate() {
        let tree_data = repo.find_object(current_oid).map_err(Error::git)?;
        let tree_ref = gix::objs::TreeRef::from_bytes(&tree_data.data).map_err(Error::git)?;

        let found = tree_ref
            .entries
            .iter()
            .find(|e| e.filename == segment.as_bytes());

        match found {
            Some(entry) => {
                let entry_mode = mode_to_u32(entry.mode);
                let entry_oid = entry.oid.to_owned();

                if i == segments.len() - 1 {
                    // Last segment — return this entry
                    return Ok(Some(TreeEntryResult {
                        oid: entry_oid,
                        mode: entry_mode,
                    }));
                } else {
                    // Intermediate segment — must be a tree
                    if entry_mode != MODE_TREE {
                        return Ok(None);
                    }
                    current_oid = entry_oid;
                }
            }
            None => return Ok(None),
        }
    }

    Ok(None)
}

/// Walk to a path within a tree, returning every entry along the way.
///
/// Unlike [`entry_at_path`], this returns the full chain of
/// [`TreeEntryResult`] objects from the first segment to the last.
///
/// # Errors
/// Returns [`Error::NotFound`] if a segment is missing, or
/// [`Error::NotADirectory`] if an intermediate entry is not a tree.
pub fn walk_to(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    path: &str,
) -> Result<Vec<TreeEntryResult>> {
    let path = crate::paths::normalize_path(path)?;
    if path.is_empty() {
        return Ok(vec![TreeEntryResult {
            oid: tree_oid,
            mode: MODE_TREE,
        }]);
    }

    let segments: Vec<&str> = path.split('/').collect();
    let mut current_oid = tree_oid;
    let mut results = Vec::new();

    for (i, segment) in segments.iter().enumerate() {
        let tree_data = repo.find_object(current_oid).map_err(Error::git)?;
        let tree_ref = gix::objs::TreeRef::from_bytes(&tree_data.data).map_err(Error::git)?;

        let found = tree_ref
            .entries
            .iter()
            .find(|e| e.filename == segment.as_bytes());

        match found {
            Some(entry) => {
                let entry_mode = mode_to_u32(entry.mode);
                let entry_oid = entry.oid.to_owned();

                results.push(TreeEntryResult {
                    oid: entry_oid,
                    mode: entry_mode,
                });

                if i < segments.len() - 1 {
                    if entry_mode != MODE_TREE {
                        return Err(Error::not_a_directory(segments[..=i].join("/")));
                    }
                    current_oid = entry_oid;
                }
            }
            None => {
                return Err(Error::not_found(segments[..=i].join("/")));
            }
        }
    }

    Ok(results)
}

/// Read a blob at a given path in the tree, returning its raw bytes.
///
/// # Errors
/// Returns [`Error::IsADirectory`] if the path points to a tree,
/// [`Error::NotFound`] if the path does not exist.
pub fn read_blob_at_path(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    path: &str,
) -> Result<Vec<u8>> {
    let results = walk_to(repo, tree_oid, path)?;
    let last = results
        .last()
        .ok_or_else(|| Error::not_found(path))?;

    if last.mode == MODE_TREE {
        return Err(Error::is_a_directory(path));
    }

    let obj = repo.find_object(last.oid).map_err(Error::git)?;
    Ok(obj.data.to_vec())
}

/// List the immediate children of a tree at the given path.
///
/// Returns [`WalkEntry`] objects with `name`, `oid`, and `mode` for each
/// child. Pass an empty or root path to list the top-level tree.
///
/// # Errors
/// Returns [`Error::NotFound`] if the path does not exist, or
/// [`Error::NotADirectory`] if it is not a tree.
pub fn list_tree_at_path(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    path: &str,
) -> Result<Vec<WalkEntry>> {
    let target_oid = if crate::paths::is_root_path(path) {
        tree_oid
    } else {
        let entry = entry_at_path(repo, tree_oid, path)?
            .ok_or_else(|| Error::not_found(path))?;
        if entry.mode != MODE_TREE {
            return Err(Error::not_a_directory(path));
        }
        entry.oid
    };

    let tree_data = repo.find_object(target_oid).map_err(Error::git)?;
    let tree_ref = gix::objs::TreeRef::from_bytes(&tree_data.data).map_err(Error::git)?;

    let mut entries = Vec::new();
    for e in &tree_ref.entries {
        entries.push(WalkEntry {
            name: String::from_utf8_lossy(e.filename).into_owned(),
            oid: e.oid.to_owned(),
            mode: mode_to_u32(e.mode),
        });
    }
    Ok(entries)
}

/// List all entries recursively under the given path.
///
/// Returns a flat list of non-tree [`WalkEntry`] items with their names
/// (basenames, not full paths). Directories are traversed but not included
/// in the output.
pub fn list_entries_at_path(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    path: &str,
) -> Result<Vec<WalkEntry>> {
    let target_oid = if crate::paths::is_root_path(path) {
        tree_oid
    } else {
        let entry = entry_at_path(repo, tree_oid, path)?
            .ok_or_else(|| Error::not_found(path))?;
        if entry.mode != MODE_TREE {
            return Err(Error::not_a_directory(path));
        }
        entry.oid
    };

    let entries = walk_tree(repo, target_oid)?;
    Ok(entries.into_iter().map(|(_path, entry)| entry).collect())
}

/// Recursively walk a tree, returning all non-tree entries with full paths.
///
/// Each element is a `(full_path, WalkEntry)` pair where `full_path` is
/// the slash-separated path from the tree root (e.g. `"dir/sub/file.txt"`).
pub fn walk_tree(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
) -> Result<Vec<(String, WalkEntry)>> {
    let mut results = Vec::new();
    walk_tree_recursive(repo, tree_oid, "", &mut results)?;
    Ok(results)
}

fn walk_tree_recursive(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    prefix: &str,
    results: &mut Vec<(String, WalkEntry)>,
) -> Result<()> {
    let tree_data = repo.find_object(tree_oid).map_err(Error::git)?;
    let tree_ref = gix::objs::TreeRef::from_bytes(&tree_data.data).map_err(Error::git)?;

    for e in &tree_ref.entries {
        let name = String::from_utf8_lossy(e.filename).into_owned();
        let full_path = if prefix.is_empty() {
            name.clone()
        } else {
            format!("{}/{}", prefix, name)
        };
        let entry_mode = mode_to_u32(e.mode);
        let entry_oid = e.oid.to_owned();

        if entry_mode == MODE_TREE {
            walk_tree_recursive(repo, entry_oid, &full_path, results)?;
        } else {
            results.push((
                full_path,
                WalkEntry {
                    name,
                    oid: entry_oid,
                    mode: entry_mode,
                },
            ));
        }
    }
    Ok(())
}

/// os.walk-style directory traversal: returns one [`WalkDirEntry`] per directory.
///
/// Each entry contains the directory path, a list of subdirectory names, and
/// a list of non-directory [`WalkEntry`] items (files, symlinks).
pub fn walk_tree_dirs(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
) -> Result<Vec<WalkDirEntry>> {
    let mut results = Vec::new();
    walk_tree_dirs_recursive(repo, tree_oid, "", &mut results)?;
    Ok(results)
}

fn walk_tree_dirs_recursive(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    prefix: &str,
    results: &mut Vec<WalkDirEntry>,
) -> Result<()> {
    let tree_data = repo.find_object(tree_oid).map_err(Error::git)?;
    let tree_ref = gix::objs::TreeRef::from_bytes(&tree_data.data).map_err(Error::git)?;

    let mut entry = WalkDirEntry {
        dirpath: prefix.to_string(),
        dirnames: Vec::new(),
        files: Vec::new(),
    };

    let mut subdirs: Vec<(String, gix::ObjectId)> = Vec::new();

    for e in &tree_ref.entries {
        let name = String::from_utf8_lossy(e.filename).into_owned();
        let entry_mode = mode_to_u32(e.mode);
        let entry_oid = e.oid.to_owned();

        if entry_mode == MODE_TREE {
            entry.dirnames.push(name.clone());
            subdirs.push((name, entry_oid));
        } else {
            entry.files.push(WalkEntry {
                name,
                oid: entry_oid,
                mode: entry_mode,
            });
        }
    }

    results.push(entry);

    for (dname, doid) in subdirs {
        let sub_prefix = if prefix.is_empty() {
            dname
        } else {
            format!("{}/{}", prefix, dname)
        };
        walk_tree_dirs_recursive(repo, doid, &sub_prefix, results)?;
    }

    Ok(())
}

/// Check whether an entry exists at the given path in the tree.
///
/// Returns `Ok(true)` if the path resolves to any object (blob, tree,
/// symlink), `Ok(false)` if not found.
pub fn exists_at_path(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    path: &str,
) -> Result<bool> {
    Ok(entry_at_path(repo, tree_oid, path)?.is_some())
}

/// Count immediate subdirectory entries in a tree (no recursion).
///
/// Used to compute `nlink` for directory stat results.
pub fn count_subdirs(repo: &gix::Repository, tree_oid: gix::ObjectId) -> Result<u32> {
    let tree_data = repo.find_object(tree_oid).map_err(Error::git)?;
    let tree_ref = gix::objs::TreeRef::from_bytes(&tree_data.data).map_err(Error::git)?;
    let count = tree_ref
        .entries
        .iter()
        .filter(|e| mode_to_u32(e.mode) == MODE_TREE)
        .count();
    Ok(count as u32)
}

/// Rebuild a tree by applying writes and deletes.
///
/// Only the ancestor chain from changed leaves to root is rebuilt;
/// sibling subtrees are shared by hash reference. Empty directories
/// are automatically pruned.
///
/// # Arguments
/// * `repo` - The git repository.
/// * `base_tree` - OID of the existing tree (null OID for empty).
/// * `writes` - Slice of `(path, Option<TreeWrite>)`. `Some` means add/update,
///   `None` means delete.
///
/// # Returns
/// OID of the new root tree.
pub fn rebuild_tree(
    repo: &gix::Repository,
    base_tree: gix::ObjectId,
    writes: &[(String, Option<crate::fs::TreeWrite>)],
) -> Result<gix::ObjectId> {
    // Group writes by first path segment
    let mut leaf_writes: BTreeMap<String, &crate::fs::TreeWrite> = BTreeMap::new();
    let mut leaf_removes: Vec<String> = Vec::new();
    let mut sub_writes: BTreeMap<String, Vec<(String, Option<&crate::fs::TreeWrite>)>> =
        BTreeMap::new();

    for (path, tw) in writes {
        if let Some(slash) = path.find('/') {
            let dir = &path[..slash];
            let rest = &path[slash + 1..];
            sub_writes
                .entry(dir.to_string())
                .or_default()
                .push((rest.to_string(), tw.as_ref()));
        } else {
            match tw {
                Some(tw) => {
                    leaf_writes.insert(path.clone(), tw);
                }
                None => {
                    leaf_removes.push(path.clone());
                }
            }
        }
    }

    // Load base tree entries into a sorted map
    let mut entries: BTreeMap<String, (gix::ObjectId, u32)> = BTreeMap::new();

    // Check if this is a null OID (empty tree)
    let is_null = base_tree.is_null();
    if !is_null {
        if let Ok(tree_data) = repo.find_object(base_tree) {
            if let Ok(tree_ref) = gix::objs::TreeRef::from_bytes(&tree_data.data) {
                for e in &tree_ref.entries {
                    let name = String::from_utf8_lossy(e.filename).into_owned();
                    entries.insert(name, (e.oid.to_owned(), mode_to_u32(e.mode)));
                }
            }
        }
    }

    // Apply leaf writes
    for (name, tw) in &leaf_writes {
        entries.insert(name.clone(), (tw.oid, tw.mode));
    }

    // Apply leaf removes
    for name in &leaf_removes {
        entries.remove(name);
    }

    // Recurse into subdirectories
    for (dir, sub_changes) in &sub_writes {
        let existing_subtree = entries
            .get(dir)
            .and_then(|(oid, mode)| {
                if *mode == MODE_TREE {
                    Some(*oid)
                } else {
                    None
                }
            })
            .unwrap_or(gix::ObjectId::null(gix::hash::Kind::Sha1));

        // If there's a non-tree entry at this name, remove it (blob→tree transition)
        if let Some((_, mode)) = entries.get(dir) {
            if *mode != MODE_TREE {
                entries.remove(dir);
            }
        }

        // Convert sub_changes to owned format for recursion
        let owned_writes: Vec<(String, Option<crate::fs::TreeWrite>)> = sub_changes
            .iter()
            .map(|(path, tw)| (path.clone(), tw.cloned()))
            .collect();

        let new_subtree_oid = rebuild_tree(repo, existing_subtree, &owned_writes)?;

        // Check if result tree is empty (prune)
        let subtree_data = repo.find_object(new_subtree_oid).map_err(Error::git)?;
        let subtree_ref =
            gix::objs::TreeRef::from_bytes(&subtree_data.data).map_err(Error::git)?;

        if subtree_ref.entries.is_empty() {
            entries.remove(dir);
        } else {
            entries.insert(dir.clone(), (new_subtree_oid, MODE_TREE));
        }
    }

    // Build and write new tree
    let tree_entries: Vec<Entry> = entries
        .iter()
        .map(|(name, (oid, mode))| Entry {
            mode: u32_to_mode(*mode),
            filename: name.as_str().into(),
            oid: *oid,
        })
        .collect();

    let tree = gix::objs::Tree {
        entries: tree_entries,
    };
    let tree_oid = repo.write_object(&tree).map_err(Error::git)?;
    Ok(tree_oid.detach())
}

/// Determine the git filemode for a file on disk.
///
/// Returns [`MODE_LINK`] for symlinks, [`MODE_BLOB_EXEC`] for executable
/// files (Unix only), or [`MODE_BLOB`] otherwise.
pub fn mode_from_disk(path: &std::path::Path) -> Result<u32> {
    let meta = std::fs::symlink_metadata(path).map_err(|e| Error::io(path, e))?;
    if meta.file_type().is_symlink() {
        return Ok(MODE_LINK);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if meta.permissions().mode() & 0o111 != 0 {
            return Ok(MODE_BLOB_EXEC);
        }
    }
    Ok(MODE_BLOB)
}

use std::collections::BTreeMap;

use gix::objs::tree::{Entry, EntryKind, EntryMode};

use crate::error::{Error, Result};
use crate::types::{WalkEntry, MODE_BLOB, MODE_BLOB_EXEC, MODE_LINK, MODE_TREE};

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

/// Get the entry (oid + mode) at a specific path in a tree.
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

/// Walk to a path within a tree, returning each intermediate tree oid.
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

/// Read a blob at a given path, returning its bytes.
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

/// List all entries (recursive) under the given path.
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

/// Recursively walk a tree, yielding all entries with full paths.
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

/// Check whether an entry exists at a path in the tree.
pub fn exists_at_path(
    repo: &gix::Repository,
    tree_oid: gix::ObjectId,
    path: &str,
) -> Result<bool> {
    Ok(entry_at_path(repo, tree_oid, path)?.is_some())
}

/// Count the number of immediate subdirectories in a tree.
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

/// Rebuild a tree by applying a set of writes (add/update/delete).
/// `None` in the value position means delete.
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
            .map(|(path, tw)| (path.clone(), tw.map(|tw| tw.clone())))
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

/// Determine the git mode for a file on disk.
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

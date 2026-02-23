//! Git notes support: per-namespace mapping of commit hashes to note text.
//!
//! Notes live at `refs/notes/<namespace>`, mapping commit hashes to UTF-8
//! text blobs. Reads handle both flat (40-char filename) and 2/38 fanout
//! layouts. Writes always use flat.

use std::collections::BTreeMap;
use std::sync::Arc;

use gix::objs::tree::{Entry, EntryKind, EntryMode};

use crate::error::{Error, Result};
use crate::lock::with_repo_lock;
use crate::store::{GitStore, GitStoreInner};
use crate::types::{MODE_BLOB, MODE_TREE};

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

fn validate_hash(h: &str) -> Result<()> {
    if h.len() != 40 || !h.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()) {
        return Err(Error::invalid_hash(h));
    }
    Ok(())
}

fn is_hex40(s: &str) -> bool {
    s.len() == 40 && s.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}

// ---------------------------------------------------------------------------
// NoteNamespace
// ---------------------------------------------------------------------------

/// One git notes namespace, backed by `refs/notes/<name>`.
///
/// Maps 40-char hex commit hashes to UTF-8 note text.
#[derive(Clone)]
pub struct NoteNamespace {
    inner: Arc<GitStoreInner>,
    namespace: String,
    ref_name: String,
}

impl NoteNamespace {
    pub(crate) fn new(inner: Arc<GitStoreInner>, namespace: &str) -> Self {
        Self {
            inner,
            namespace: namespace.to_string(),
            ref_name: format!("refs/notes/{}", namespace),
        }
    }

    fn with_repo<F, T>(&self, f: F) -> Result<T>
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

    // -- internal helpers ------------------------------------------------

    fn tip_oid(&self, repo: &gix::Repository) -> Result<Option<gix::ObjectId>> {
        match repo.find_reference(&self.ref_name) {
            Ok(r) => Ok(Some(r.id().detach())),
            Err(_) => Ok(None),
        }
    }

    fn tree_oid(&self, repo: &gix::Repository) -> Result<Option<gix::ObjectId>> {
        let tip = self.tip_oid(repo)?;
        match tip {
            None => Ok(None),
            Some(oid) => {
                let data = repo.find_object(oid).map_err(Error::git)?;
                let commit =
                    gix::objs::CommitRef::from_bytes(&data.data).map_err(Error::git)?;
                Ok(Some(commit.tree()))
            }
        }
    }

    /// Read tree entries into a BTreeMap.
    fn read_tree_entries(
        &self,
        repo: &gix::Repository,
        tree_oid: gix::ObjectId,
    ) -> Result<Vec<(String, gix::ObjectId, u32)>> {
        let data = repo.find_object(tree_oid).map_err(Error::git)?;
        let tree = gix::objs::TreeRef::from_bytes(&data.data).map_err(Error::git)?;
        let mut entries = Vec::new();
        for e in &tree.entries {
            let name = String::from_utf8_lossy(e.filename).into_owned();
            let mode = e.mode.value() as u32;
            entries.push((name, e.oid.to_owned(), mode));
        }
        Ok(entries)
    }

    /// Find the blob OID for `hash` in a tree, handling flat and fanout.
    fn find_note_in_tree(
        &self,
        repo: &gix::Repository,
        tree_oid: gix::ObjectId,
        hash: &str,
    ) -> Result<Option<gix::ObjectId>> {
        let entries = self.read_tree_entries(repo, tree_oid)?;

        // Try flat: entry named by full 40-char hash
        for (name, oid, mode) in &entries {
            if name == hash && *mode != MODE_TREE {
                return Ok(Some(*oid));
            }
        }

        // Try 2/38 fanout
        let prefix = &hash[..2];
        let suffix = &hash[2..];
        for (name, oid, mode) in &entries {
            if name == prefix && *mode == MODE_TREE {
                let sub_entries = self.read_tree_entries(repo, *oid)?;
                for (sub_name, sub_oid, _) in &sub_entries {
                    if sub_name == suffix {
                        return Ok(Some(*sub_oid));
                    }
                }
            }
        }

        Ok(None)
    }

    /// Iterate all (hash, blob_oid) pairs from the tree.
    fn iter_notes(
        &self,
        repo: &gix::Repository,
        tree_oid: gix::ObjectId,
    ) -> Result<Vec<(String, gix::ObjectId)>> {
        let entries = self.read_tree_entries(repo, tree_oid)?;
        let mut result = Vec::new();

        for (name, oid, mode) in &entries {
            if *mode == MODE_TREE && name.len() == 2 {
                // Fanout subtree
                let sub_entries = self.read_tree_entries(repo, *oid)?;
                for (sub_name, sub_oid, _) in &sub_entries {
                    let full = format!("{}{}", name, sub_name);
                    if is_hex40(&full) {
                        result.push((full, *sub_oid));
                    }
                }
            } else if is_hex40(name) {
                result.push((name.clone(), *oid));
            }
        }

        Ok(result)
    }

    /// Build a new note tree from a base tree + writes + deletes.
    fn build_note_tree(
        &self,
        repo: &gix::Repository,
        base_tree_oid: Option<gix::ObjectId>,
        writes: &[(String, String)], // (hash, text)
        deletes: &[String],
    ) -> Result<gix::ObjectId> {
        // Load existing tree entries
        let mut tree_map: BTreeMap<String, (gix::ObjectId, u32)> = BTreeMap::new();

        if let Some(tree_oid) = base_tree_oid {
            let entries = self.read_tree_entries(repo, tree_oid)?;
            for (name, oid, mode) in entries {
                tree_map.insert(name, (oid, mode));
            }
        }

        // Process deletes
        for h in deletes {
            let mut removed = false;

            // Try flat removal
            if let Some((_, mode)) = tree_map.get(h) {
                if *mode != MODE_TREE {
                    tree_map.remove(h);
                    removed = true;
                }
            }

            // Try fanout removal
            if !removed {
                let prefix = &h[..2];
                let suffix = &h[2..];
                if let Some((sub_oid, mode)) = tree_map.get(prefix).copied() {
                    if mode == MODE_TREE {
                        let sub_entries = self.read_tree_entries(repo, sub_oid)?;
                        let has_suffix = sub_entries.iter().any(|(n, _, _)| n == suffix);
                        if has_suffix {
                            let new_sub: Vec<_> = sub_entries
                                .into_iter()
                                .filter(|(n, _, _)| n != suffix)
                                .collect();
                            if new_sub.is_empty() {
                                tree_map.remove(prefix);
                            } else {
                                let new_sub_oid = self.write_flat_tree(repo, &new_sub)?;
                                tree_map.insert(prefix.to_string(), (new_sub_oid, MODE_TREE));
                            }
                            removed = true;
                        }
                    }
                }
            }

            if !removed {
                return Err(Error::key_not_found(h.as_str()));
            }
        }

        // Process writes (flat, clearing fanout if present)
        for (h, text) in writes {
            let blob_oid = repo.write_blob(text.as_bytes()).map_err(Error::git)?.detach();

            // Remove fanout entry if present
            if base_tree_oid.is_some() {
                let prefix = &h[..2];
                let suffix = &h[2..];
                if let Some((sub_oid, mode)) = tree_map.get(prefix).copied() {
                    if mode == MODE_TREE {
                        let sub_entries = self.read_tree_entries(repo, sub_oid)?;
                        if sub_entries.iter().any(|(n, _, _)| n == suffix) {
                            let new_sub: Vec<_> = sub_entries
                                .into_iter()
                                .filter(|(n, _, _)| n != suffix)
                                .collect();
                            if new_sub.is_empty() {
                                tree_map.remove(prefix);
                            } else {
                                let new_sub_oid = self.write_flat_tree(repo, &new_sub)?;
                                tree_map.insert(prefix.to_string(), (new_sub_oid, MODE_TREE));
                            }
                        }
                    }
                }
            }

            // Write flat entry
            tree_map.insert(h.clone(), (blob_oid, MODE_BLOB));
        }

        // Build and write final tree
        let tree_entries: Vec<Entry> = tree_map
            .iter()
            .map(|(name, (oid, mode))| Entry {
                mode: EntryMode::try_from(*mode).unwrap_or(EntryMode::from(EntryKind::Blob)),
                filename: name.as_str().into(),
                oid: *oid,
            })
            .collect();

        let tree = gix::objs::Tree {
            entries: tree_entries,
        };
        Ok(repo.write_object(&tree).map_err(Error::git)?.detach())
    }

    /// Write a flat tree from (name, oid, mode) entries.
    fn write_flat_tree(
        &self,
        repo: &gix::Repository,
        entries: &[(String, gix::ObjectId, u32)],
    ) -> Result<gix::ObjectId> {
        let tree_entries: Vec<Entry> = entries
            .iter()
            .map(|(name, oid, mode)| Entry {
                mode: EntryMode::try_from(*mode).unwrap_or(EntryMode::from(EntryKind::Blob)),
                filename: name.as_str().into(),
                oid: *oid,
            })
            .collect();
        let tree = gix::objs::Tree {
            entries: tree_entries,
        };
        Ok(repo.write_object(&tree).map_err(Error::git)?.detach())
    }

    /// Commit a new tree to the notes ref under repo lock.
    fn commit_note_tree(&self, new_tree_oid: gix::ObjectId, message: &str) -> Result<()> {
        with_repo_lock(&self.inner.path, || {
            let repo = self
                .inner
                .repo
                .lock()
                .map_err(|e| Error::git_msg(e.to_string()))?;

            // Re-read tip inside lock
            let parents: Vec<gix::ObjectId> = match self.tip_oid(&repo)? {
                Some(oid) => vec![oid],
                None => vec![],
            };

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

            let commit = gix::objs::Commit {
                tree: new_tree_oid,
                parents: parents.into(),
                author: actor.clone(),
                committer: actor,
                encoding: None,
                message: format!("{}\n", message).into(),
                extra_headers: vec![],
            };
            let commit_oid = repo.write_object(&commit).map_err(Error::git)?;

            use gix::refs::transaction::PreviousValue;
            repo.reference(
                self.ref_name.as_str(),
                commit_oid,
                PreviousValue::Any,
                message,
            )
            .map_err(Error::git)?;

            Ok(())
        })
    }

    // -- public API ------------------------------------------------------

    /// Get the note text for `hash`.
    pub fn get(&self, hash: &str) -> Result<String> {
        validate_hash(hash)?;
        self.with_repo(|repo| {
            let tree_oid = self
                .tree_oid(repo)?
                .ok_or_else(|| Error::key_not_found(hash))?;
            let blob_oid = self
                .find_note_in_tree(repo, tree_oid, hash)?
                .ok_or_else(|| Error::key_not_found(hash))?;
            let data = repo.find_object(blob_oid).map_err(Error::git)?;
            String::from_utf8(data.data.to_vec())
                .map_err(|e| Error::git_msg(e.to_string()))
        })
    }

    /// Set a note on `hash`. Creates or updates; each call = 1 commit.
    pub fn set(&self, hash: &str, text: &str) -> Result<()> {
        validate_hash(hash)?;
        let new_tree_oid = self.with_repo(|repo| {
            let tree_oid = self.tree_oid(repo)?;
            self.build_note_tree(repo, tree_oid, &[(hash.to_string(), text.to_string())], &[])
        })?;
        self.commit_note_tree(
            new_tree_oid,
            &format!("Notes added by 'git notes' on {}", &hash[..7]),
        )
    }

    /// Delete the note for `hash`.
    pub fn delete(&self, hash: &str) -> Result<()> {
        validate_hash(hash)?;
        let new_tree_oid = self.with_repo(|repo| {
            let tree_oid = self
                .tree_oid(repo)?
                .ok_or_else(|| Error::key_not_found(hash))?;
            self.build_note_tree(repo, Some(tree_oid), &[], &[hash.to_string()])
        })?;
        self.commit_note_tree(
            new_tree_oid,
            &format!("Notes removed by 'git notes' on {}", &hash[..7]),
        )
    }

    /// Check whether a note exists for `hash`.
    pub fn has(&self, hash: &str) -> Result<bool> {
        validate_hash(hash)?;
        self.with_repo(|repo| {
            let tree_oid = match self.tree_oid(repo)? {
                Some(oid) => oid,
                None => return Ok(false),
            };
            Ok(self.find_note_in_tree(repo, tree_oid, hash)?.is_some())
        })
    }

    /// List all hashes that have notes (sorted).
    pub fn list(&self) -> Result<Vec<String>> {
        self.with_repo(|repo| {
            let tree_oid = match self.tree_oid(repo)? {
                Some(oid) => oid,
                None => return Ok(vec![]),
            };
            let notes = self.iter_notes(repo, tree_oid)?;
            let mut hashes: Vec<String> = notes.into_iter().map(|(h, _)| h).collect();
            hashes.sort();
            Ok(hashes)
        })
    }

    /// Count notes in this namespace.
    pub fn len(&self) -> Result<usize> {
        self.with_repo(|repo| {
            let tree_oid = match self.tree_oid(repo)? {
                Some(oid) => oid,
                None => return Ok(0),
            };
            let notes = self.iter_notes(repo, tree_oid)?;
            Ok(notes.len())
        })
    }

    /// Whether this namespace has no notes.
    pub fn is_empty(&self) -> Result<bool> {
        Ok(self.len()? == 0)
    }

    /// Get the note for the current HEAD commit.
    pub fn get_for_current_branch(&self, store: &GitStore) -> Result<String> {
        let current = store
            .branches()
            .get_current()?
            .ok_or_else(|| Error::git_msg("HEAD is dangling — no current branch"))?;
        let hash = current
            .commit_hash()
            .ok_or_else(|| Error::git_msg("no commit hash on current branch"))?;
        self.get(&hash)
    }

    /// Set a note on the current HEAD commit.
    pub fn set_for_current_branch(&self, store: &GitStore, text: &str) -> Result<()> {
        let current = store
            .branches()
            .get_current()?
            .ok_or_else(|| Error::git_msg("HEAD is dangling — no current branch"))?;
        let hash = current
            .commit_hash()
            .ok_or_else(|| Error::git_msg("no commit hash on current branch"))?;
        self.set(&hash, text)
    }

    /// Create a batch for deferred writes.
    pub fn batch(&self) -> NotesBatch {
        NotesBatch {
            ns: self.clone(),
            writes: Vec::new(),
            deletes: Vec::new(),
        }
    }
}

impl std::fmt::Display for NoteNamespace {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "NoteNamespace('{}')", self.namespace)
    }
}

// ---------------------------------------------------------------------------
// NotesBatch
// ---------------------------------------------------------------------------

/// Collects note writes/deletes and applies them in one commit.
pub struct NotesBatch {
    ns: NoteNamespace,
    writes: Vec<(String, String)>,
    deletes: Vec<String>,
}

impl NotesBatch {
    /// Stage a note write.
    pub fn set(&mut self, hash: &str, text: &str) -> Result<()> {
        validate_hash(hash)?;
        self.deletes.retain(|h| h != hash);
        // Last-wins for writes
        self.writes.retain(|(h, _)| h != hash);
        self.writes.push((hash.to_string(), text.to_string()));
        Ok(())
    }

    /// Stage a note delete.
    pub fn delete(&mut self, hash: &str) -> Result<()> {
        validate_hash(hash)?;
        self.writes.retain(|(h, _)| h != hash);
        if !self.deletes.contains(&hash.to_string()) {
            self.deletes.push(hash.to_string());
        }
        Ok(())
    }

    /// Commit all accumulated changes. Consumes `self`.
    pub fn commit(self) -> Result<()> {
        if self.writes.is_empty() && self.deletes.is_empty() {
            return Ok(());
        }

        let new_tree_oid = self.ns.with_repo(|repo| {
            let tree_oid = self.ns.tree_oid(repo)?;
            self.ns
                .build_note_tree(repo, tree_oid, &self.writes, &self.deletes)
        })?;

        let count = self.writes.len() + self.deletes.len();
        self.ns.commit_note_tree(
            new_tree_oid,
            &format!("Notes batch update ({} changes)", count),
        )
    }
}

// ---------------------------------------------------------------------------
// NoteDict
// ---------------------------------------------------------------------------

/// Outer container for git notes namespaces on a [`GitStore`].
///
/// `store.notes().commits()` → default namespace (`refs/notes/commits`).
/// `store.notes().namespace("reviews")` → custom namespace.
pub struct NoteDict<'a> {
    store: &'a GitStore,
}

impl<'a> NoteDict<'a> {
    pub(crate) fn new(store: &'a GitStore) -> Self {
        Self { store }
    }

    /// The default `refs/notes/commits` namespace.
    pub fn commits(&self) -> NoteNamespace {
        NoteNamespace::new(Arc::clone(&self.store.inner), "commits")
    }

    /// A custom namespace.
    pub fn namespace(&self, name: &str) -> NoteNamespace {
        NoteNamespace::new(Arc::clone(&self.store.inner), name)
    }
}

impl std::fmt::Display for NoteDict<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "NoteDict({})", self.store.inner.path.display())
    }
}

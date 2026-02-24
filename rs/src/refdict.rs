use std::sync::Arc;

use crate::error::{Error, Result};
use crate::fs::Fs;
use crate::store::GitStore;
use crate::types::ReflogEntry;

/// A transient, borrowed view over a set of git references sharing a common
/// prefix (e.g. `refs/heads/` or `refs/tags/`).
///
/// `store.branches()` and `store.tags()` both return `RefDict` instances.
/// Branches yield writable [`Fs`] snapshots; tags yield read-only ones.
pub struct RefDict<'a> {
    store: &'a GitStore,
    prefix: &'static str,
}

impl<'a> RefDict<'a> {
    pub(crate) fn new(store: &'a GitStore, prefix: &'static str) -> Self {
        Self { store, prefix }
    }

    fn full_name(&self, name: &str) -> String {
        format!("{}{}", self.prefix, name)
    }

    /// Whether this RefDict is for branches (writable Fs) or tags (readonly).
    fn is_branch_prefix(&self) -> bool {
        self.prefix == "refs/heads/"
    }

    /// Whether this RefDict is for tags.
    fn is_tags(&self) -> bool {
        self.prefix == "refs/tags/"
    }

    /// Build an `Fs` from a resolved commit OID and ref name.
    fn fs_for_ref(&self, commit_oid: gix::ObjectId, name: &str) -> Result<Fs> {
        let writable = self.is_branch_prefix();
        Fs::from_commit(Arc::clone(&self.store.inner), commit_oid, Some(name.to_string()), Some(writable))
    }

    /// Get the [`Fs`] snapshot for the named branch or tag.
    ///
    /// Branches return a writable `Fs`; tags return a read-only `Fs`.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the ref does not exist.
    pub fn get(&self, name: &str) -> Result<Fs> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        let refname = self.full_name(name);
        let reference = repo
            .find_reference(refname.as_str())
            .map_err(|_| Error::not_found(format!("ref '{}' not found", name)))?;
        let commit_oid = reference.id().detach();
        drop(repo);
        self.fs_for_ref(commit_oid, name)
    }

    /// Point the named ref at the commit of `fs`.
    ///
    /// For branches, updates (or creates) the ref and writes a reflog entry.
    /// For tags, creates the ref but returns [`Error::KeyExists`] if the tag
    /// already exists (tags are immutable).
    ///
    /// # Arguments
    /// * `name` - Branch or tag name (e.g. `"main"`).
    /// * `fs` - The snapshot whose commit will become the ref target.
    ///
    /// # Errors
    /// * [`Error::InvalidRefName`] if `name` is not a valid git ref name.
    /// * [`Error::InvalidPath`] if `fs` belongs to a different repository.
    /// * [`Error::KeyExists`] if setting a tag that already exists.
    pub fn set(&self, name: &str, fs: &Fs) -> Result<()> {
        // 1. Validate ref name
        crate::paths::validate_ref_name(name)?;

        // 2. Same-repo check
        let same = Arc::ptr_eq(&self.store.inner, &fs.inner) || {
            let self_canon = std::fs::canonicalize(&self.store.inner.path).ok();
            let fs_canon = std::fs::canonicalize(&fs.inner.path).ok();
            self_canon.is_some() && self_canon == fs_canon
        };
        if !same {
            return Err(Error::invalid_path(
                "Fs belongs to a different repository".to_string(),
            ));
        }

        let commit_oid = fs
            .commit_oid
            .ok_or_else(|| Error::git_msg("Fs has no commit".to_string()))?;
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        let refname = self.full_name(name);

        // 3. Tag overwrite protection
        if self.is_tags() {
            if repo.find_reference(refname.as_str()).is_ok() {
                return Err(Error::key_exists(format!("tag '{}' already exists", name)));
            }
        }

        // Read old OID for reflog
        let old_oid = repo
            .find_reference(refname.as_str())
            .ok()
            .map(|r| r.id().detach());

        use gix::refs::transaction::PreviousValue;
        repo.reference(refname.as_str(), commit_oid, PreviousValue::Any, "refdict: set")
            .map_err(Error::git)?;

        // Write reflog entry
        let old_sha = old_oid
            .map(|o| format!("{}", o))
            .unwrap_or_else(|| crate::reflog::ZERO_SHA.to_string());
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        let _ = crate::reflog::write_reflog_entry(
            &self.store.inner.path,
            &refname,
            &ReflogEntry {
                old_sha,
                new_sha: format!("{}", commit_oid),
                committer: format!(
                    "{} <{}>",
                    self.store.inner.signature.name, self.store.inner.signature.email
                ),
                timestamp: now.as_secs(),
                message: format!("refdict: set {}", name),
            },
        );

        Ok(())
    }

    /// Point the named ref at the commit of `fs` and return a new writable [`Fs`]
    /// bound to the updated ref.
    ///
    /// Convenience wrapper: equivalent to calling [`set`](Self::set) followed by
    /// [`get`](Self::get).
    pub fn set_to(&self, name: &str, fs: &Fs) -> Result<Fs> {
        self.set(name, fs)?;
        self.get(name)
    }

    /// Point the named ref at the commit of `fs` and return the previous [`Fs`]
    /// (or `None` if the ref did not exist before).
    pub fn set_and_get(&self, name: &str, fs: &Fs) -> Result<Option<Fs>> {
        let old = self.try_get(name)?;
        self.set(name, fs)?;
        Ok(old)
    }

    /// Delete the named branch or tag.
    ///
    /// # Errors
    /// Returns a git error if the ref does not exist or cannot be deleted.
    pub fn delete(&self, name: &str) -> Result<()> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        let refname = self.full_name(name);

        use gix::refs::transaction::{Change, PreviousValue, RefEdit, RefLog};
        use gix::refs::FullName;

        let edit = RefEdit {
            change: Change::Delete {
                expected: PreviousValue::Any,
                log: RefLog::AndReference,
            },
            name: FullName::try_from(refname).map_err(|e| Error::git(e))?,
            deref: false,
        };
        repo.edit_reference(edit).map_err(Error::git)?;
        Ok(())
    }

    /// Returns `true` if the named branch or tag exists.
    pub fn has(&self, name: &str) -> Result<bool> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        let refname = self.full_name(name);
        Ok(repo.find_reference(refname.as_str()).is_ok())
    }

    /// List all ref short names under this prefix, sorted alphabetically.
    ///
    /// For branches this returns names like `["dev", "main"]`; for tags
    /// `["v1.0", "v2.0"]`.
    pub fn list(&self) -> Result<Vec<String>> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        let refs_platform = repo.references().map_err(Error::git)?;
        let mut names = Vec::new();
        for r in refs_platform.prefixed(self.prefix).map_err(Error::git)? {
            if let Ok(reference) = r {
                let full_name = reference.name().as_bstr().to_string();
                if let Some(short) = full_name.strip_prefix(self.prefix) {
                    names.push(short.to_string());
                }
            }
        }
        names.sort();
        Ok(names)
    }

    /// Return all `(name, Fs)` pairs, sorted by name.
    pub fn iter(&self) -> Result<Vec<(String, Fs)>> {
        let pairs = {
            let repo = self
                .store
                .inner
                .repo
                .lock()
                .map_err(|e| Error::git_msg(e.to_string()))?;

            let refs_platform = repo.references().map_err(Error::git)?;
            let mut raw_pairs = Vec::new();
            for r in refs_platform.prefixed(self.prefix).map_err(Error::git)? {
                if let Ok(reference) = r {
                    let full_name = reference.name().as_bstr().to_string();
                    if let Some(short) = full_name.strip_prefix(self.prefix) {
                        let oid = reference.id().detach();
                        raw_pairs.push((short.to_string(), oid));
                    }
                }
            }
            raw_pairs.sort_by(|a, b| a.0.cmp(&b.0));
            raw_pairs
        };

        let mut result = Vec::with_capacity(pairs.len());
        for (name, oid) in pairs {
            let fs = self.fs_for_ref(oid, &name)?;
            result.push((name, fs));
        }
        Ok(result)
    }

    /// Get the current branch name (HEAD symbolic target within this prefix).
    ///
    /// Returns `Ok(None)` when HEAD is detached or dangling.
    /// Always returns `Ok(None)` for tags (tags do not have a "current" concept).
    /// This is a cheap operation — it does not construct an [`Fs`] object.
    pub fn get_current_name(&self) -> Result<Option<String>> {
        if self.is_tags() {
            return Ok(None);
        }
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        match repo.find_reference("HEAD") {
            Ok(head) => match head.target().try_name() {
                Some(name) => {
                    let name_str = name.as_bstr().to_string();
                    Ok(name_str.strip_prefix(self.prefix).map(|s| s.to_string()))
                }
                None => Ok(None),
            },
            Err(_) => Ok(None),
        }
    }

    /// Get the [`Fs`] for the current (HEAD) branch.
    ///
    /// Returns `Ok(None)` if HEAD is dangling or detached, or for tags.
    pub fn get_current(&self) -> Result<Option<Fs>> {
        if self.is_tags() {
            return Ok(None);
        }
        match self.get_current_name()? {
            Some(name) => match self.get(&name) {
                Ok(fs) => Ok(Some(fs)),
                Err(_) => Ok(None),
            },
            None => Ok(None),
        }
    }

    /// Set the current branch (HEAD symbolic ref target).
    ///
    /// # Errors
    /// Returns [`Error::Permission`] for tags (tags have no current branch).
    pub fn set_current(&self, name: &str) -> Result<()> {
        if self.is_tags() {
            return Err(Error::permission("tags do not support set_current"));
        }
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        let target_refname = self.full_name(name);

        use gix::refs::transaction::{Change, LogChange, PreviousValue, RefEdit, RefLog};
        use gix::refs::{FullName, Target};

        let edit = RefEdit {
            change: Change::Update {
                log: LogChange {
                    mode: RefLog::AndReference,
                    force_create_reflog: false,
                    message: format!("set current: {}", name).into(),
                },
                expected: PreviousValue::Any,
                new: Target::Symbolic(
                    FullName::try_from(target_refname).map_err(|e| Error::git(e))?,
                ),
            },
            name: FullName::try_from("HEAD".to_string()).map_err(|e| Error::git(e))?,
            deref: false,
        };
        repo.edit_reference(edit).map_err(Error::git)?;
        Ok(())
    }

    /// Read the reflog entries for the named branch.
    ///
    /// Returns a list of [`ReflogEntry`] objects recording each branch movement.
    ///
    /// # Errors
    /// * [`Error::Permission`] for tags (tags do not have reflogs).
    /// * [`Error::NotFound`] if no reflog file exists for the branch.
    pub fn reflog(&self, name: &str) -> Result<Vec<ReflogEntry>> {
        if self.is_tags() {
            return Err(Error::permission("tags do not have reflogs"));
        }
        let refname = self.full_name(name);
        crate::reflog::read_reflog(&self.store.inner.path, &refname)
    }

    /// Internal: get ref as Option (for set_and_get).
    fn try_get(&self, name: &str) -> Result<Option<Fs>> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        let refname = self.full_name(name);
        match repo.find_reference(refname.as_str()) {
            Ok(reference) => {
                let commit_oid = reference.id().detach();
                drop(repo);
                Ok(Some(self.fs_for_ref(commit_oid, name)?))
            }
            Err(_) => Ok(None),
        }
    }
}

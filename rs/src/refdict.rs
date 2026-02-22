use std::sync::Arc;

use crate::error::{Error, Result};
use crate::fs::Fs;
use crate::store::GitStore;
use crate::types::ReflogEntry;

/// A transient, borrowed view over a set of git references sharing a common
/// prefix (e.g. `refs/heads/` or `refs/tags/`).
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

    /// Build an `Fs` from a resolved commit OID and ref name.
    fn fs_for_ref(&self, commit_oid: gix::ObjectId, name: &str) -> Result<Fs> {
        let branch = if self.is_branch_prefix() {
            Some(name.to_string())
        } else {
            None
        };
        Fs::from_commit(Arc::clone(&self.store.inner), commit_oid, branch)
    }

    /// Get the `Fs` for the named ref.
    ///
    /// Branches return a writable `Fs`; tags return a readonly (detached) `Fs`.
    /// Errors if the ref does not exist.
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
    pub fn set(&self, name: &str, fs: &Fs) -> Result<()> {
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

        use gix::refs::transaction::PreviousValue;
        repo.reference(refname.as_str(), commit_oid, PreviousValue::Any, "refdict: set")
            .map_err(Error::git)?;
        Ok(())
    }

    /// Point the named ref at the commit of `fs` and return a new writable `Fs`
    /// for the updated ref.
    pub fn set_to(&self, name: &str, fs: &Fs) -> Result<Fs> {
        self.set(name, fs)?;
        self.get(name)
    }

    /// Point the named ref at the commit of `fs` and return the previous `Fs`.
    pub fn set_and_get(&self, name: &str, fs: &Fs) -> Result<Option<Fs>> {
        let old = self.try_get(name)?;
        self.set(name, fs)?;
        Ok(old)
    }

    /// Delete the named ref.
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

    /// Returns `true` if the named ref exists.
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

    /// List all ref names under this prefix.
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

    /// Iterate over `(name, Fs)` pairs.
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

    /// Get the default ref (HEAD symbolic target within this prefix).
    pub fn get_default(&self) -> Result<Option<String>> {
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

    /// Set the default ref (HEAD symbolic target).
    pub fn set_default(&self, name: &str) -> Result<()> {
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
                    message: format!("set default: {}", name).into(),
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

    /// Read the reflog for the named ref.
    pub fn reflog(&self, name: &str) -> Result<Vec<ReflogEntry>> {
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

use crate::error::{Error, Result};
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

    /// Get the target of the named ref (hex SHA).
    pub fn get(&self, name: &str) -> Result<Option<String>> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        let refname = self.full_name(name);
        match repo.find_reference(refname.as_str()) {
            Ok(reference) => {
                let oid = reference.id().detach();
                Ok(Some(format!("{}", oid)))
            }
            Err(_) => Ok(None),
        }
    }

    /// Point the named ref at `target` (hex SHA).
    pub fn set(&self, name: &str, target: &str) -> Result<()> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;
        let refname = self.full_name(name);
        let oid = gix::ObjectId::from_hex(target.as_bytes()).map_err(Error::git)?;

        use gix::refs::transaction::PreviousValue;
        repo.reference(refname.as_str(), oid, PreviousValue::Any, "refdict: set")
            .map_err(Error::git)?;
        Ok(())
    }

    /// Point the named ref at `target` and return the previous value.
    pub fn set_and_get(&self, name: &str, target: &str) -> Result<Option<String>> {
        let old = self.get(name)?;
        self.set(name, target)?;
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
        Ok(self.get(name)?.is_some())
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

    /// Iterate over `(name, target)` pairs.
    pub fn iter(&self) -> Result<Vec<(String, String)>> {
        let repo = self
            .store
            .inner
            .repo
            .lock()
            .map_err(|e| Error::git_msg(e.to_string()))?;

        let refs_platform = repo.references().map_err(Error::git)?;
        let mut pairs = Vec::new();
        for r in refs_platform.prefixed(self.prefix).map_err(Error::git)? {
            if let Ok(reference) = r {
                let full_name = reference.name().as_bstr().to_string();
                if let Some(short) = full_name.strip_prefix(self.prefix) {
                    let oid = reference.id().detach();
                    pairs.push((short.to_string(), format!("{}", oid)));
                }
            }
        }
        pairs.sort_by(|a, b| a.0.cmp(&b.0));
        Ok(pairs)
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
}

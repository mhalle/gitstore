use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use crate::error::{Error, Result};
use crate::fs::Fs;
use crate::notes::NoteDict;
use crate::refdict::RefDict;
use crate::types::{MirrorDiff, OpenOptions, Signature};

/// Internal state shared via `Arc`.
pub(crate) struct GitStoreInner {
    pub(crate) repo: Mutex<gix::Repository>,
    pub(crate) path: PathBuf,
    pub(crate) signature: Signature,
}

impl std::fmt::Debug for GitStoreInner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("GitStoreInner")
            .field("path", &self.path)
            .field("signature", &self.signature)
            .finish_non_exhaustive()
    }
}

/// A versioned filesystem backed by a bare git repository.
///
/// Cheap to clone (`Arc` internally).
#[derive(Clone)]
pub struct GitStore {
    pub(crate) inner: Arc<GitStoreInner>,
}

impl GitStore {
    /// Open (or create) a bare git repository at `path`.
    ///
    /// # Arguments
    /// * `path` - Path to the bare repository.
    /// * `options` - [`OpenOptions`] controlling creation, branch name, and author.
    ///
    /// # Errors
    /// Returns [`Error::NotFound`] if the repository does not exist and
    /// `options.create` is `false`.
    pub fn open(path: impl AsRef<Path>, options: OpenOptions) -> Result<Self> {
        let path = path.as_ref().to_path_buf();

        let sig = Signature {
            name: options.author.unwrap_or_else(|| "vost".into()),
            email: options.email.unwrap_or_else(|| "vost@localhost".into()),
        };

        let repo = if path.exists() {
            gix::open(&path).map_err(Error::git)?
        } else if options.create {
            std::fs::create_dir_all(&path).map_err(|e| Error::io(&path, e))?;
            let repo = gix::init_bare(&path).map_err(Error::git)?;

            if let Some(ref branch) = options.branch {
                Self::init_branch(&repo, &path, branch, &sig)?;
            }

            repo
        } else {
            return Err(Error::not_found(format!(
                "repository not found: {}",
                path.display()
            )));
        };

        #[allow(clippy::arc_with_non_send_sync)]
        Ok(GitStore {
            inner: Arc::new(GitStoreInner {
                repo: Mutex::new(repo),
                path,
                signature: sig,
            }),
        })
    }

    /// Create the initial commit on `branch` with an empty tree.
    fn init_branch(repo: &gix::Repository, path: &std::path::Path, branch: &str, sig: &Signature) -> Result<()> {
        // Write empty tree
        let empty_tree = gix::objs::Tree { entries: vec![] };
        let tree_oid = repo.write_object(&empty_tree).map_err(Error::git)?;

        // Build commit
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        let time = gix::date::Time::new(now.as_secs() as gix::date::SecondsSinceUnixEpoch, 0);
        let actor = gix::actor::Signature {
            name: sig.name.clone().into(),
            email: sig.email.clone().into(),
            time,
        };

        let commit = gix::objs::Commit {
            tree: tree_oid.detach(),
            parents: vec![].into(),
            author: actor.clone(),
            committer: actor,
            encoding: None,
            message: format!("Initialize {}", branch).into(),
            extra_headers: vec![],
        };
        let commit_oid = repo.write_object(&commit).map_err(Error::git)?;

        // Create branch ref
        use gix::refs::transaction::PreviousValue;
        let refname = format!("refs/heads/{}", branch);
        let log_msg = format!("commit: Initialize {}", branch);
        repo.reference(
            refname.as_str(),
            commit_oid,
            PreviousValue::Any,
            log_msg.as_str(),
        )
        .map_err(Error::git)?;

        // Write reflog entry for the initial commit
        let _ = crate::reflog::write_reflog_entry(
            path,
            &refname,
            &crate::types::ReflogEntry {
                old_sha: crate::reflog::ZERO_SHA.to_string(),
                new_sha: format!("{}", commit_oid),
                committer: format!("{} <{}>", sig.name, sig.email),
                timestamp: now.as_secs(),
                message: log_msg,
            },
        );

        // Set HEAD as symbolic ref to the branch
        use gix::refs::transaction::{Change, LogChange, RefEdit, RefLog};
        use gix::refs::{FullName, Target};
        let edit = RefEdit {
            change: Change::Update {
                log: LogChange {
                    mode: RefLog::AndReference,
                    force_create_reflog: false,
                    message: format!("init: point to {}", branch).into(),
                },
                expected: PreviousValue::Any,
                new: Target::Symbolic(
                    FullName::try_from(refname).map_err(Error::git)?,
                ),
            },
            name: FullName::try_from("HEAD".to_string()).map_err(Error::git)?,
            deref: false,
        };
        repo.edit_reference(edit).map_err(Error::git)?;

        Ok(())
    }

    /// Return a detached (read-only) [`Fs`] for a commit identified by hex SHA.
    ///
    /// The returned snapshot is not bound to any branch and cannot be written to.
    pub fn fs(&self, hash: &str) -> Result<Fs> {
        let oid = gix::ObjectId::from_hex(hash.as_bytes()).map_err(Error::git)?;
        Fs::from_commit(Arc::clone(&self.inner), oid, None, Some(false))
    }

    /// Return a [`RefDict`] for branches (`refs/heads/`).
    ///
    /// Supports `get`, `set`, `delete`, `contains`, `keys`, iteration,
    /// and `current`/`set_current` for HEAD management.
    pub fn branches(&self) -> RefDict<'_> {
        RefDict::new(self, "refs/heads/")
    }

    /// Return a [`RefDict`] for tags (`refs/tags/`).
    ///
    /// Tags are read-only snapshots — `set` creates a tag but the returned
    /// [`Fs`] is not writable.
    pub fn tags(&self) -> RefDict<'_> {
        RefDict::new(self, "refs/tags/")
    }

    /// Return a [`NoteDict`] for accessing git notes namespaces.
    ///
    /// Use `notes().commits()` for the default `refs/notes/commits` namespace,
    /// or `notes().ns("custom")` for a custom namespace.
    pub fn notes(&self) -> NoteDict<'_> {
        NoteDict::new(self)
    }

    /// Path to the bare repository on disk.
    pub fn path(&self) -> &Path {
        &self.inner.path
    }

    /// The default signature used for commits.
    pub fn signature(&self) -> &Signature {
        &self.inner.signature
    }

    /// Push all refs to `dest`, creating an exact mirror.
    ///
    /// Supports local paths and remote URLs (SSH, HTTPS, git).
    /// Auto-creates a bare repository at local destinations.
    ///
    /// # Arguments
    /// * `dest` - Destination URL or local path.
    /// * `dry_run` - If true, compute diff but do not push.
    pub fn backup(&self, dest: &str, dry_run: bool) -> Result<MirrorDiff> {
        crate::mirror::backup(&self.inner.path, dest, dry_run)
    }

    /// Fetch all refs from `src`, overwriting local state.
    ///
    /// Supports local paths and remote URLs (SSH, HTTPS, git).
    /// All branches, tags, and notes are restored, but HEAD (the current
    /// branch pointer) is not — use `store.branches().set_current("name")`
    /// afterwards if needed.
    ///
    /// # Arguments
    /// * `src` - Source URL or local path.
    /// * `dry_run` - If true, compute diff but do not fetch.
    pub fn restore(&self, src: &str, dry_run: bool) -> Result<MirrorDiff> {
        crate::mirror::restore(&self.inner.path, src, dry_run)
    }
}

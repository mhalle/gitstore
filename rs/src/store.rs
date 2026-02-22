use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use crate::error::{Error, Result};
use crate::fs::Fs;
use crate::refdict::RefDict;
use crate::types::{MirrorDiff, OpenOptions, Signature};

/// Internal state shared via `Arc`.
pub(crate) struct GitStoreInner {
    pub(crate) repo: Mutex<gix::Repository>,
    pub(crate) path: PathBuf,
    pub(crate) signature: Signature,
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
    pub fn open(path: impl AsRef<Path>, options: OpenOptions) -> Result<Self> {
        let path = path.as_ref().to_path_buf();

        let sig = Signature {
            name: options.author.unwrap_or_else(|| "gitstore".into()),
            email: options.email.unwrap_or_else(|| "gitstore@localhost".into()),
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
                    FullName::try_from(refname).map_err(|e| Error::git(e))?,
                ),
            },
            name: FullName::try_from("HEAD".to_string()).map_err(|e| Error::git(e))?,
            deref: false,
        };
        repo.edit_reference(edit).map_err(Error::git)?;

        Ok(())
    }

    /// Return the `Fs` view for the given branch (or the default branch).
    pub fn fs(&self, branch: Option<&str>) -> Result<Fs> {
        let repo = self.inner.repo.lock().map_err(|e| Error::git_msg(e.to_string()))?;

        let branch_name = match branch {
            Some(name) => name.to_string(),
            None => {
                // Resolve HEAD to find the default branch
                let head = repo.find_reference("HEAD").map_err(Error::git)?;
                match head.target().try_name() {
                    Some(name) => {
                        let name_str = name.as_bstr().to_string();
                        name_str
                            .strip_prefix("refs/heads/")
                            .unwrap_or(&name_str)
                            .to_string()
                    }
                    None => {
                        return Err(Error::not_found("HEAD is not a symbolic reference"));
                    }
                }
            }
        };

        let refname = format!("refs/heads/{}", branch_name);
        let reference = repo
            .find_reference(refname.as_str())
            .map_err(|_| Error::not_found(format!("branch '{}' not found", branch_name)))?;
        let commit_oid = reference.id().detach();

        // Read commit to get tree oid
        let commit_obj = repo.find_object(commit_oid).map_err(Error::git)?;
        let commit_ref =
            gix::objs::CommitRef::from_bytes(&commit_obj.data).map_err(Error::git)?;
        let tree_oid = commit_ref.tree();

        Ok(Fs {
            inner: Arc::clone(&self.inner),
            commit_oid: Some(commit_oid),
            tree_oid: Some(tree_oid.into()),
            branch: Some(branch_name),
        })
    }

    /// Return a `RefDict` for branches.
    pub fn branches(&self) -> RefDict<'_> {
        RefDict::new(self, "refs/heads/")
    }

    /// Return a `RefDict` for tags.
    pub fn tags(&self) -> RefDict<'_> {
        RefDict::new(self, "refs/tags/")
    }

    /// Path to the bare repository on disk.
    pub fn path(&self) -> &Path {
        &self.inner.path
    }

    /// The default signature used for commits.
    pub fn signature(&self) -> &Signature {
        &self.inner.signature
    }

    /// Back up this repository to a target path.
    pub fn backup(&self, dest: impl AsRef<Path>) -> Result<MirrorDiff> {
        crate::mirror::backup(&self.inner.path, dest.as_ref())
    }

    /// Restore this repository from a backup.
    pub fn restore(&self, src: impl AsRef<Path>) -> Result<MirrorDiff> {
        crate::mirror::restore(src.as_ref(), &self.inner.path)
    }
}

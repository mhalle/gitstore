use std::path::PathBuf;

// ---------------------------------------------------------------------------
// Mode constants
// ---------------------------------------------------------------------------

pub const MODE_BLOB: u32 = 0o100644;
pub const MODE_BLOB_EXEC: u32 = 0o100755;
pub const MODE_LINK: u32 = 0o120000;
pub const MODE_TREE: u32 = 0o040000;

// ---------------------------------------------------------------------------
// FileType
// ---------------------------------------------------------------------------

/// The type of a git tree entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FileType {
    Blob,
    Executable,
    Link,
    Tree,
}

impl FileType {
    /// Convert a raw git mode to a `FileType`.
    pub fn from_mode(mode: u32) -> Option<Self> {
        match mode {
            MODE_BLOB => Some(Self::Blob),
            MODE_BLOB_EXEC => Some(Self::Executable),
            MODE_LINK => Some(Self::Link),
            MODE_TREE => Some(Self::Tree),
            _ => None,
        }
    }

    /// Convert to a raw git mode.
    pub fn to_mode(self) -> u32 {
        match self {
            Self::Blob => MODE_BLOB,
            Self::Executable => MODE_BLOB_EXEC,
            Self::Link => MODE_LINK,
            Self::Tree => MODE_TREE,
        }
    }

    /// Whether this type represents a regular file (blob or executable).
    pub fn is_file(self) -> bool {
        matches!(self, Self::Blob | Self::Executable)
    }

    /// Whether this type represents a directory.
    pub fn is_dir(self) -> bool {
        matches!(self, Self::Tree)
    }

    /// Whether this type represents a symlink.
    pub fn is_link(self) -> bool {
        matches!(self, Self::Link)
    }
}

// ---------------------------------------------------------------------------
// WalkEntry
// ---------------------------------------------------------------------------

/// An entry yielded when walking a tree.
#[derive(Debug, Clone)]
pub struct WalkEntry {
    pub name: String,
    pub oid: gix::ObjectId,
    pub mode: u32,
}

impl WalkEntry {
    pub fn file_type(&self) -> Option<FileType> {
        FileType::from_mode(self.mode)
    }
}

// ---------------------------------------------------------------------------
// WriteEntry
// ---------------------------------------------------------------------------

/// Data to be written to the store.
#[derive(Debug, Clone)]
pub struct WriteEntry {
    /// Raw content (for blobs).
    pub data: Option<Vec<u8>>,
    /// Symlink target.
    pub target: Option<String>,
    /// Git file mode.
    pub mode: u32,
}

impl WriteEntry {
    /// Create a blob entry from raw bytes.
    pub fn from_bytes(data: impl Into<Vec<u8>>) -> Self {
        Self {
            data: Some(data.into()),
            target: None,
            mode: MODE_BLOB,
        }
    }

    /// Create a blob entry from a UTF-8 string.
    pub fn from_text(text: impl Into<String>) -> Self {
        Self::from_bytes(text.into().into_bytes())
    }

    /// Create a symlink entry.
    pub fn symlink(target: impl Into<String>) -> Self {
        Self {
            data: None,
            target: Some(target.into()),
            mode: MODE_LINK,
        }
    }

    /// Validate that the entry is internally consistent.
    pub fn validate(&self) -> crate::error::Result<()> {
        match self.mode {
            MODE_LINK => {
                if self.target.is_none() {
                    return Err(crate::error::Error::invalid_path(
                        "symlink entry requires a target",
                    ));
                }
                if self.data.is_some() {
                    return Err(crate::error::Error::invalid_path(
                        "symlink entry must not have data",
                    ));
                }
            }
            MODE_BLOB | MODE_BLOB_EXEC => {
                if self.data.is_none() {
                    return Err(crate::error::Error::invalid_path(
                        "blob entry requires data",
                    ));
                }
                if self.target.is_some() {
                    return Err(crate::error::Error::invalid_path(
                        "blob entry must not have a symlink target",
                    ));
                }
            }
            _ => {
                return Err(crate::error::Error::invalid_path(format!(
                    "unsupported mode: {:#o}",
                    self.mode
                )));
            }
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// FileEntry
// ---------------------------------------------------------------------------

/// Describes a file on disk that should be imported/exported.
#[derive(Debug, Clone)]
pub struct FileEntry {
    /// Relative path within the store.
    pub path: String,
    /// Type of the file.
    pub file_type: FileType,
    /// Source path on disk (for copy_in) or destination (for copy_out).
    pub src: PathBuf,
}

// ---------------------------------------------------------------------------
// ChangeReport
// ---------------------------------------------------------------------------

/// Kinds of change actions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ChangeActionKind {
    Add,
    Update,
    Delete,
}

/// A single change action.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChangeAction {
    pub kind: ChangeActionKind,
    pub path: String,
}

impl ChangeAction {
    pub fn new(kind: ChangeActionKind, path: impl Into<String>) -> Self {
        Self {
            kind,
            path: path.into(),
        }
    }
}

impl PartialOrd for ChangeAction {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for ChangeAction {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.path.cmp(&other.path)
    }
}

/// An error encountered during a change operation.
#[derive(Debug, Clone)]
pub struct ChangeError {
    pub path: String,
    pub message: String,
}

impl ChangeError {
    pub fn new(path: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            message: message.into(),
        }
    }
}

/// Report summarising the outcome of a sync / copy / import operation.
#[derive(Debug, Clone, Default)]
pub struct ChangeReport {
    pub add: Vec<String>,
    pub update: Vec<String>,
    pub delete: Vec<String>,
    pub errors: Vec<ChangeError>,
    pub warnings: Vec<String>,
}

impl ChangeReport {
    pub fn new() -> Self {
        Self::default()
    }

    /// `true` when nothing was changed.
    pub fn in_sync(&self) -> bool {
        self.add.is_empty() && self.update.is_empty() && self.delete.is_empty()
    }

    /// Total number of changes (add + update + delete).
    pub fn total(&self) -> usize {
        self.add.len() + self.update.len() + self.delete.len()
    }

    /// Return a sorted list of all change actions.
    pub fn actions(&self) -> Vec<ChangeAction> {
        let mut out = Vec::with_capacity(self.total());
        for p in &self.add {
            out.push(ChangeAction::new(ChangeActionKind::Add, p.as_str()));
        }
        for p in &self.update {
            out.push(ChangeAction::new(ChangeActionKind::Update, p.as_str()));
        }
        for p in &self.delete {
            out.push(ChangeAction::new(ChangeActionKind::Delete, p.as_str()));
        }
        out.sort();
        out
    }

    /// Consume the report and return an error if any errors were recorded.
    pub fn finalize(self) -> crate::error::Result<Self> {
        if self.errors.is_empty() {
            Ok(self)
        } else {
            let msgs: Vec<_> = self.errors.iter().map(|e| e.message.clone()).collect();
            Err(crate::error::Error::Permission(msgs.join("; ")))
        }
    }
}

// ---------------------------------------------------------------------------
// Signature / CommitInfo
// ---------------------------------------------------------------------------

/// Author/committer identity.
#[derive(Debug, Clone)]
pub struct Signature {
    pub name: String,
    pub email: String,
}

impl Default for Signature {
    fn default() -> Self {
        Self {
            name: "gitstore".into(),
            email: "gitstore@localhost".into(),
        }
    }
}

/// Information for creating a commit.
#[derive(Debug, Clone)]
pub struct CommitInfo {
    pub message: String,
    pub time: Option<u64>,
    pub author_name: Option<String>,
    pub author_email: Option<String>,
}

// ---------------------------------------------------------------------------
// ReflogEntry
// ---------------------------------------------------------------------------

/// A single reflog entry.
#[derive(Debug, Clone)]
pub struct ReflogEntry {
    pub old_sha: String,
    pub new_sha: String,
    pub committer: String,
    pub timestamp: u64,
    pub message: String,
}

// ---------------------------------------------------------------------------
// RefChange / MirrorDiff
// ---------------------------------------------------------------------------

/// Describes a reference change during backup/restore.
#[derive(Debug, Clone)]
pub struct RefChange {
    pub name: String,
    pub old_target: Option<String>,
    pub new_target: Option<String>,
}

/// Summary of differences between two repositories (for mirror ops).
#[derive(Debug, Clone, Default)]
pub struct MirrorDiff {
    pub refs_added: Vec<RefChange>,
    pub refs_updated: Vec<RefChange>,
    pub refs_deleted: Vec<RefChange>,
}

impl MirrorDiff {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn in_sync(&self) -> bool {
        self.refs_added.is_empty()
            && self.refs_updated.is_empty()
            && self.refs_deleted.is_empty()
    }

    pub fn total(&self) -> usize {
        self.refs_added.len() + self.refs_updated.len() + self.refs_deleted.len()
    }
}

// ---------------------------------------------------------------------------
// OpenOptions
// ---------------------------------------------------------------------------

/// Options for opening or creating a `GitStore`.
#[derive(Debug, Clone, Default)]
pub struct OpenOptions {
    /// Create the repository if it doesn't exist.
    pub create: bool,
    /// Default branch name.
    pub branch: Option<String>,
    /// Default author name.
    pub author: Option<String>,
    /// Default author email.
    pub email: Option<String>,
}

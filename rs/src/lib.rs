pub mod batch;
pub mod copy;
pub mod error;
pub mod fs;
pub mod glob;
pub mod lock;
pub mod mirror;
pub mod notes;
pub mod paths;
pub mod refdict;
pub mod reflog;
pub mod store;
pub mod tree;
pub mod types;

// Re-export primary public types at crate root.
pub use error::{Error, Result};
pub use store::GitStore;
pub use fs::Fs;
pub use batch::Batch;
pub use refdict::RefDict;
pub use notes::{NoteDict, NoteNamespace, NotesBatch};
pub use types::*;

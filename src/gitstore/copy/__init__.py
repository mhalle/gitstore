"""Copy and sync files between local disk and a gitstore repo.

Supports files, directories, trailing-slash "contents" mode, and glob
patterns (``*``, ``?``) with dotfile-aware matching.

Sync operations (``sync_to_repo``, ``sync_from_repo``) make a repo path
identical to a local directory or vice versa, including deletes.
"""

from .._exclude import ExcludeFilter
from ._types import (
    CopyAction,
    CopyError,
    CopyPlan,
    CopyReport,
    FileEntry,
    SyncAction,
    SyncPlan,
    _finalize_report,
    format_commit_message,
)
from ._resolve import (
    _walk_local_paths,
    _walk_repo,
    _expand_disk_glob,
    _disk_glob_walk,
    _resolve_disk_sources,
    _resolve_repo_sources,
    _enum_disk_to_repo,
    _enum_repo_to_disk,
)
from ._io import (
    _HASH_CHUNK_SIZE,
    _blob_hasher,
    _local_file_oid,
    _local_file_oid_abs,
    _write_files_to_repo,
    _write_files_to_disk,
    _filter_tree_conflicts,
    _prune_empty_dirs,
)
from ._ops import (
    copy_to_repo,
    copy_from_repo,
    copy_to_repo_dry_run,
    copy_from_repo_dry_run,
    remove_from_repo,
    remove_from_repo_dry_run,
    sync_to_repo,
    sync_from_repo,
    sync_to_repo_dry_run,
    sync_from_repo_dry_run,
    _ensure_trailing_slash,
    _sync_delete_all_in_repo,
    _sync_delete_all_local,
)

__all__ = [
    # Public types
    "CopyAction", "CopyError", "CopyReport", "ExcludeFilter", "FileEntry",
    "CopyPlan", "SyncAction", "SyncPlan",
    # Public functions
    "copy_to_repo", "copy_from_repo",
    "copy_to_repo_dry_run", "copy_from_repo_dry_run",
    "remove_from_repo", "remove_from_repo_dry_run",
    "sync_to_repo", "sync_from_repo",
    "sync_to_repo_dry_run", "sync_from_repo_dry_run",
    "format_commit_message",
    # Private but used by tests
    "_expand_disk_glob",
]

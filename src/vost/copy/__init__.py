"""Copy and sync files between local disk and a vost repo.

Supports files, directories, and trailing-slash "contents" mode.

Operations are available as methods on ``FS``:

- ``fs.copy_in()``  — disk → repo
- ``fs.copy_out()`` — repo → disk
- ``fs.sync_in()``  — disk → repo (with delete)
- ``fs.sync_out()`` — repo → disk (with delete)
- ``fs.remove()``   — remove from repo
- ``fs.move()``     — move within repo

Use ``disk_glob()`` for local filesystem glob expansion and
``fs.glob()`` for repo-side glob expansion.
"""

from .._exclude import ExcludeFilter
from ._types import (
    ChangeAction,
    ChangeActionKind,
    ChangeError,
    ChangeReport,
    FileEntry,
    FileType,
    _finalize_changes,
    format_commit_message,
)
from ._resolve import (
    _walk_local_paths,
    _walk_repo,
    disk_glob,
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

__all__ = [
    # Public types
    "ChangeAction", "ChangeActionKind", "ChangeError", "ChangeReport", "ExcludeFilter",
    "FileEntry", "FileType",
    # Glob expansion
    "disk_glob",
]

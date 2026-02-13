"""Copy and sync files between local disk and a gitstore repo.

Supports files, directories, trailing-slash "contents" mode, and glob
patterns (``*``, ``?``) with dotfile-aware matching.

Operations are available as methods on ``FS``:

- ``fs.copy_in()``  — disk → repo
- ``fs.copy_out()`` — repo → disk
- ``fs.sync_in()``  — disk → repo (with delete)
- ``fs.sync_out()`` — repo → disk (with delete)
- ``fs.remove()``   — remove from repo
- ``fs.move()``     — move within repo
"""

from .._exclude import ExcludeFilter
from ._types import (
    ChangeAction,
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

__all__ = [
    # Public types
    "ChangeAction", "ChangeError", "ChangeReport", "ExcludeFilter",
    "FileEntry", "FileType",
]

"""FS: immutable snapshot of a committed tree state."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from . import _compat as pygit2

from ._lock import repo_lock
from .exceptions import StaleSnapshotError
from .tree import (
    GIT_FILEMODE_BLOB,
    GIT_FILEMODE_LINK,
    GIT_OBJECT_TREE,
    _is_root_path,
    _mode_from_disk,
    _normalize_path,
    _walk_to,
    read_blob_at_path,
    list_tree_at_path,
    walk_tree,
    exists_at_path,
    rebuild_tree,
)

if TYPE_CHECKING:
    from .repo import GitStore


class FS:
    """An immutable snapshot of a committed tree.

    Read-only when branch is None (tag snapshot).
    Writable when branch is set — writes auto-commit and return a new FS.
    """

    def __init__(self, gitstore: GitStore, commit_oid, branch: str | None = None):
        self._store = gitstore
        self._commit_oid = commit_oid
        self._branch = branch
        commit = gitstore._repo[commit_oid]
        self._tree_oid = commit.tree_id

    @property
    def _writable(self) -> bool:
        return self._branch is not None

    def __repr__(self) -> str:
        short = str(self._commit_oid)[:7]
        if self._branch:
            return f"FS(branch={self._branch!r}, commit={short})"
        return f"FS(commit={short})"

    @property
    def hash(self) -> str:
        return str(self._commit_oid)

    @property
    def branch(self) -> str | None:
        return self._branch

    @property
    def message(self) -> str:
        return self._store._repo[self._commit_oid].message.rstrip("\n")

    @property
    def time(self) -> datetime:
        commit = self._store._repo[self._commit_oid]
        tz = timezone(timedelta(minutes=commit.commit_time_offset))
        return datetime.fromtimestamp(commit.commit_time, tz=tz)

    @property
    def author_name(self) -> str:
        return self._store._repo[self._commit_oid].author.name

    @property
    def author_email(self) -> str:
        return self._store._repo[self._commit_oid].author.email

    # --- Read operations ---

    def read(self, path: str | os.PathLike[str]) -> bytes:
        return read_blob_at_path(self._store._repo, self._tree_oid, path)

    def ls(self, path: str | os.PathLike[str] | None = None) -> list[str]:
        return list_tree_at_path(self._store._repo, self._tree_oid, path)

    def walk(self, path: str | os.PathLike[str] | None = None) -> Iterator[tuple[str, list[str], list[str]]]:
        if path is None or _is_root_path(path):
            yield from walk_tree(self._store._repo, self._tree_oid)
        else:
            path = _normalize_path(path)
            obj = _walk_to(self._store._repo, self._tree_oid, path)
            if obj.type != GIT_OBJECT_TREE:
                raise NotADirectoryError(path)
            yield from walk_tree(self._store._repo, obj.id, path)

    def exists(self, path: str | os.PathLike[str]) -> bool:
        return exists_at_path(self._store._repo, self._tree_oid, path)

    def readlink(self, path: str | os.PathLike[str]) -> str:
        """Read the target of a symlink."""
        from .tree import _entry_at_path
        path = _normalize_path(path)
        entry = _entry_at_path(self._store._repo, self._tree_oid, path)
        if entry is None:
            raise FileNotFoundError(path)
        _oid, filemode = entry
        if filemode != GIT_FILEMODE_LINK:
            raise ValueError(f"Not a symlink: {path}")
        return self._store._repo[_oid].data.decode()

    def open(self, path: str | os.PathLike[str], mode: str = "rb"):
        if mode == "rb":
            from ._fileobj import ReadableFile
            return ReadableFile(self.read(path))
        elif mode == "wb":
            if not self._writable:
                raise PermissionError("Cannot write to a read-only snapshot")
            from ._fileobj import WritableFile
            return WritableFile(self, path)
        else:
            raise ValueError(f"Unsupported mode: {mode!r}")

    # --- Write operations ---

    def _commit_changes(
        self,
        writes: dict[str, bytes | tuple[bytes, int] | pygit2.Oid | tuple[pygit2.Oid, int]],
        removes: set[str],
        message: str,
    ) -> FS:
        if not self._writable:
            raise PermissionError("Cannot write to a read-only snapshot")

        repo = self._store._repo
        sig = self._store._signature

        new_tree_oid = rebuild_tree(repo, self._tree_oid, writes, removes)
        if new_tree_oid == self._tree_oid:
            return self  # nothing changed

        # Create commit object without moving the ref
        new_commit_oid = repo.create_commit(
            None,
            sig,
            sig,
            message,
            new_tree_oid,
            [self._commit_oid],
        )

        # Atomic check-and-update under file lock
        ref_name = f"refs/heads/{self._branch}"
        with repo_lock(repo.path):
            ref = repo.references[ref_name]
            if ref.resolve().target != self._commit_oid:
                raise StaleSnapshotError(
                    f"Branch {self._branch!r} has advanced since this snapshot"
                )
            ref.set_target(new_commit_oid)

        return FS(self._store, new_commit_oid, branch=self._branch)

    def write(
        self,
        path: str | os.PathLike[str],
        data: bytes,
        *,
        message: str | None = None,
        mode: int | None = None,
    ) -> FS:
        path = _normalize_path(path)
        value: bytes | tuple[bytes, int] = (data, mode) if mode is not None else data
        return self._commit_changes({path: value}, set(), message or f"Write {path}")

    def write_from(
        self,
        path: str | os.PathLike[str],
        local_path: str | os.PathLike[str],
        *,
        message: str | None = None,
        mode: int | None = None,
    ) -> FS:
        path = _normalize_path(path)
        local_path = os.fspath(local_path)
        detected_mode = _mode_from_disk(local_path)
        if mode is None:
            mode = detected_mode
        repo = self._store._repo
        blob_oid = repo.create_blob_fromdisk(local_path)
        value: pygit2.Oid | tuple[pygit2.Oid, int] = (blob_oid, mode) if mode != GIT_FILEMODE_BLOB else blob_oid
        return self._commit_changes({path: value}, set(), message or f"Write {path}")

    def write_symlink(
        self,
        path: str | os.PathLike[str],
        target: str,
        *,
        message: str | None = None,
    ) -> FS:
        path = _normalize_path(path)
        data = target.encode()
        return self._commit_changes(
            {path: (data, GIT_FILEMODE_LINK)}, set(),
            message or f"Symlink {path} -> {target}",
        )

    def remove(self, path: str | os.PathLike[str], *, message: str | None = None) -> FS:
        path = _normalize_path(path)
        if not self._writable:
            raise PermissionError("Cannot write to a read-only snapshot")
        if not self.exists(path):
            raise FileNotFoundError(path)
        # Reject directories — remove is for files only
        obj = _walk_to(self._store._repo, self._tree_oid, path)
        if obj.type == GIT_OBJECT_TREE:
            raise IsADirectoryError(path)
        return self._commit_changes({}, {path}, message if message is not None else f"Remove {path}")

    def batch(self, message: str | None = None):
        from .batch import Batch
        return Batch(self, message=message)

    # --- Dump ---

    def dump(self, path: str | Path) -> None:
        """Write the tree contents to a directory on the filesystem."""
        from .tree import _entry_at_path
        path = Path(path)
        for dirpath, dirnames, filenames in self.walk():
            dir_on_disk = path / dirpath if dirpath else path
            dir_on_disk.mkdir(parents=True, exist_ok=True)
            for filename in filenames:
                store_path = f"{dirpath}/{filename}" if dirpath else filename
                entry = _entry_at_path(self._store._repo, self._tree_oid, store_path)
                if entry and entry[1] == GIT_FILEMODE_LINK:
                    target = self.readlink(store_path)
                    dest = dir_on_disk / filename
                    if dest.exists() or dest.is_symlink():
                        dest.unlink()
                    os.symlink(target, dest)
                else:
                    (dir_on_disk / filename).write_bytes(self.read(store_path))

    # --- History ---

    @property
    def parent(self) -> FS | None:
        commit = self._store._repo[self._commit_oid]
        if not commit.parents:
            return None
        return FS(self._store, commit.parents[0].id, branch=self._branch)

    def log(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        at: str | os.PathLike[str] | None = None,
        match: str | None = None,
        before: datetime | None = None,
    ) -> Iterator[FS]:
        # `path` is the primary parameter (positional or keyword).
        # `at` is a deprecated alias kept for backward compatibility.
        filter_path = path if path is not None else at
        if filter_path is not None:
            filter_path = _normalize_path(filter_path)
        repo = self._store._repo
        if match is not None:
            from fnmatch import fnmatch as _fnmatch
        past_cutoff = False
        current: FS | None = self
        while current is not None:
            if not past_cutoff and before is not None:
                if current.time > before:
                    current = current.parent
                    continue
                past_cutoff = True
            if filter_path is not None:
                from .tree import _entry_at_path
                current_entry = _entry_at_path(repo, current._tree_oid, filter_path)
                parent = current.parent
                parent_entry = _entry_at_path(repo, parent._tree_oid, filter_path) if parent else None
                if current_entry == parent_entry:
                    current = current.parent
                    continue
            if match is not None and not _fnmatch(current.message, match):
                current = current.parent
                continue
            yield current
            current = current.parent

"""FS: immutable snapshot of a committed tree state."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from . import _compat as pygit2

from ._glob import _glob_match
from ._lock import repo_lock
from .exceptions import StaleSnapshotError
from .tree import (
    GIT_FILEMODE_BLOB,
    GIT_FILEMODE_BLOB_EXECUTABLE,
    GIT_FILEMODE_LINK,
    GIT_FILEMODE_TREE,
    GIT_OBJECT_TREE,
    WalkEntry,
    _entry_at_path,
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
    from .copy._types import ChangeReport
    from .repo import GitStore

__all__ = ["FS", "retry_write"]


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
        self._changes = None

    @property
    def _writable(self) -> bool:
        return self._branch is not None

    def __repr__(self) -> str:
        short = str(self._commit_oid)[:7]
        if self._branch:
            return f"FS(branch={self._branch!r}, commit={short})"
        return f"FS(commit={short})"

    @property
    def commit_hash(self) -> str:
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

    @property
    def changes(self) -> ChangeReport | None:
        """Report of the operation that created this snapshot."""
        return self._changes

    # --- Read operations ---

    def read(self, path: str | os.PathLike[str]) -> bytes:
        return read_blob_at_path(self._store._repo, self._tree_oid, path)

    def read_text(self, path: str | os.PathLike[str], encoding: str = "utf-8") -> str:
        return self.read(path).decode(encoding)

    def ls(self, path: str | os.PathLike[str] | None = None) -> list[str]:
        return list_tree_at_path(self._store._repo, self._tree_oid, path)

    def walk(self, path: str | os.PathLike[str] | None = None) -> Iterator[tuple[str, list[str], list[WalkEntry]]]:
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

    def is_dir(self, path: str | os.PathLike[str]) -> bool:
        """Return True if *path* is a directory (tree) in the repo."""
        path = _normalize_path(path)
        entry = _entry_at_path(self._store._repo, self._tree_oid, path)
        if entry is None:
            return False
        return entry[1] == GIT_FILEMODE_TREE

    def iglob(self, pattern: str) -> Iterator[str]:
        """Expand a glob pattern against the repo tree, yielding unique matches.

        Like :meth:`glob` but returns an unordered iterator instead of a
        sorted list.  Useful when you only need to iterate once and don't
        need sorted output.
        """
        pattern = pattern.strip("/")
        if not pattern:
            return
        seen: set[str] = set()
        for path in self._iglob_walk(pattern.split("/"), None, self._tree_oid):
            if path not in seen:
                seen.add(path)
                yield path

    def glob(self, pattern: str) -> list[str]:
        """Expand a glob pattern against the repo tree.

        Supports ``*``, ``?``, and ``**``.  ``*`` and ``?`` do not match
        a leading ``.`` unless the pattern segment itself starts with ``.``.
        ``**`` matches zero or more directory levels, skipping directories
        whose names start with ``.``.
        Returns a sorted, deduplicated list of matching paths (files and directories).
        """
        return sorted(self.iglob(pattern))

    def _iglob_entries(self, tree_oid) -> list[tuple[str, bool, object]]:
        """Return [(name, is_dir, oid), ...] for entries in a tree."""
        repo = self._store._repo
        tree = repo[tree_oid]
        return [(e.name, e.filemode == GIT_FILEMODE_TREE, e.id) for e in tree]

    def _iglob_walk(self, segments: list[str], prefix: str | None, tree_oid) -> Iterator[str]:
        """Recursive glob generator — carries tree OID to avoid root walks."""
        if not segments:
            return
        seg = segments[0]
        rest = segments[1:]
        repo = self._store._repo

        if seg == "**":
            try:
                entries = self._iglob_entries(tree_oid)
            except (KeyError, TypeError):
                return
            if rest:
                # Zero dirs: match rest[0] against entries we already have
                yield from self._iglob_match_entries(rest, prefix, entries)
            else:
                # ** alone at end: yield non-dot entries at this level
                for name, _is_dir, _oid in entries:
                    if name.startswith("."):
                        continue
                    yield f"{prefix}/{name}" if prefix else name
            # One+ dirs: recurse into non-dot subdirs
            for name, entry_is_dir, oid in entries:
                if name.startswith("."):
                    continue
                full = f"{prefix}/{name}" if prefix else name
                if entry_is_dir:
                    yield from self._iglob_walk(segments, full, oid)  # keep **
            return

        has_wild = "*" in seg or "?" in seg

        if has_wild:
            try:
                entries = self._iglob_entries(tree_oid)
            except (KeyError, TypeError):
                return
            for name, _is_dir, oid in entries:
                if not _glob_match(seg, name):
                    continue
                full = f"{prefix}/{name}" if prefix else name
                if rest:
                    yield from self._iglob_walk(rest, full, oid)
                else:
                    yield full
        else:
            # Literal segment — look up directly in current tree
            try:
                tree = repo[tree_oid]
                entry = tree[seg]
            except (KeyError, TypeError):
                return
            full = f"{prefix}/{seg}" if prefix else seg
            if rest:
                yield from self._iglob_walk(rest, full, entry.id)
            else:
                yield full

    def _iglob_match_entries(
        self,
        segments: list[str],
        prefix: str | None,
        entries: list[tuple[str, bool, object]],
    ) -> Iterator[str]:
        """Match segments against already-fetched entries (avoids re-listing)."""
        seg = segments[0]
        rest = segments[1:]
        has_wild = "*" in seg or "?" in seg

        if has_wild:
            for name, _is_dir, oid in entries:
                if not _glob_match(seg, name):
                    continue
                full = f"{prefix}/{name}" if prefix else name
                if rest:
                    yield from self._iglob_walk(rest, full, oid)
                else:
                    yield full
        else:
            # Literal — look up in entries
            for name, _is_dir, oid in entries:
                if name == seg:
                    full = f"{prefix}/{seg}" if prefix else seg
                    if rest:
                        yield from self._iglob_walk(rest, full, oid)
                    else:
                        yield full
                    return

    def readlink(self, path: str | os.PathLike[str]) -> str:
        """Read the target of a symlink."""
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

    def _build_changes(
        self,
        writes: dict[str, bytes | tuple[bytes, int] | pygit2.Oid | tuple[pygit2.Oid, int]],
        removes: set[str],
    ):
        """Build ChangeReport from writes and removes with type detection."""
        from .copy._types import ChangeReport, FileEntry, FileType

        repo = self._store._repo
        add_entries = []
        update_entries = []

        for path, value in writes.items():
            # Extract data/oid and mode from value
            if isinstance(value, tuple):
                data_or_oid, mode = value
            else:
                data_or_oid, mode = value, GIT_FILEMODE_BLOB

            existing = _entry_at_path(repo, self._tree_oid, path)
            if existing is not None:
                # Compare OID + mode to skip unchanged files
                existing_oid, existing_mode = existing
                if isinstance(data_or_oid, bytes):
                    new_oid = repo.create_blob(data_or_oid)
                else:
                    new_oid = data_or_oid
                if new_oid == existing_oid and mode == existing_mode:
                    continue  # identical — not a real update
                update_entries.append(FileEntry.from_mode(path, mode))
            else:
                add_entries.append(FileEntry.from_mode(path, mode))

        # For deletes, query the repo to get types before deletion
        delete_entries = []
        for path in removes:
            entry = _entry_at_path(repo, self._tree_oid, path)
            if entry:
                file_entry = FileEntry.from_mode(path, entry[1])
                delete_entries.append(file_entry)
            else:
                # Shouldn't happen, but handle gracefully
                delete_entries.append(FileEntry(path, FileType.BLOB))

        return ChangeReport(add=add_entries, update=update_entries, delete=delete_entries)

    def _commit_changes(
        self,
        writes: dict[str, bytes | tuple[bytes, int] | pygit2.Oid | tuple[pygit2.Oid, int]],
        removes: set[str],
        message: str | None,
        operation: str | None = None,
    ) -> FS:
        if not self._writable:
            raise PermissionError("Cannot write to a read-only snapshot")

        from .copy._types import format_commit_message

        repo = self._store._repo
        sig = self._store._signature

        # Build changes
        changes = self._build_changes(writes, removes)

        # Generate message if not provided
        final_message = format_commit_message(changes, message, operation)

        new_tree_oid = rebuild_tree(repo, self._tree_oid, writes, removes)

        # Atomic check-and-update under file lock
        ref_name = f"refs/heads/{self._branch}"
        with repo_lock(repo.path):
            ref = repo.references[ref_name]
            if ref.resolve().target != self._commit_oid:
                raise StaleSnapshotError(
                    f"Branch {self._branch!r} has advanced since this snapshot"
                )

            if new_tree_oid == self._tree_oid:
                return self  # nothing changed, branch is current

            # Create commit object and move the ref
            new_commit_oid = repo.create_commit(
                None,
                sig,
                sig,
                final_message,
                new_tree_oid,
                [self._commit_oid],
            )
            # Pass commit message to reflog
            ref.set_target(new_commit_oid, message=f"commit: {final_message}".encode(), committer=sig._identity)

        new_fs = FS(self._store, new_commit_oid, branch=self._branch)
        new_fs._changes = changes
        return new_fs

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
        return self._commit_changes({path: value}, set(), message)

    def write_text(
        self,
        path: str | os.PathLike[str],
        text: str,
        *,
        encoding: str = "utf-8",
        message: str | None = None,
    ) -> FS:
        return self.write(path, text.encode(encoding), message=message)

    def write_from_file(
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
        return self._commit_changes({path: value}, set(), message)

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
            message,
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
        return self._commit_changes({}, {path}, message)

    def batch(self, message: str | None = None, operation: str | None = None):
        from .batch import Batch
        return Batch(self, message=message, operation=operation)

    # --- Export ---

    def export_tree(self, path: str | Path) -> None:
        """Write the tree contents to a directory on the filesystem.

        The destination directory should be empty or non-existent.
        Collisions with existing files or directories are not handled.
        """
        path = Path(path)
        repo = self._store._repo
        for dirpath, dirnames, files in self.walk():
            dir_on_disk = path / dirpath if dirpath else path
            dir_on_disk.mkdir(parents=True, exist_ok=True)
            for fe in files:
                if fe.filemode == GIT_FILEMODE_LINK:
                    target = repo[fe.oid].data.decode()
                    dest = dir_on_disk / fe.name
                    if dest.exists() or dest.is_symlink():
                        dest.unlink()
                    os.symlink(target, dest)
                else:
                    (dir_on_disk / fe.name).write_bytes(repo[fe.oid].data)
                    if fe.filemode == GIT_FILEMODE_BLOB_EXECUTABLE:
                        os.chmod(dir_on_disk / fe.name, 0o755)

    # --- History ---

    @property
    def parent(self) -> FS | None:
        commit = self._store._repo[self._commit_oid]
        if not commit.parents:
            return None
        return FS(self._store, commit.parents[0].id, branch=self._branch)

    def back(self, n: int = 1) -> FS:
        """Return the FS at the *n*-th ancestor commit.

        Raises ValueError if *n* < 0 or history is too short.
        """
        if n < 0:
            raise ValueError(f"back() requires n >= 0, got {n}")
        fs = self
        for _ in range(n):
            p = fs.parent
            if p is None:
                raise ValueError(
                    f"Cannot go back {n} commits — history too short")
            fs = p
        return fs

    def undo(self, steps: int = 1) -> FS:
        """Move branch back N commits.

        Walks back through parent commits and updates the branch pointer.
        Automatically writes a reflog entry.

        Args:
            steps: Number of commits to undo (default 1)

        Returns:
            New FS snapshot at the parent commit

        Raises:
            PermissionError: If called on read-only snapshot (tag)
            ValueError: If not enough history exists

        Example:
            >>> fs = repo.branches["main"]
            >>> fs = fs.undo()  # Go back 1 commit
            >>> fs = fs.undo(3)  # Go back 3 commits
        """
        if not self._writable:
            raise PermissionError("Cannot undo on a read-only snapshot")

        # Walk back N parents (safe to do outside the lock — read-only)
        current = self
        for i in range(steps):
            if current.parent is None:
                raise ValueError(
                    f"Cannot undo {steps} steps - only {i} commit(s) in history"
                )
            current = current.parent

        # Atomic stale-check + ref update under a single lock
        repo = self._store._repo
        ref_name = f"refs/heads/{self._branch}"
        with repo_lock(repo.path):
            ref = repo.references[ref_name]
            if ref.resolve().target != self._commit_oid:
                raise StaleSnapshotError(
                    f"Branch {self._branch!r} has advanced since this snapshot"
                )
            ref.set_target(current._commit_oid, message=b"undo: move back", committer=self._store._signature._identity)

        return current

    def redo(self, steps: int = 1) -> FS:
        """Move branch forward N steps using reflog.

        Reads the reflog to find where the branch was before the last N movements.
        This can resurrect "orphaned" commits after undo.

        The reflog tracks all branch movements chronologically. Each redo step
        moves back one entry in the reflog (backwards in time through the log,
        but forward in commit history).

        Args:
            steps: Number of reflog entries to go back (default 1)

        Returns:
            New FS snapshot at the target position

        Raises:
            PermissionError: If called on read-only snapshot (tag)
            ValueError: If not enough redo history exists

        Example:
            >>> fs = fs.undo(2)  # Creates 1 reflog entry moving back 2 commits
            >>> fs = fs.redo()   # Go back 1 reflog entry (to before the undo)
        """
        if not self._writable:
            raise PermissionError("Cannot redo on a read-only snapshot")

        # Early stale check (fast-fail; authoritative check under lock below)
        ref_name = f"refs/heads/{self._branch}"
        ref = self._store._repo.references[ref_name]
        if ref.resolve().target != self._commit_oid:
            raise StaleSnapshotError(
                f"Branch {self._branch!r} has advanced since this snapshot"
            )

        from dulwich import reflog as dreflog

        # Read reflog for this branch (safe to do outside the lock — read-only)
        reflog_path = os.path.join(
            self._store._repo.path,
            "logs", "refs", "heads", self._branch
        )

        if not os.path.exists(reflog_path):
            raise ValueError(f"No reflog found for branch {self._branch!r}")

        with open(reflog_path, 'rb') as f:
            entries = list(dreflog.read_reflog(f))

        if len(entries) == 0:
            raise ValueError("Reflog is empty")

        # Find current position in reflog (search backwards to get most recent)
        current_sha = self._commit_oid.raw if hasattr(self._commit_oid, 'raw') else self._commit_oid
        current_index = None

        for i in range(len(entries) - 1, -1, -1):
            if entries[i].new_sha == current_sha:
                current_index = i
                break

        if current_index is None:
            raise ValueError(
                f"Cannot redo - current commit not in reflog (you may have a stale snapshot)"
            )

        # To redo, we want to go to where the branch was N steps ago
        # Each step back in the reflog shows us old_sha (where it was before that movement)
        # So we walk back N steps, taking the old_sha at each step
        target_sha = current_sha
        index = current_index

        from dulwich.protocol import ZERO_SHA as _ZERO_SHA

        for step in range(steps):
            if index < 0:
                raise ValueError(
                    f"Cannot redo {steps} steps - only {step} step(s) available"
                )
            target_sha = entries[index].old_sha
            if target_sha == _ZERO_SHA:
                raise ValueError(
                    f"Cannot redo {steps} step(s) — reaches branch creation point (no prior commit)"
                )
            index -= 1

        target_oid = pygit2.Oid(target_sha)
        target_fs = FS(self._store, target_oid, branch=self._branch)

        # Atomic stale-check + ref update under a single lock
        repo = self._store._repo
        ref_name = f"refs/heads/{self._branch}"
        with repo_lock(repo.path):
            ref = repo.references[ref_name]
            if ref.resolve().target != self._commit_oid:
                raise StaleSnapshotError(
                    f"Branch {self._branch!r} has advanced since this snapshot"
                )
            ref.set_target(target_oid, message=b"redo: move forward", committer=self._store._signature._identity)

        return target_fs

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


def retry_write(
    store: GitStore,
    branch: str,
    path: str | os.PathLike[str],
    data: bytes,
    *,
    message: str | None = None,
    mode: int | None = None,
    retries: int = 5,
) -> FS:
    """Write data to a branch with automatic retry on concurrent modification.

    Re-fetches the branch FS on each attempt.  Uses exponential backoff
    with jitter (base 10ms, factor 2x, cap 200ms) to avoid thundering-herd.

    Raises ``StaleSnapshotError`` if all attempts are exhausted.
    Raises ``KeyError`` if the branch does not exist.
    """
    import random
    import time

    for attempt in range(retries):
        fs = store.branches[branch]
        try:
            return fs.write(path, data, message=message, mode=mode)
        except StaleSnapshotError:
            if attempt == retries - 1:
                raise
            delay = min(0.01 * (2 ** attempt), 0.2)
            time.sleep(random.uniform(0, delay))

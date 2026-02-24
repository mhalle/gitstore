"""Data structures for copy/sync operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..tree import (
    GIT_FILEMODE_BLOB,
    GIT_FILEMODE_BLOB_EXECUTABLE,
    GIT_FILEMODE_LINK,
    GIT_FILEMODE_TREE,
)


class FileType(str, Enum):
    """Git file type enum.

    Members: ``BLOB``, ``EXECUTABLE``, ``LINK``, ``TREE``.
    """
    BLOB = "blob"
    EXECUTABLE = "executable"
    LINK = "link"
    TREE = "tree"

    def __str__(self) -> str:          # noqa: D105
        return self.value

    @classmethod
    def from_filemode(cls, mode: int) -> FileType:
        """Convert a git filemode integer to a :class:`FileType`."""
        return _MODE_TO_TYPE[mode]

    @property
    def filemode(self) -> int:
        """Return the git filemode integer for this type."""
        return _TYPE_TO_MODE[self]


_MODE_TO_TYPE = {
    GIT_FILEMODE_BLOB: FileType.BLOB,
    GIT_FILEMODE_BLOB_EXECUTABLE: FileType.EXECUTABLE,
    GIT_FILEMODE_LINK: FileType.LINK,
    GIT_FILEMODE_TREE: FileType.TREE,
}
_TYPE_TO_MODE = {v: k for k, v in _MODE_TO_TYPE.items()}


@dataclass
class FileEntry:
    """A file path with type information, used in :class:`ChangeReport` lists.

    Attributes:
        path: Relative path (repo-style forward slashes).
        type: :class:`FileType` of the entry.
        src: Source path (local file, repo path, or ``None`` for direct data).
    """
    path: str
    type: FileType
    src: str | None = None

    @classmethod
    def from_mode(cls, path: str, mode: int, src: str | None = None) -> FileEntry:
        """Create FileEntry from path and git filemode."""
        return cls(path, FileType.from_filemode(mode), src)


class ChangeActionKind(str, Enum):
    """Kind of change action: ``ADD``, ``UPDATE``, or ``DELETE``."""
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"

    def __str__(self) -> str:          # noqa: D105
        return self.value


@dataclass
class ChangeAction:
    """A single add/update/delete action in a :class:`ChangeReport`.

    Attributes:
        path: Relative path (repo-style forward slashes).
        action: :class:`ChangeActionKind` value.
    """
    path: str
    action: ChangeActionKind


@dataclass
class ChangeError:
    """A file that failed during an operation.

    Attributes:
        path: The path that caused the error.
        error: Human-readable error message.
    """
    path: str
    error: str


@dataclass
class ChangeReport:
    """Result of a copy, sync, move, or remove operation.

    Available on the :attr:`~gitstore.FS.changes` property of the
    resulting snapshot (both dry-run and real).

    Attributes:
        add: Files added.
        update: Files updated.
        delete: Files deleted.
        errors: Per-file errors (populated when ``ignore_errors=True``).
        warnings: Non-fatal warnings.
    """
    add: list[FileEntry] = field(default_factory=list)
    update: list[FileEntry] = field(default_factory=list)
    delete: list[FileEntry] = field(default_factory=list)
    errors: list[ChangeError] = field(default_factory=list)
    warnings: list[ChangeError] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        """``True`` if there are no add, update, or delete actions."""
        return not self.add and not self.update and not self.delete

    @property
    def total(self) -> int:
        """Total number of add + update + delete actions."""
        return len(self.add) + len(self.update) + len(self.delete)

    def actions(self) -> list[ChangeAction]:
        """Return all actions as a flat list sorted by path."""
        result: list[ChangeAction] = []
        for e in self.add:
            result.append(ChangeAction(path=e.path, action=ChangeActionKind.ADD))
        for e in self.update:
            result.append(ChangeAction(path=e.path, action=ChangeActionKind.UPDATE))
        for e in self.delete:
            result.append(ChangeAction(path=e.path, action=ChangeActionKind.DELETE))
        result.sort(key=lambda a: a.path)
        return result


def _finalize_changes(changes: ChangeReport) -> ChangeReport | None:
    """Return *changes* if it has any content, else ``None``."""
    if (not changes.add and not changes.update and not changes.delete
            and not changes.errors and not changes.warnings):
        return None
    return changes


def format_commit_message(changes: ChangeReport, custom_message: str | None = None, operation: str | None = None) -> str:
    """Generate commit message from changes.

    Args:
        changes: The operation changes
        custom_message: Custom message (overrides auto-generation).
            Supports placeholders: ``{default}``, ``{add_count}``,
            ``{update_count}``, ``{delete_count}``, ``{total_count}``,
            ``{op}``.
        operation: Operation type ("cp", "ar") or None for generic batch
    """
    if custom_message:
        if "{" in custom_message:
            default = _auto_message(changes, operation)
            return custom_message.format(
                default=default,
                add_count=len(changes.add),
                update_count=len(changes.update),
                delete_count=len(changes.delete),
                total_count=changes.total,
                op=operation or "",
            )
        return custom_message

    return _auto_message(changes, operation)


def _auto_message(changes: ChangeReport, operation: str | None) -> str:
    """Generate the default auto commit message."""
    if changes.total == 0:
        return "No changes"

    # Single operation - use +/-/~ notation
    if changes.total == 1:
        if changes.add:
            e = changes.add[0]
            return f"+ {e.path}" + (f" ({e.type})" if e.type != FileType.BLOB else "")
        elif changes.update:
            e = changes.update[0]
            return f"~ {e.path}" + (f" ({e.type})" if e.type != FileType.BLOB else "")
        else:
            return f"- {changes.delete[0].path}"

    # Multiple operations - show summary with +/-/~ counts
    parts = []
    if changes.add:
        parts.append(f"+{len(changes.add)}")
    if changes.update:
        parts.append(f"~{len(changes.update)}")
    if changes.delete:
        parts.append(f"-{len(changes.delete)}")

    # Add operation prefix for batch operations
    prefix = f"Batch {operation}:" if operation else "Batch:"
    return prefix + " " + " ".join(parts)

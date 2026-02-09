"""Data structures for copy/sync operations."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..tree import GIT_FILEMODE_BLOB_EXECUTABLE, GIT_FILEMODE_LINK


@dataclass
class FileEntry:
    """A file with type information."""
    path: str
    type: str  # "B" (blob), "E" (executable), "L" (link)
    src: str | None = None  # source path (local file path, repo path, or None for direct data)

    @classmethod
    def from_mode(cls, path: str, mode: int, src: str | None = None) -> FileEntry:
        """Create FileEntry from path and git filemode."""
        if mode == GIT_FILEMODE_LINK:
            return cls(path, "L", src)
        elif mode == GIT_FILEMODE_BLOB_EXECUTABLE:
            return cls(path, "E", src)
        else:
            return cls(path, "B", src)


@dataclass
class CopyAction:
    """A single add/update/delete action."""
    path: str       # relative path (repo-style forward slashes)
    action: str     # "add", "update", "delete"


@dataclass
class CopyError:
    """A file that failed during a copy operation."""
    path: str
    error: str


@dataclass
class CopyReport:
    """Result of a copy/sync operation (dry-run or real)."""
    add: list[FileEntry] = field(default_factory=list)
    update: list[FileEntry] = field(default_factory=list)
    delete: list[FileEntry] = field(default_factory=list)
    errors: list[CopyError] = field(default_factory=list)
    warnings: list[CopyError] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.add and not self.update and not self.delete

    @property
    def total(self) -> int:
        return len(self.add) + len(self.update) + len(self.delete)

    def actions(self) -> list[CopyAction]:
        """All actions sorted by path."""
        result: list[CopyAction] = []
        for e in self.add:
            result.append(CopyAction(path=e.path, action="add"))
        for e in self.update:
            result.append(CopyAction(path=e.path, action="update"))
        for e in self.delete:
            result.append(CopyAction(path=e.path, action="delete"))
        result.sort(key=lambda a: a.path)
        return result


# Backward-compatible aliases
CopyPlan = CopyReport
SyncAction = CopyAction
SyncPlan = CopyReport


def _finalize_report(report: CopyReport) -> CopyReport | None:
    """Return *report* if it has any content, else ``None``."""
    if (not report.add and not report.update and not report.delete
            and not report.errors and not report.warnings):
        return None
    return report


def format_commit_message(report: CopyReport, custom_message: str | None = None, operation: str | None = None) -> str:
    """Generate commit message from report.

    Args:
        report: The operation report
        custom_message: Custom message (overrides auto-generation)
        operation: Operation type ("cp", "ar") or None for generic batch
    """
    if custom_message:
        return custom_message

    if report.total == 0:
        return "No changes"

    # Single operation - use +/-/~ notation
    if report.total == 1:
        if report.add:
            e = report.add[0]
            return f"+ {e.path}" + (f" ({e.type})" if e.type != "B" else "")
        elif report.update:
            e = report.update[0]
            return f"~ {e.path}" + (f" ({e.type})" if e.type != "B" else "")
        else:
            return f"- {report.delete[0].path}"

    # Multiple operations - show summary with +/-/~ counts
    parts = []
    if report.add:
        parts.append(f"+{len(report.add)}")
    if report.update:
        parts.append(f"~{len(report.update)}")
    if report.delete:
        parts.append(f"-{len(report.delete)}")

    # Add operation prefix for batch operations
    prefix = f"Batch {operation}:" if operation else "Batch:"
    return prefix + " " + " ".join(parts)

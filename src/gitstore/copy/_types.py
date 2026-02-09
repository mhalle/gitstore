"""Data structures for copy/sync operations."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    add: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
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
        for p in self.add:
            result.append(CopyAction(path=p, action="add"))
        for p in self.update:
            result.append(CopyAction(path=p, action="update"))
        for p in self.delete:
            result.append(CopyAction(path=p, action="delete"))
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

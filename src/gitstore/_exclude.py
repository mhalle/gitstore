"""Exclude-filter support for disk→repo operations.

Combines ``--exclude`` patterns, ``--exclude-from`` files, and automatic
``.gitignore`` loading into a single predicate used by
``_walk_local_paths`` and ``_enum_disk_to_repo``.

Pattern syntax follows gitignore rules (implemented by
``dulwich.ignore.IgnoreFilter``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from dulwich.ignore import IgnoreFilter, IgnoreFilterStack


class ExcludeFilter:
    """Combines --exclude patterns, --exclude-from, and .gitignore files."""

    def __init__(
        self,
        *,
        patterns: Sequence[str] | None = None,
        exclude_from: str | None = None,
        gitignore: bool = False,
    ) -> None:
        base_lines: list[bytes] = []
        for p in patterns or ():
            base_lines.append(p.encode("utf-8"))
        if exclude_from is not None:
            path = Path(exclude_from)
            for raw in path.read_bytes().splitlines():
                line = raw.strip()
                if line and not line.startswith(b"#"):
                    base_lines.append(line)
        self._base: IgnoreFilter | None = (
            IgnoreFilter(base_lines) if base_lines else None
        )
        self._gitignore = gitignore
        # {rel_dir: IgnoreFilter | None} — lazily loaded per directory
        self._dir_filters: dict[str, IgnoreFilter | None] = {}

    # ------------------------------------------------------------------
    @property
    def active(self) -> bool:
        """True if any filtering is configured."""
        return self._base is not None or self._gitignore

    # ------------------------------------------------------------------
    def is_excluded(self, rel_path: str, *, is_dir: bool = False) -> bool:
        """Check against base patterns only (for post-filtering)."""
        if self._base is None:
            return False
        check = rel_path + "/" if is_dir else rel_path
        return self._base.is_ignored(check) is True

    # ------------------------------------------------------------------
    def enter_directory(self, abs_dir: Path, rel_dir: str) -> None:
        """Load .gitignore from *abs_dir* if gitignore mode is on."""
        if not self._gitignore:
            return
        if rel_dir in self._dir_filters:
            return
        gi = abs_dir / ".gitignore"
        if gi.is_file():
            self._dir_filters[rel_dir] = IgnoreFilter.from_path(str(gi))
        else:
            self._dir_filters[rel_dir] = None

    # ------------------------------------------------------------------
    def is_excluded_in_walk(
        self, rel_path: str, *, is_dir: bool = False,
    ) -> bool:
        """Check base patterns + loaded .gitignore hierarchy.

        Called during ``os.walk()`` after ``enter_directory`` has been
        invoked for every ancestor.
        """
        check = rel_path + "/" if is_dir else rel_path

        # Base patterns (--exclude / --exclude-from)
        if self._base is not None and self._base.is_ignored(check) is True:
            return True

        if not self._gitignore:
            return False

        # Auto-exclude .gitignore files themselves
        if not is_dir and rel_path.rsplit("/", 1)[-1] == ".gitignore":
            return True

        # Walk .gitignore filters from root → deepest ancestor.
        # Each filter checks the path *relative to its own directory*.
        parts = rel_path.split("/")
        for depth in range(len(parts)):
            if depth == 0:
                dir_key = ""
            else:
                dir_key = "/".join(parts[:depth])
            filt = self._dir_filters.get(dir_key)
            if filt is not None:
                # Path relative to this .gitignore's directory
                sub = "/".join(parts[depth:])
                sub_check = sub + "/" if is_dir else sub
                result = filt.is_ignored(sub_check)
                if result is True:
                    return True
                if result is False:
                    # Explicit negation — stop checking higher-level filters
                    return False

        return False

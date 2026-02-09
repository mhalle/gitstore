"""Shared dotfile-aware glob matching."""

from __future__ import annotations

from fnmatch import fnmatch as _fnmatch


def _glob_match(pattern: str, name: str) -> bool:
    """Match *name* against a glob *pattern* segment.

    ``*`` and ``?`` do not match a leading ``.`` unless the pattern itself
    starts with ``.`` (Unix/rsync convention).
    """
    if not pattern.startswith(".") and name.startswith("."):
        return False
    return _fnmatch(name, pattern)

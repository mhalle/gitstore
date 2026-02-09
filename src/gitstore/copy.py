"""Copy files between local disk and a gitstore repo.

Supports files, directories, trailing-slash "contents" mode, and glob
patterns (``*``, ``?``) with dotfile-aware matching.
"""

from __future__ import annotations

import os
from fnmatch import fnmatch as _fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from .tree import (
    GIT_FILEMODE_LINK,
    GIT_FILEMODE_TREE,
    _entry_at_path,
    _normalize_path,
)

if TYPE_CHECKING:
    from .fs import FS


# ---------------------------------------------------------------------------
# Disk-side glob expansion
# ---------------------------------------------------------------------------

def _glob_match(pattern: str, name: str) -> bool:
    """Match *name* against a glob *pattern* segment.

    ``*`` and ``?`` do not match a leading ``.`` unless the pattern itself
    starts with ``.`` (Unix/rsync convention).
    """
    if not pattern.startswith(".") and name.startswith("."):
        return False
    return _fnmatch(name, pattern)


def _expand_disk_glob(pattern: str) -> list[str]:
    """Expand a glob pattern against the local filesystem.

    Same dotfile rules as the repo-side ``fs.glob()``.
    Returns a sorted list of matching paths.
    """
    pattern = pattern.rstrip("/")
    if not pattern:
        return []

    # Handle absolute paths: split off the root prefix so that we walk
    # from "/" (or the drive root on Windows) as our base directory.
    if os.path.isabs(pattern):
        # Find the root part (e.g. "/") and the rest
        root = os.sep
        rest_pattern = pattern[len(root):]
        # Strip any leading separators left over
        rest_pattern = rest_pattern.lstrip(os.sep)
        segments = rest_pattern.split("/")
        return sorted(_disk_glob_walk(segments, root))
    else:
        segments = pattern.split("/")
        return sorted(_disk_glob_walk(segments, ""))


def _disk_glob_walk(segments: list[str], prefix: str) -> list[str]:
    seg = segments[0]
    rest = segments[1:]
    has_wild = "*" in seg or "?" in seg

    scan_dir = prefix or "."

    if has_wild:
        try:
            entries = os.listdir(scan_dir)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return []
        results: list[str] = []
        for name in entries:
            if not _glob_match(seg, name):
                continue
            full = os.path.join(prefix, name) if prefix else name
            if rest:
                results.extend(_disk_glob_walk(rest, full))
            else:
                results.append(full)
        return results
    else:
        full = os.path.join(prefix, seg) if prefix else seg
        if rest:
            return _disk_glob_walk(rest, full)
        else:
            if os.path.exists(full):
                return [full]
            return []


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

def _resolve_disk_sources(sources: list[str]) -> list[tuple[str, str]]:
    """Resolve local source specs into ``(local_path, mode)`` tuples.

    ``mode`` is one of:
    - ``"file"``    — single file
    - ``"dir"``     — directory, name preserved
    - ``"contents"`` — directory, trailing ``/`` → pour contents
    """
    resolved: list[tuple[str, str]] = []
    for src in sources:
        contents_mode = src.endswith("/")
        has_glob = "*" in src or "?" in src

        if has_glob:
            expanded = _expand_disk_glob(src.rstrip("/"))
            if not expanded:
                raise FileNotFoundError(f"No matches for pattern: {src}")
            for path in expanded:
                if os.path.isdir(path):
                    resolved.append((path, "dir"))
                else:
                    resolved.append((path, "file"))
        elif contents_mode:
            path = src.rstrip("/")
            if not os.path.isdir(path):
                raise NotADirectoryError(f"Not a directory: {path}")
            resolved.append((path, "contents"))
        else:
            if os.path.isdir(src):
                resolved.append((src, "dir"))
            elif os.path.exists(src):
                resolved.append((src, "file"))
            else:
                raise FileNotFoundError(f"Local file not found: {src}")
    return resolved


def _resolve_repo_sources(fs: FS, sources: list[str]) -> list[tuple[str, str]]:
    """Resolve repo source specs into ``(repo_path, mode)`` tuples."""
    resolved: list[tuple[str, str]] = []
    for src in sources:
        contents_mode = src.endswith("/")
        has_glob = "*" in src or "?" in src

        if has_glob:
            expanded = fs.glob(src.rstrip("/"))
            if not expanded:
                raise FileNotFoundError(f"No matches for pattern: {src}")
            for path in expanded:
                if fs.is_dir(path):
                    resolved.append((path, "dir"))
                else:
                    resolved.append((path, "file"))
        elif contents_mode:
            path = src.rstrip("/")
            if path:
                path = _normalize_path(path)
            if path and not fs.is_dir(path):
                raise NotADirectoryError(f"Not a directory in repo: {path}")
            resolved.append((path, "contents"))
        else:
            if src:
                path = _normalize_path(src)
            else:
                path = ""
            if not path:
                resolved.append(("", "contents"))
            elif not fs.exists(path):
                raise FileNotFoundError(f"File not found in repo: {path}")
            elif fs.is_dir(path):
                resolved.append((path, "dir"))
            else:
                resolved.append((path, "file"))
    return resolved


# ---------------------------------------------------------------------------
# File enumeration (for actual copy and dry-run)
# ---------------------------------------------------------------------------

def _enum_disk_to_repo(
    resolved: list[tuple[str, str]], dest: str,
) -> list[tuple[str, str]]:
    """Build ``(local_path, repo_path)`` pairs for disk → repo copy."""
    pairs: list[tuple[str, str]] = []
    for local_path, mode in resolved:
        if mode == "file":
            name = os.path.basename(local_path)
            repo_file = f"{dest}/{name}" if dest else name
            pairs.append((local_path, _normalize_path(repo_file)))
        elif mode == "dir":
            dirname = os.path.basename(local_path)
            target = f"{dest}/{dirname}" if dest else dirname
            for dirpath, _dirnames, filenames in os.walk(local_path):
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    rel = os.path.relpath(full, local_path)
                    rel = rel.replace(os.sep, "/")
                    repo_file = f"{target}/{rel}"
                    pairs.append((full, _normalize_path(repo_file)))
                # Also handle symlinked dirs and file symlinks — they appear
                # in filenames on walk without followlinks
        elif mode == "contents":
            for dirpath, _dirnames, filenames in os.walk(local_path):
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    rel = os.path.relpath(full, local_path)
                    rel = rel.replace(os.sep, "/")
                    repo_file = f"{dest}/{rel}" if dest else rel
                    pairs.append((full, _normalize_path(repo_file)))
    return pairs


def _enum_repo_to_disk(
    fs: FS, resolved: list[tuple[str, str]], dest: str,
) -> list[tuple[str, str]]:
    """Build ``(repo_path, local_path)`` pairs for repo → disk copy."""
    pairs: list[tuple[str, str]] = []
    for repo_path, mode in resolved:
        if mode == "file":
            name = repo_path.rsplit("/", 1)[-1]
            local = os.path.join(dest, name)
            pairs.append((repo_path, local))
        elif mode == "dir":
            dirname = repo_path.rsplit("/", 1)[-1]
            target = os.path.join(dest, dirname)
            for dirpath, _dirs, files in fs.walk(repo_path):
                for fname in files:
                    store_path = f"{dirpath}/{fname}" if dirpath else fname
                    if repo_path and store_path.startswith(repo_path + "/"):
                        rel = store_path[len(repo_path) + 1:]
                    else:
                        rel = store_path
                    local = os.path.join(target, rel)
                    pairs.append((store_path, local))
        elif mode == "contents":
            walk_path = repo_path or None
            for dirpath, _dirs, files in fs.walk(walk_path):
                for fname in files:
                    store_path = f"{dirpath}/{fname}" if dirpath else fname
                    if repo_path and store_path.startswith(repo_path + "/"):
                        rel = store_path[len(repo_path) + 1:]
                    else:
                        rel = store_path
                    local = os.path.join(dest, rel)
                    pairs.append((store_path, local))
    return pairs


# ---------------------------------------------------------------------------
# Disk → repo helpers
# ---------------------------------------------------------------------------

def _cptree_disk_to_repo(b, local, dest_path, follow_symlinks):
    """Walk *local* dir and write files into batch *b* under *dest_path*.

    Returns the number of files written.
    """
    count = 0
    seen_realpaths: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(local, followlinks=follow_symlinks):
        if follow_symlinks:
            real = os.path.realpath(dirpath)
            if real in seen_realpaths:
                dirnames.clear()
                continue
            seen_realpaths.add(real)
        if not follow_symlinks:
            symlinked_dirs = []
            for dname in dirnames:
                full = Path(dirpath) / dname
                if full.is_symlink():
                    rel = full.relative_to(local)
                    repo_file = f"{dest_path}/{rel}" if dest_path else str(rel)
                    repo_file = repo_file.replace(os.sep, "/")
                    repo_file = _normalize_path(repo_file)
                    b.write_symlink(repo_file, os.readlink(full))
                    count += 1
                    symlinked_dirs.append(dname)
            for dname in symlinked_dirs:
                dirnames.remove(dname)
        for fname in filenames:
            full = Path(dirpath) / fname
            rel = full.relative_to(local)
            repo_file = f"{dest_path}/{rel}" if dest_path else str(rel)
            repo_file = repo_file.replace(os.sep, "/")
            repo_file = _normalize_path(repo_file)
            if not follow_symlinks and full.is_symlink():
                b.write_symlink(repo_file, os.readlink(full))
            else:
                b.write_from(repo_file, full)
            count += 1
    return count


def _cptree_repo_to_disk(fs, src_path, local_dest):
    """Walk repo tree at *src_path* and write files to *local_dest*."""
    src_repo_path = src_path or None
    for dirpath, _dirs, files in fs.walk(src_repo_path):
        for fname in files:
            if dirpath:
                store_path = f"{dirpath}/{fname}"
            else:
                store_path = fname
            if src_path and store_path.startswith(src_path + "/"):
                rel = store_path[len(src_path) + 1:]
            else:
                rel = store_path
            out = local_dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            entry = _entry_at_path(fs._store._repo, fs._tree_oid, store_path)
            if entry and entry[1] == GIT_FILEMODE_LINK:
                target = fs.readlink(store_path)
                out.symlink_to(target)
            else:
                out.write_bytes(fs.read(store_path))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def copy_to_repo(
    fs: FS,
    sources: list[str],
    dest: str,
    *,
    follow_symlinks: bool = False,
    message: str | None = None,
    mode: int | None = None,
) -> FS:
    """Copy local files/dirs/globs into the repo. Returns new FS."""
    resolved = _resolve_disk_sources(sources)
    pairs = _enum_disk_to_repo(resolved, dest)

    if not pairs:
        return fs

    with fs.batch(message=message) as b:
        for local_path, repo_path in pairs:
            p = Path(local_path)
            if not follow_symlinks and p.is_symlink():
                b.write_symlink(repo_path, os.readlink(local_path))
            else:
                b.write_from(repo_path, local_path, mode=mode)
    return b.fs


def copy_from_repo(
    fs: FS,
    sources: list[str],
    dest: str,
) -> None:
    """Copy repo files/dirs/globs to local disk."""
    resolved = _resolve_repo_sources(fs, sources)
    pairs = _enum_repo_to_disk(fs, resolved, dest)

    for repo_path, local_path in pairs:
        out = Path(local_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        entry = _entry_at_path(fs._store._repo, fs._tree_oid, repo_path)
        if entry and entry[1] == GIT_FILEMODE_LINK:
            target = fs.readlink(repo_path)
            if out.exists() or out.is_symlink():
                out.unlink()
            out.symlink_to(target)
        else:
            out.write_bytes(fs.read(repo_path))


def copy_to_repo_dry_run(
    fs: FS,
    sources: list[str],
    dest: str,
) -> list[tuple[str, str]]:
    """Compute what copy_to_repo would copy. Returns (local, repo_path) pairs."""
    resolved = _resolve_disk_sources(sources)
    return _enum_disk_to_repo(resolved, dest)


def copy_from_repo_dry_run(
    fs: FS,
    sources: list[str],
    dest: str,
) -> list[tuple[str, str]]:
    """Compute what copy_from_repo would copy. Returns (repo_path, local) pairs."""
    resolved = _resolve_repo_sources(fs, sources)
    return _enum_repo_to_disk(fs, resolved, dest)

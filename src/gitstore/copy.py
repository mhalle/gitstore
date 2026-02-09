"""Copy and sync files between local disk and a gitstore repo.

Supports files, directories, trailing-slash "contents" mode, and glob
patterns (``*``, ``?``) with dotfile-aware matching.

Sync operations (``sync_to_repo``, ``sync_from_repo``) make a repo path
identical to a local directory or vice versa, including deletes.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
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
# Data structures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Shared: directory walking
# ---------------------------------------------------------------------------

def _walk_local_paths(local_path: str, follow_symlinks: bool = False) -> set[str]:
    """Return the set of relative paths under *local_path*.

    Only collects path names — does not read file content.

    When *follow_symlinks* is ``False`` (default), symlinked directories are
    recorded as entries (not descended into), and file symlinks appear
    normally in the walk results.

    When *follow_symlinks* is ``True``, ``os.walk`` follows symlinks with
    cycle detection to avoid infinite loops.

    Note: if *local_path* itself is a symlink to a directory (e.g. contents
    mode with a trailing ``/``), ``os.walk`` always dereferences it
    regardless of *follow_symlinks*.  This matches standard Unix semantics
    where a trailing slash causes the OS to resolve the symlink.
    """
    result: set[str] = set()
    base = Path(local_path)

    if follow_symlinks:
        seen_realpaths: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
            real = os.path.realpath(dirpath)
            if real in seen_realpaths:
                dirnames.clear()
                continue
            seen_realpaths.add(real)
            dp = Path(dirpath)
            for fname in filenames:
                full = dp / fname
                rel_str = str(full.relative_to(base)).replace(os.sep, "/")
                result.add(rel_str)
    else:
        for dirpath, _dirnames, filenames in os.walk(base):
            dp = Path(dirpath)
            for fname in filenames:
                full = dp / fname
                rel_str = str(full.relative_to(base)).replace(os.sep, "/")
                result.add(rel_str)
            symlinked = []
            for dname in _dirnames:
                full = dp / dname
                if full.is_symlink():
                    rel_str = str(full.relative_to(base)).replace(os.sep, "/")
                    result.add(rel_str)
                    symlinked.append(dname)
            for dname in symlinked:
                _dirnames.remove(dname)
    return result


def _walk_repo(fs: FS, repo_path: str) -> dict[str, bytes]:
    """Build {relative_path: oid_hex_bytes} for all files under *repo_path*.

    The values are the raw OID hex bytes from the repo (not file content),
    suitable for comparison against ``_local_file_oid()`` results.
    Returns an empty dict if *repo_path* does not exist or is not a directory.
    """
    result: dict[str, bytes] = {}
    if repo_path:
        if not fs.exists(repo_path):
            return result
        if not fs.is_dir(repo_path):
            return result
    walk_path = repo_path or None
    for dirpath, _dirs, files in fs.walk(walk_path):
        for fname in files:
            store_path = f"{dirpath}/{fname}" if dirpath else fname
            if repo_path and store_path.startswith(repo_path + "/"):
                rel = store_path[len(repo_path) + 1:]
            else:
                rel = store_path
            entry = _entry_at_path(fs._store._repo, fs._tree_oid, store_path)
            if entry is not None:
                result[rel] = entry[0]._sha  # raw hex bytes
    return result


# ---------------------------------------------------------------------------
# Shared: file writing
# ---------------------------------------------------------------------------

def _write_files_to_repo(batch, pairs, *, follow_symlinks=False, mode=None,
                         ignore_errors=False, errors=None):
    """Write ``(local_path, repo_path)`` pairs into a batch."""
    for local_path, repo_path in pairs:
        try:
            p = Path(local_path)
            if not follow_symlinks and p.is_symlink():
                batch.write_symlink(repo_path, os.readlink(local_path))
            else:
                batch.write_from(repo_path, p, mode=mode)
        except OSError as exc:
            if not ignore_errors:
                raise
            if errors is not None:
                errors.append(CopyError(path=local_path, error=str(exc)))


def _write_files_to_disk(fs, pairs, *, ignore_errors=False, errors=None):
    """Write ``(repo_path, local_path)`` pairs to local disk."""
    for repo_path, local_path in pairs:
        try:
            out = Path(local_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() or out.is_symlink():
                out.unlink()
            entry = _entry_at_path(fs._store._repo, fs._tree_oid, repo_path)
            if entry and entry[1] == GIT_FILEMODE_LINK:
                out.symlink_to(fs.readlink(repo_path))
            else:
                out.write_bytes(fs.read(repo_path))
        except OSError as exc:
            if not ignore_errors:
                raise
            if errors is not None:
                errors.append(CopyError(path=local_path, error=str(exc)))


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

    # Normalize platform separators to forward slashes for consistent splitting
    pattern = pattern.replace(os.sep, "/").replace("\\", "/")

    drive, rest = os.path.splitdrive(pattern)
    if drive:
        rest_pattern = rest.lstrip("/")
        segments = rest_pattern.split("/") if rest_pattern else []
        root = drive + "/"
        return sorted(_disk_glob_walk(segments, root))

    # Handle absolute paths: split off the root prefix so that we walk
    # from "/" (or the drive root on Windows) as our base directory.
    if os.path.isabs(pattern):
        root = os.sep
        rest_pattern = pattern[len(root):]
        rest_pattern = rest_pattern.lstrip(os.sep)
        segments = rest_pattern.split("/") if rest_pattern else []
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
    *, follow_symlinks: bool = False,
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
            # If the source itself is a symlink to a directory and we're not
            # following symlinks, treat it as a single symlink entry.
            if not follow_symlinks and Path(local_path).is_symlink():
                pairs.append((local_path, _normalize_path(target)))
            else:
                for rel in sorted(_walk_local_paths(local_path, follow_symlinks)):
                    full = os.path.join(local_path, rel)
                    repo_file = f"{target}/{rel}"
                    pairs.append((full, _normalize_path(repo_file)))
        elif mode == "contents":
            for rel in sorted(_walk_local_paths(local_path, follow_symlinks)):
                full = os.path.join(local_path, rel)
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
# Sync-specific: hashing & diffing
# ---------------------------------------------------------------------------

_HASH_CHUNK_SIZE = 65536


def _blob_hasher(size: int) -> hashlib._Hash:
    """Return a SHA-1 hasher pre-loaded with the git blob header.

    Git blob OID = SHA-1(``blob <size>\\0`` + content).
    """
    return hashlib.sha1(f"blob {size}\0".encode())


def _local_file_oid(base: Path, rel: str) -> bytes:
    """Compute git blob OID for a local file by streaming through SHA-1.

    Symlinks hash their target string.  Regular files are streamed in
    chunks to avoid loading entire contents into memory.
    """
    return _local_file_oid_abs(base / rel)


def _local_file_oid_abs(full: Path) -> bytes:
    """Compute git blob OID for a local file given its absolute path."""
    if full.is_symlink():
        data = os.readlink(full).encode()
        h = _blob_hasher(len(data))
        h.update(data)
        return h.hexdigest().encode("ascii")
    size = full.stat().st_size
    h = _blob_hasher(size)
    with open(full, "rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().encode("ascii")



def _filter_tree_conflicts(
    write_paths: set[str], deletes: list[str],
) -> list[str]:
    """Remove deletes that conflict with writes at file↔directory boundaries.

    When a write replaces a tree with a blob (e.g. write ``foo``, delete
    ``foo/bar``), the tree builder handles the replacement implicitly —
    the delete is redundant and would cause a conflict in ``rebuild_tree``.
    Similarly, when writes create a subtree that replaces a blob (e.g.
    write ``foo/bar``, delete ``foo``), the delete is also redundant.
    """
    result: list[str] = []
    for d in deletes:
        skip = False
        for w in write_paths:
            # write at foo, delete at foo/bar → skip (blob replaces tree)
            if d.startswith(w + "/"):
                skip = True
                break
            # write at foo/bar, delete at foo → skip (tree replaces blob)
            if w.startswith(d + "/"):
                skip = True
                break
        if not skip:
            result.append(d)
    return result


def _prune_empty_dirs(base: Path) -> None:
    """Remove empty directories under *base* (bottom-up)."""
    for dirpath, _dirnames, _filenames in os.walk(base, topdown=False):
        dp = Path(dirpath)
        if dp == base:
            continue
        try:
            dp.rmdir()  # only succeeds if truly empty
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public API: Copy
# ---------------------------------------------------------------------------

def copy_to_repo(
    fs: FS,
    sources: list[str],
    dest: str,
    *,
    follow_symlinks: bool = False,
    message: str | None = None,
    mode: int | None = None,
    ignore_existing: bool = False,
    delete: bool = False,
    ignore_errors: bool = False,
) -> tuple[FS, CopyReport | None]:
    """Copy local files/dirs/globs into the repo. Returns ``(new_fs, report)``.

    With ``delete=True``, files under *dest* that are not covered by
    *sources* are removed (rsync ``--delete`` semantics).

    When *ignore_errors* is ``True``, per-file errors are collected instead
    of aborting. If **all** files fail, a ``RuntimeError`` is raised.

    Returns ``None`` as the report when there are no actions, errors, or warnings.
    """
    report = CopyReport()

    if ignore_errors:
        resolved: list[tuple[str, str]] = []
        for src in sources:
            try:
                resolved.extend(_resolve_disk_sources([src]))
            except (FileNotFoundError, NotADirectoryError) as exc:
                report.errors.append(CopyError(path=src, error=str(exc)))
        if not resolved:
            if report.errors:
                raise RuntimeError(f"All files failed to copy: {report.errors}")
            return fs, _finalize_report(report)
    else:
        resolved = _resolve_disk_sources(sources)

    pairs = _enum_disk_to_repo(resolved, dest, follow_symlinks=follow_symlinks)

    if delete:
        # Hash-based comparison: build plan then execute
        # Build {repo_rel: local_abs} from enumerated pairs
        pair_map: dict[str, str] = {}
        for local_path, repo_path in pairs:
            # repo_rel is the path relative to dest
            if dest and repo_path.startswith(dest + "/"):
                rel = repo_path[len(dest) + 1:]
            else:
                rel = repo_path
            if rel in pair_map:
                report.warnings.append(CopyError(
                    path=local_path,
                    error=f"Overlapping destination '{rel}': skipping (kept earlier source)",
                ))
            else:
                pair_map[rel] = local_path

        repo_files = _walk_repo(fs, dest)
        local_rels = set(pair_map.keys())
        repo_rels = set(repo_files.keys())

        add_rels = sorted(local_rels - repo_rels)
        delete_rels = sorted(repo_rels - local_rels)
        both = sorted(local_rels & repo_rels)

        update_rels: list[str] = []
        for rel in both:
            try:
                if _local_file_oid_abs(Path(pair_map[rel])) != repo_files[rel]:
                    update_rels.append(rel)
            except OSError as exc:
                if not ignore_errors:
                    raise
                report.errors.append(CopyError(path=pair_map[rel], error=str(exc)))
                update_rels.append(rel)  # treat as needing update

        if ignore_existing:
            update_rels = []

        write_rels = add_rels + update_rels
        if not write_rels and not delete_rels:
            if ignore_errors and report.errors:
                raise RuntimeError(
                    f"All files failed to copy: {report.errors}"
                )
            return fs, _finalize_report(report)

        write_pairs = []
        for rel in write_rels:
            repo_path = f"{dest}/{rel}" if dest else rel
            write_pairs.append((pair_map[rel], repo_path))

        write_path_set = set(write_rels)
        safe_deletes = _filter_tree_conflicts(write_path_set, delete_rels)

        with fs.batch(message=message) as b:
            _write_files_to_repo(b, write_pairs, follow_symlinks=follow_symlinks,
                                 mode=mode, ignore_errors=ignore_errors,
                                 errors=report.errors)
            for rel in safe_deletes:
                full_repo_path = f"{dest}/{rel}" if dest else rel
                try:
                    b.remove(full_repo_path)
                except OSError as exc:
                    if not ignore_errors:
                        raise
                    report.errors.append(CopyError(path=full_repo_path, error=str(exc)))
        result_fs = b.fs

        if ignore_errors and report.errors and result_fs.hash == fs.hash:
            raise RuntimeError(
                f"All files failed to copy: {report.errors}"
            )

        report.add = add_rels
        report.update = update_rels
        report.delete = safe_deletes
        return result_fs, _finalize_report(report)
    else:
        # Non-delete mode: classify written pairs as add vs update
        if ignore_existing:
            pairs = [(l, r) for l, r in pairs if not fs.exists(r)]

        if not pairs:
            if ignore_errors and report.errors:
                raise RuntimeError(
                    f"All files failed to copy: {report.errors}"
                )
            return fs, _finalize_report(report)

        # Classify before writing
        for local_path, repo_path in pairs:
            if dest and repo_path.startswith(dest + "/"):
                rel = repo_path[len(dest) + 1:]
            else:
                rel = repo_path
            if fs.exists(repo_path):
                report.update.append(rel)
            else:
                report.add.append(rel)

        with fs.batch(message=message) as b:
            _write_files_to_repo(b, pairs, follow_symlinks=follow_symlinks,
                                 mode=mode, ignore_errors=ignore_errors,
                                 errors=report.errors)
        result_fs = b.fs

        if ignore_errors and report.errors and result_fs.hash == fs.hash:
            raise RuntimeError(
                f"All files failed to copy: {report.errors}"
            )
        return result_fs, _finalize_report(report)


def copy_from_repo(
    fs: FS,
    sources: list[str],
    dest: str,
    *,
    ignore_existing: bool = False,
    delete: bool = False,
    ignore_errors: bool = False,
) -> CopyReport | None:
    """Copy repo files/dirs/globs to local disk. Returns a ``CopyReport`` or ``None``.

    With ``delete=True``, local files under *dest* that are not covered
    by *sources* are removed (rsync ``--delete`` semantics).

    When *ignore_errors* is ``True``, per-file errors are collected instead
    of aborting. If **all** files fail, a ``RuntimeError`` is raised.

    Returns ``None`` when there are no actions, errors, or warnings.
    """
    import shutil

    report = CopyReport()

    if ignore_errors:
        resolved: list[tuple[str, str]] = []
        for src in sources:
            try:
                resolved.extend(_resolve_repo_sources(fs, [src]))
            except (FileNotFoundError, NotADirectoryError) as exc:
                report.errors.append(CopyError(path=src, error=str(exc)))
        if not resolved:
            if report.errors:
                raise RuntimeError(f"All files failed to copy: {report.errors}")
            return _finalize_report(report)
    else:
        resolved = _resolve_repo_sources(fs, sources)

    pairs = _enum_repo_to_disk(fs, resolved, dest)

    if delete:
        base = Path(dest)
        base.mkdir(parents=True, exist_ok=True)

        # Build {local_rel: repo_path} from enumerated pairs
        pair_map: dict[str, str] = {}
        for repo_path, local_path in pairs:
            rel = os.path.relpath(local_path, dest).replace(os.sep, "/")
            if rel in pair_map:
                report.warnings.append(CopyError(
                    path=repo_path,
                    error=f"Overlapping destination '{rel}': skipping (kept earlier source)",
                ))
            else:
                pair_map[rel] = repo_path

        # B2 fix: build repo_files from pair_map (deduplicated) not pairs
        repo_files = {}
        for rel, rp in pair_map.items():
            entry = _entry_at_path(fs._store._repo, fs._tree_oid, rp)
            if entry is not None:
                repo_files[rel] = entry[0]._sha

        local_paths = _walk_local_paths(dest)
        source_rels = set(pair_map.keys())

        add_rels = sorted(source_rels - local_paths)
        delete_rels = sorted(local_paths - source_rels)
        both = sorted(source_rels & local_paths)

        update_rels: list[str] = []
        for rel in both:
            try:
                if rel in repo_files and _local_file_oid(base, rel) != repo_files[rel]:
                    update_rels.append(rel)
            except OSError as exc:
                if not ignore_errors:
                    raise
                report.errors.append(CopyError(path=str(base / rel), error=str(exc)))
                update_rels.append(rel)  # treat as needing update

        if ignore_existing:
            update_rels = []

        # Process deletes first
        for rel in delete_rels:
            out = base / rel
            try:
                if out.exists() or out.is_symlink():
                    out.unlink()
            except OSError as exc:
                if not ignore_errors:
                    raise
                report.errors.append(CopyError(path=str(out), error=str(exc)))

        # Clear blocking paths
        for rel in add_rels + update_rels:
            out = base / rel
            if out.is_dir() and not out.is_symlink():
                shutil.rmtree(out)
            for parent in out.parents:
                if parent == base:
                    break
                if parent.exists() and not parent.is_dir():
                    parent.unlink()
                    break

        write_pairs = []
        for rel in add_rels + update_rels:
            write_pairs.append((pair_map[rel], str(base / rel)))

        _write_files_to_disk(fs, write_pairs, ignore_errors=ignore_errors,
                             errors=report.errors)
        _prune_empty_dirs(base)

        report.add = add_rels
        report.update = update_rels
        report.delete = delete_rels
    else:
        if ignore_existing:
            pairs = [(r, l) for r, l in pairs if not Path(l).exists()]

        if not pairs:
            if ignore_errors and report.errors:
                raise RuntimeError(
                    f"All files failed to copy: {report.errors}"
                )
            return _finalize_report(report)

        # Classify as add vs update
        for repo_path, local_path in pairs:
            rel = os.path.relpath(local_path, dest).replace(os.sep, "/")
            try:
                exists = Path(local_path).exists()
            except OSError:
                exists = False
            if exists:
                report.update.append(rel)
            else:
                report.add.append(rel)

        _write_files_to_disk(fs, pairs, ignore_errors=ignore_errors,
                             errors=report.errors)

    # Safety check: if all files failed
    if ignore_errors and report.errors and not pairs:
        raise RuntimeError(
            f"All files failed to copy: {report.errors}"
        )

    return _finalize_report(report)


def copy_to_repo_dry_run(
    fs: FS,
    sources: list[str],
    dest: str,
    *,
    follow_symlinks: bool = False,
    ignore_existing: bool = False,
    delete: bool = False,
) -> CopyReport | None:
    """Compute what copy_to_repo would do. Returns a ``CopyReport`` or ``None``."""
    resolved = _resolve_disk_sources(sources)
    pairs = _enum_disk_to_repo(resolved, dest, follow_symlinks=follow_symlinks)

    if delete:
        report = CopyReport()
        pair_map: dict[str, str] = {}
        for local_path, repo_path in pairs:
            if dest and repo_path.startswith(dest + "/"):
                rel = repo_path[len(dest) + 1:]
            else:
                rel = repo_path
            if rel in pair_map:
                report.warnings.append(CopyError(
                    path=local_path,
                    error=f"Overlapping destination '{rel}': skipping (kept earlier source)",
                ))
            else:
                pair_map[rel] = local_path

        repo_files = _walk_repo(fs, dest)
        local_rels = set(pair_map.keys())
        repo_rels = set(repo_files.keys())

        add = sorted(local_rels - repo_rels)
        delete_list = sorted(repo_rels - local_rels)
        both = sorted(local_rels & repo_rels)

        update: list[str] = []
        for rel in both:
            if _local_file_oid_abs(Path(pair_map[rel])) != repo_files[rel]:
                update.append(rel)

        if ignore_existing:
            update = []

        report.add = add
        report.update = update
        report.delete = delete_list
        return _finalize_report(report)
    else:
        # Non-delete mode: classify by existence only
        add: list[str] = []
        update: list[str] = []
        for local_path, repo_path in pairs:
            if dest and repo_path.startswith(dest + "/"):
                rel = repo_path[len(dest) + 1:]
            else:
                rel = repo_path
            if fs.exists(repo_path):
                update.append(rel)
            else:
                add.append(rel)

        if ignore_existing:
            update = []

        return _finalize_report(CopyReport(add=sorted(add), update=sorted(update)))


def copy_from_repo_dry_run(
    fs: FS,
    sources: list[str],
    dest: str,
    *,
    ignore_existing: bool = False,
    delete: bool = False,
) -> CopyReport | None:
    """Compute what copy_from_repo would do. Returns a ``CopyReport`` or ``None``."""
    resolved = _resolve_repo_sources(fs, sources)
    pairs = _enum_repo_to_disk(fs, resolved, dest)

    if delete:
        base = Path(dest)
        report = CopyReport()

        pair_map: dict[str, str] = {}
        for repo_path, local_path in pairs:
            rel = os.path.relpath(local_path, dest).replace(os.sep, "/")
            if rel in pair_map:
                report.warnings.append(CopyError(
                    path=repo_path,
                    error=f"Overlapping destination '{rel}': skipping (kept earlier source)",
                ))
            else:
                pair_map[rel] = repo_path

        repo_files: dict[str, bytes] = {}
        for rel, rp in pair_map.items():
            entry = _entry_at_path(fs._store._repo, fs._tree_oid, rp)
            if entry is not None:
                repo_files[rel] = entry[0]._sha

        local_paths = _walk_local_paths(dest) if base.exists() else set()
        source_rels = set(pair_map.keys())

        add = sorted(source_rels - local_paths)
        delete_list = sorted(local_paths - source_rels)
        both = sorted(source_rels & local_paths)

        update: list[str] = []
        for rel in both:
            if rel in repo_files and _local_file_oid(base, rel) != repo_files[rel]:
                update.append(rel)

        if ignore_existing:
            update = []

        report.add = add
        report.update = update
        report.delete = delete_list
        return _finalize_report(report)
    else:
        # Non-delete mode: classify by existence only
        add: list[str] = []
        update: list[str] = []
        for repo_path, local_path in pairs:
            rel = os.path.relpath(local_path, dest).replace(os.sep, "/")
            if Path(local_path).exists():
                update.append(rel)
            else:
                add.append(rel)

        if ignore_existing:
            update = []

        return _finalize_report(CopyReport(add=sorted(add), update=sorted(update)))


# ---------------------------------------------------------------------------
# Public API: Sync (convenience wrappers with delete=True)
# ---------------------------------------------------------------------------

def _ensure_trailing_slash(path: str) -> str:
    """Ensure *path* ends with ``/`` (contents mode for copy)."""
    return path if path.endswith("/") else path + "/"


def sync_to_repo(
    fs: FS, local_path: str, repo_path: str, *,
    message: str | None = None,
    ignore_errors: bool = False,
) -> tuple[FS, CopyReport | None]:
    """Make *repo_path* identical to *local_path*. Returns ``(new_fs, report)``."""
    try:
        return copy_to_repo(
            fs, [_ensure_trailing_slash(local_path)], repo_path,
            message=message, delete=True, ignore_errors=ignore_errors,
        )
    except (FileNotFoundError, NotADirectoryError):
        # Nonexistent local path → treat as empty source (delete everything)
        new_fs, delete_rels = _sync_delete_all_in_repo(fs, repo_path, message=message)
        if not delete_rels:
            return new_fs, None
        return new_fs, CopyReport(delete=delete_rels)


def _sync_delete_all_in_repo(
    fs: FS, repo_path: str, *, message: str | None = None,
) -> tuple[FS, list[str]]:
    """Delete all files under *repo_path* (used when sync source is empty).

    Returns ``(new_fs, deleted_rels)`` where *deleted_rels* are relative
    to *repo_path*.
    """
    dest = _normalize_path(repo_path) if repo_path else ""
    repo_files = _walk_repo(fs, dest)
    if not repo_files:
        # _walk_repo returns {} for files (not dirs) — check if dest is a file
        if dest and fs.exists(dest) and not fs.is_dir(dest):
            with fs.batch(message=message) as b:
                b.remove(dest)
            return b.fs, [""]
        return fs, []
    with fs.batch(message=message) as b:
        for rel in sorted(repo_files):
            full = f"{dest}/{rel}" if dest else rel
            b.remove(full)
    return b.fs, sorted(repo_files.keys())


def sync_from_repo(
    fs: FS, repo_path: str, local_path: str, *,
    ignore_errors: bool = False,
) -> CopyReport | None:
    """Make *local_path* identical to *repo_path*. Returns a ``CopyReport`` or ``None``."""
    try:
        sources = [_ensure_trailing_slash(repo_path)] if repo_path else [""]
        return copy_from_repo(fs, sources, local_path, delete=True,
                              ignore_errors=ignore_errors)
    except (FileNotFoundError, NotADirectoryError):
        # Nonexistent repo path → treat as empty source (delete everything local)
        delete_rels = _sync_delete_all_local(local_path)
        if not delete_rels:
            return None
        return CopyReport(delete=delete_rels)


def _sync_delete_all_local(local_path: str) -> list[str]:
    """Delete all files under *local_path* and prune empty dirs.

    Returns sorted list of deleted relative paths.
    """
    base = Path(local_path)
    base.mkdir(parents=True, exist_ok=True)
    deleted = sorted(_walk_local_paths(local_path))
    for rel in deleted:
        out = base / rel
        if out.exists() or out.is_symlink():
            out.unlink()
    _prune_empty_dirs(base)
    return deleted


def sync_to_repo_dry_run(
    fs: FS, local_path: str, repo_path: str,
) -> CopyReport | None:
    """Compute what ``sync_to_repo`` would do without writing."""
    try:
        return copy_to_repo_dry_run(
            fs, [_ensure_trailing_slash(local_path)], repo_path, delete=True,
        )
    except (FileNotFoundError, NotADirectoryError):
        # Nonexistent local path → everything in repo is a delete
        dest = _normalize_path(repo_path) if repo_path else ""
        repo_files = _walk_repo(fs, dest)
        if not repo_files and dest and fs.exists(dest) and not fs.is_dir(dest):
            # B1 fix: dest is a single file — relative path within dest is ""
            return CopyReport(delete=[""])
        delete_list = sorted(repo_files.keys())
        return _finalize_report(CopyReport(delete=delete_list))


def sync_from_repo_dry_run(
    fs: FS, repo_path: str, local_path: str,
) -> CopyReport | None:
    """Compute what ``sync_from_repo`` would do without writing."""
    try:
        sources = [_ensure_trailing_slash(repo_path)] if repo_path else [""]
        return copy_from_repo_dry_run(fs, sources, local_path, delete=True)
    except (FileNotFoundError, NotADirectoryError):
        # Nonexistent repo path → everything local is a delete
        local_paths = _walk_local_paths(local_path)
        return _finalize_report(CopyReport(delete=sorted(local_paths)))

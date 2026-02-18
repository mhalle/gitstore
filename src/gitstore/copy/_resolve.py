"""Directory walking, glob expansion, source resolution, and file enumeration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .._glob import _glob_match
from ..tree import _entry_at_path, _normalize_path

if TYPE_CHECKING:
    from .._exclude import ExcludeFilter
    from ..fs import FS


# ---------------------------------------------------------------------------
# Directory walking
# ---------------------------------------------------------------------------

def _walk_local_paths(
    local_path: str, follow_symlinks: bool = False,
    exclude: ExcludeFilter | None = None,
) -> set[str]:
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
    _excl = exclude is not None and exclude.active

    if follow_symlinks:
        seen_realpaths: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
            real = os.path.realpath(dirpath)
            if real in seen_realpaths:
                dirnames.clear()
                continue
            seen_realpaths.add(real)
            dp = Path(dirpath)
            rel_dir = str(dp.relative_to(base)).replace(os.sep, "/")
            if rel_dir == ".":
                rel_dir = ""

            if _excl:
                exclude.enter_directory(dp, rel_dir)
                dirnames[:] = [
                    d for d in dirnames
                    if not exclude.is_excluded_in_walk(
                        f"{rel_dir}/{d}" if rel_dir else d, is_dir=True,
                    )
                ]

            for fname in filenames:
                rel_str = f"{rel_dir}/{fname}" if rel_dir else fname
                if _excl and exclude.is_excluded_in_walk(rel_str):
                    continue
                result.add(rel_str)
    else:
        for dirpath, _dirnames, filenames in os.walk(base):
            dp = Path(dirpath)
            rel_dir = str(dp.relative_to(base)).replace(os.sep, "/")
            if rel_dir == ".":
                rel_dir = ""

            if _excl:
                exclude.enter_directory(dp, rel_dir)
                _dirnames[:] = [
                    d for d in _dirnames
                    if not exclude.is_excluded_in_walk(
                        f"{rel_dir}/{d}" if rel_dir else d, is_dir=True,
                    )
                ]

            for fname in filenames:
                rel_str = f"{rel_dir}/{fname}" if rel_dir else fname
                if _excl and exclude.is_excluded_in_walk(rel_str):
                    continue
                result.add(rel_str)
            symlinked = []
            for dname in _dirnames:
                full = dp / dname
                if full.is_symlink():
                    rel_str = f"{rel_dir}/{dname}" if rel_dir else dname
                    result.add(rel_str)
                    symlinked.append(dname)
            for dname in symlinked:
                _dirnames.remove(dname)
    return result


def _walk_repo(fs: FS, repo_path: str) -> dict[str, tuple[bytes, int]]:
    """Build {relative_path: (oid_hex_bytes, filemode)} for files under *repo_path*.

    The OID values are the raw hex bytes from the repo (not file content),
    suitable for comparison against ``_local_file_oid()`` results.
    The filemode is the git filemode (e.g. 0o100644, 0o100755, 0o120000).
    Returns an empty dict if *repo_path* does not exist or is not a directory.
    """
    result: dict[str, tuple[bytes, int]] = {}
    if repo_path:
        if not fs.exists(repo_path):
            return result
        if not fs.is_dir(repo_path):
            return result
    walk_path = repo_path or None
    for dirpath, _dirs, files in fs.walk(walk_path):
        for fe in files:
            store_path = f"{dirpath}/{fe.name}" if dirpath else fe.name
            if repo_path and store_path.startswith(repo_path + "/"):
                rel = store_path[len(repo_path) + 1:]
            else:
                rel = store_path
            result[rel] = (fe.oid, fe.filemode)
    return result


# ---------------------------------------------------------------------------
# Disk-side glob expansion
# ---------------------------------------------------------------------------

def disk_glob(pattern: str) -> list[str]:
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

    scan_dir = prefix or "."

    if seg == "**":
        # Match zero or more directory levels, skipping dotfiles.
        try:
            entries = os.listdir(scan_dir)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return []
        results: list[str] = []
        # Zero dirs: try matching rest against entries at this level
        if rest:
            results.extend(_disk_glob_walk(rest, prefix))
        else:
            for name in entries:
                if name.startswith("."):
                    continue
                full = os.path.join(prefix, name) if prefix else name
                results.append(full)
        # One+ dirs: recurse into non-dot subdirs (keep ** segment)
        for name in entries:
            if name.startswith("."):
                continue
            full = os.path.join(prefix, name) if prefix else name
            if os.path.isdir(full):
                results.extend(_disk_glob_walk(segments, full))
        return results

    has_wild = "*" in seg or "?" in seg

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

def _resolve_disk_sources(sources: list[str]) -> list[tuple[str, str, str]]:
    """Resolve local source specs into ``(local_path, mode, prefix)`` tuples.

    ``mode`` is one of:
    - ``"file"``    — single file
    - ``"dir"``     — directory, name preserved
    - ``"contents"`` — directory, trailing ``/`` → pour contents

    ``prefix`` is an intermediate path to inject between the destination and
    the file name.  It is ``""`` for normal sources and non-empty when the
    source contains an rsync-style ``/./`` pivot marker (with ``idx > 0``).

    Sources must be literal paths (no glob expansion).  Use :func:`disk_glob`
    to expand patterns before calling this function.
    """
    resolved: list[tuple[str, str, str]] = []
    for src in sources:
        # --- /./  pivot detection (rsync -R style) ---
        # Normalize separators only for the probe so backslash pivots
        # are found on Windows without mangling extended-length paths
        # (\\?\...) or the rest of the source string.
        idx = src.replace(os.sep, "/").find("/./")
        if idx > 0:
            base = src[:idx]
            rest_os = src[idx + 3:]                        # OS-native for full_path
            rest = rest_os.replace(os.sep, "/")            # normalised for contents_mode / prefix
            contents_mode = rest.endswith("/")
            rest_clean = rest.rstrip("/")

            rest_os_clean = rest_os.rstrip("/").rstrip(os.sep)
            full_path = os.path.join(base, rest_os_clean) if rest_os_clean else base

            if not os.path.exists(full_path):
                raise FileNotFoundError(f"Local file not found: {full_path}")

            if os.path.isdir(full_path):
                mode = "contents" if contents_mode else "dir"
            else:
                if contents_mode:
                    raise NotADirectoryError(f"Not a directory: {full_path}")
                mode = "file"

            prefix = "/".join(rest_clean.split("/")[:-1]) if rest_clean else ""
            resolved.append((full_path, mode, prefix))
            continue

        contents_mode = src.endswith("/")

        if contents_mode:
            path = src.rstrip("/")
            if not os.path.isdir(path):
                raise NotADirectoryError(f"Not a directory: {path}")
            resolved.append((path, "contents", ""))
        else:
            if os.path.isdir(src):
                resolved.append((src, "dir", ""))
            elif os.path.exists(src):
                resolved.append((src, "file", ""))
            else:
                raise FileNotFoundError(f"Local file not found: {src}")
    return resolved


def _resolve_repo_sources(fs: FS, sources: list[str]) -> list[tuple[str, str, str]]:
    """Resolve repo source specs into ``(repo_path, mode, prefix)`` tuples.

    ``prefix`` is an intermediate path to inject between the destination and
    the file name.  It is ``""`` for normal sources and non-empty when the
    source contains an rsync-style ``/./`` pivot marker (with ``idx > 0``).

    Sources must be literal paths (no glob expansion).  Use ``fs.glob()``
    to expand patterns before calling this function.
    """
    resolved: list[tuple[str, str, str]] = []
    for src in sources:
        # --- /./  pivot detection (rsync -R style) ---
        # Normalize only for the probe — repo entries may legitimately
        # contain literal backslashes on POSIX.
        idx = src.replace("\\", "/").find("/./")
        if idx > 0:
            base = src[:idx].replace("\\", "/")
            rest = src[idx + 3:].replace("\\", "/")   # normalise for repo paths
            contents_mode = rest.endswith("/")
            rest_clean = rest.rstrip("/")

            full_path = f"{base}/{rest_clean}" if rest_clean else base
            full_path = _normalize_path(full_path)
            if not fs.exists(full_path):
                raise FileNotFoundError(f"File not found in repo: {full_path}")
            if fs.is_dir(full_path):
                mode = "contents" if contents_mode else "dir"
            else:
                if contents_mode:
                    raise NotADirectoryError(f"Not a directory in repo: {full_path}")
                mode = "file"
            prefix = "/".join(rest_clean.split("/")[:-1]) if rest_clean else ""
            resolved.append((full_path, mode, prefix))
            continue

        contents_mode = src.endswith("/")

        if contents_mode:
            path = src.rstrip("/")
            if path:
                path = _normalize_path(path)
            if path and not fs.is_dir(path):
                raise NotADirectoryError(f"Not a directory in repo: {path}")
            resolved.append((path, "contents", ""))
        else:
            if src:
                path = _normalize_path(src)
            else:
                path = ""
            if not path:
                resolved.append(("", "contents", ""))
            elif not fs.exists(path):
                raise FileNotFoundError(f"File not found in repo: {path}")
            elif fs.is_dir(path):
                resolved.append((path, "dir", ""))
            else:
                resolved.append((path, "file", ""))
    return resolved


# ---------------------------------------------------------------------------
# File enumeration (for actual copy and dry-run)
# ---------------------------------------------------------------------------

def _enum_disk_to_repo(
    resolved: list[tuple[str, str, str]], dest: str,
    *, follow_symlinks: bool = False,
    exclude: ExcludeFilter | None = None,
) -> list[tuple[str, str]]:
    """Build ``(local_path, repo_path)`` pairs for disk → repo copy."""
    pairs: list[tuple[str, str]] = []
    for local_path, mode, prefix in resolved:
        # Build the effective destination by injecting the pivot prefix.
        _dest = "/".join(p for p in (dest, prefix) if p)

        if mode == "file":
            name = os.path.basename(local_path)
            # Post-filter single files against base patterns
            if exclude is not None and exclude.active and exclude.is_excluded(name):
                continue
            repo_file = f"{_dest}/{name}" if _dest else name
            pairs.append((local_path, _normalize_path(repo_file)))
        elif mode == "dir":
            dirname = os.path.basename(local_path)
            target = f"{_dest}/{dirname}" if _dest else dirname
            # If the source itself is a symlink to a directory and we're not
            # following symlinks, treat it as a single symlink entry.
            if not follow_symlinks and Path(local_path).is_symlink():
                pairs.append((local_path, _normalize_path(target)))
            else:
                for rel in sorted(_walk_local_paths(local_path, follow_symlinks, exclude=exclude)):
                    full = os.path.join(local_path, rel)
                    repo_file = f"{target}/{rel}"
                    pairs.append((full, _normalize_path(repo_file)))
        elif mode == "contents":
            for rel in sorted(_walk_local_paths(local_path, follow_symlinks, exclude=exclude)):
                full = os.path.join(local_path, rel)
                repo_file = f"{_dest}/{rel}" if _dest else rel
                pairs.append((full, _normalize_path(repo_file)))
    return pairs


def _enum_repo_to_disk(
    fs: FS, resolved: list[tuple[str, str, str]], dest: str,
) -> list[tuple[str, str]]:
    """Build ``(repo_path, local_path)`` pairs for repo → disk copy."""
    pairs: list[tuple[str, str]] = []
    for repo_path, mode, prefix in resolved:
        _dest = os.path.join(dest, prefix) if prefix else dest

        if mode == "file":
            name = repo_path.rsplit("/", 1)[-1]
            local = os.path.join(_dest, name)
            pairs.append((repo_path, local))
        elif mode == "dir":
            dirname = repo_path.rsplit("/", 1)[-1]
            target = os.path.join(_dest, dirname)
            for dirpath, _dirs, files in fs.walk(repo_path):
                for fe in files:
                    store_path = f"{dirpath}/{fe.name}" if dirpath else fe.name
                    if repo_path and store_path.startswith(repo_path + "/"):
                        rel = store_path[len(repo_path) + 1:]
                    else:
                        rel = store_path
                    local = os.path.join(target, rel)
                    pairs.append((store_path, local))
        elif mode == "contents":
            walk_path = repo_path or None
            for dirpath, _dirs, files in fs.walk(walk_path):
                for fe in files:
                    store_path = f"{dirpath}/{fe.name}" if dirpath else fe.name
                    if repo_path and store_path.startswith(repo_path + "/"):
                        rel = store_path[len(repo_path) + 1:]
                    else:
                        rel = store_path
                    local = os.path.join(_dest, rel)
                    pairs.append((store_path, local))
    return pairs


def _enum_repo_to_repo(
    fs: FS, resolved: list[tuple[str, str, str]], dest: str,
) -> list[tuple[str, str]]:
    """Build ``(src_repo_path, dest_repo_path)`` pairs for repo → repo copy."""
    pairs: list[tuple[str, str]] = []
    for repo_path, mode, prefix in resolved:
        _dest = "/".join(p for p in (dest, prefix) if p)

        if mode == "file":
            name = repo_path.rsplit("/", 1)[-1]
            dest_file = f"{_dest}/{name}" if _dest else name
            pairs.append((repo_path, _normalize_path(dest_file)))
        elif mode == "dir":
            dirname = repo_path.rsplit("/", 1)[-1]
            target = f"{_dest}/{dirname}" if _dest else dirname
            for dirpath, _dirs, files in fs.walk(repo_path):
                for fe in files:
                    store_path = f"{dirpath}/{fe.name}" if dirpath else fe.name
                    if repo_path and store_path.startswith(repo_path + "/"):
                        rel = store_path[len(repo_path) + 1:]
                    else:
                        rel = store_path
                    dest_file = f"{target}/{rel}"
                    pairs.append((store_path, _normalize_path(dest_file)))
        elif mode == "contents":
            walk_path = repo_path or None
            for dirpath, _dirs, files in fs.walk(walk_path):
                for fe in files:
                    store_path = f"{dirpath}/{fe.name}" if dirpath else fe.name
                    if repo_path and store_path.startswith(repo_path + "/"):
                        rel = store_path[len(repo_path) + 1:]
                    else:
                        rel = store_path
                    dest_file = f"{_dest}/{rel}" if _dest else rel
                    pairs.append((store_path, _normalize_path(dest_file)))
    return pairs

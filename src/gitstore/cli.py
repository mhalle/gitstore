"""gitstore CLI — copy files into/out of bare git repos."""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path

import click
from gitstore import _compat as pygit2

from .exceptions import StaleSnapshotError
from .repo import GitStore
from .tree import GIT_FILEMODE_BLOB, GIT_FILEMODE_BLOB_EXECUTABLE, GIT_FILEMODE_LINK, GIT_FILEMODE_TREE, _entry_at_path, _normalize_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_repo_path(raw: str) -> tuple[bool, str]:
    """Return (is_repo, path).  A leading ':' marks a repo-side path."""
    if raw.startswith(":"):
        return True, raw[1:].rstrip("/")
    return False, raw


def _strip_colon(raw: str) -> str:
    """Strip an optional leading ':' from a repo-side path."""
    return raw[1:] if raw.startswith(":") else raw


def _normalize_repo_path(path: str) -> str:
    """Normalize and validate a repo-side path via the library's _normalize_path."""
    if not path:
        raise click.ClickException("Repo path must not be empty")
    try:
        return _normalize_path(path)
    except ValueError as exc:
        raise click.ClickException(f"Invalid repo path: {exc}")


def _clean_archive_path(raw: str) -> str:
    """Clean an archive entry path for repo import.

    Strips leading './' components that standard tools like ``tar -cf`` add,
    then delegates to ``_normalize_repo_path``.
    """
    # Collapse leading "./" (e.g. "./dir/file.txt" → "dir/file.txt")
    while raw.startswith("./"):
        raw = raw[2:]
    return _normalize_repo_path(raw)


def _status(ctx, msg):
    """Emit a status message to stderr when verbose mode (-v) is on."""
    if ctx.obj.get("verbose"):
        click.echo(msg, err=True)


def _store_repo(ctx, param, value):
    """Click callback: store --repo value in the context."""
    ctx.ensure_object(dict)
    if value is not None:
        ctx.obj["repo_path"] = value
    return value


def _repo_option(f):
    """Shared --repo/-r option decorator for all commands."""
    return click.option(
        "--repo", "-r", type=click.Path(), envvar="GITSTORE_REPO",
        help="Path to bare git repository (or set GITSTORE_REPO).",
        expose_value=False, callback=_store_repo, is_eager=True,
    )(f)


def _require_repo(ctx) -> str:
    """Get the repo path from context, raising a clear error if missing."""
    repo = ctx.obj.get("repo_path")
    if not repo:
        raise click.ClickException(
            "No repository specified. Use --repo or set GITSTORE_REPO."
        )
    return repo


def _open_store(repo_path: str) -> GitStore:
    try:
        return GitStore.open(repo_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))


def _open_or_create_store(repo_path: str, branch: str = "main") -> GitStore:
    """Open a store, creating it with *branch* if the repo doesn't exist."""
    try:
        return GitStore.open(repo_path)
    except FileNotFoundError:
        return GitStore.open(repo_path, create=branch)


def _open_or_create_bare(repo_path: str) -> GitStore:
    """Open a store, creating a bare repo (no branch) if it doesn't exist."""
    try:
        return GitStore.open(repo_path)
    except FileNotFoundError:
        return GitStore.open(repo_path, create=True)


def _no_create_option(f):
    """Shared --no-create flag for write commands."""
    return click.option(
        "--no-create", "no_create", is_flag=True, default=False,
        help="Do not auto-create the repository if it doesn't exist.",
    )(f)


def _get_branch_fs(store: GitStore, branch: str):
    try:
        return store.branches[branch]
    except KeyError:
        raise click.ClickException(f"Branch not found: {branch}")


def _get_fs(store: GitStore, branch: str, ref: str | None):
    """Resolve an FS from --hash (any ref) or --branch."""
    if ref:
        return _resolve_ref(store, ref)
    return _get_branch_fs(store, branch)


def _normalize_at_path(at_path: str | None) -> str | None:
    """Normalize a --path filter value, returning None if unset."""
    if at_path is None:
        return None
    return _normalize_repo_path(_strip_colon(at_path))


def _parse_before(value: str | None):
    """Parse a --before value into a timezone-aware datetime, or None."""
    if value is None:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise click.ClickException(
            f"Invalid date: {value} (use ISO 8601, e.g. 2024-01-15 or 2024-01-15T14:30:00)"
        )
    if "T" not in value and "t" not in value:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_snapshot(fs, at_path: str | None, match_pattern: str | None, before=None):
    """Narrow *fs* to the first commit matching --path / --match / --before filters."""
    at_path = _normalize_at_path(at_path)
    if at_path is not None or match_pattern is not None or before is not None:
        for entry in fs.log(path=at_path, match=match_pattern, before=before):
            return entry
        raise click.ClickException("No matching commits found")
    return fs


def _detect_archive_format(filename: str) -> str:
    """Detect archive format from filename extension. Returns 'zip' or 'tar'."""
    lower = filename.lower()
    if lower.endswith(".zip"):
        return "zip"
    if any(lower.endswith(ext) for ext in (
        ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
    )):
        return "tar"
    raise click.ClickException(
        f"Cannot detect archive format from extension: {filename}\n"
        f"Use --format zip or --format tar"
    )


def _do_export(ctx, fs, filename: str, fmt: str):
    """Export *fs* contents to an archive file.

    *fmt* must be ``"zip"`` or ``"tar"``.  *filename* may be ``"-"`` for stdout.
    """
    if fmt == "zip":
        to_stdout = filename == "-"
        dest = io.BytesIO() if to_stdout else filename
        repo = fs._store._repo
        root_tree = repo[fs._tree_oid]
        count = 0
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirs, files in fs.walk():
                tree = root_tree
                if dirpath:
                    for seg in dirpath.split("/"):
                        tree = repo[tree[seg].id]
                for fname in files:
                    repo_path = f"{dirpath}/{fname}" if dirpath else fname
                    entry = tree[fname]
                    info = zipfile.ZipInfo(repo_path)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3  # Unix
                    if entry.filemode == GIT_FILEMODE_LINK:
                        info.external_attr = 0o120000 << 16
                        raw = fs.read(repo_path)
                        try:
                            raw.decode()
                        except UnicodeDecodeError:
                            raise click.ClickException(
                                f"Symlink target for {repo_path} is not valid UTF-8"
                            )
                        zf.writestr(info, raw)
                    else:
                        info.external_attr = entry.filemode << 16
                        zf.writestr(info, fs.read(repo_path))
                    count += 1
        if to_stdout:
            click.get_binary_stream("stdout").write(dest.getvalue())
        _status(ctx, f"Wrote {count} file(s) to {filename}")
    else:
        import tarfile

        to_stdout = filename == "-"
        mode = "w:"
        if not to_stdout:
            lower = filename.lower()
            if lower.endswith((".tar.gz", ".tgz")):
                mode = "w:gz"
            elif lower.endswith((".tar.bz2", ".tbz2")):
                mode = "w:bz2"
            elif lower.endswith((".tar.xz", ".txz")):
                mode = "w:xz"

        dest = io.BytesIO() if to_stdout else filename
        repo = fs._store._repo
        root_tree = repo[fs._tree_oid]
        count = 0
        with tarfile.open(fileobj=dest, mode=mode) if to_stdout else tarfile.open(dest, mode=mode) as tf:
            for dirpath, _dirs, files in fs.walk():
                tree = root_tree
                if dirpath:
                    for seg in dirpath.split("/"):
                        tree = repo[tree[seg].id]
                for fname in files:
                    repo_path = f"{dirpath}/{fname}" if dirpath else fname
                    entry = tree[fname]
                    if entry.filemode == GIT_FILEMODE_LINK:
                        info = tarfile.TarInfo(name=repo_path)
                        info.type = tarfile.SYMTYPE
                        raw = fs.read(repo_path)
                        try:
                            info.linkname = raw.decode()
                        except UnicodeDecodeError:
                            raise click.ClickException(
                                f"Symlink target for {repo_path} is not valid UTF-8"
                            )
                        tf.addfile(info)
                    else:
                        data = fs.read(repo_path)
                        info = tarfile.TarInfo(name=repo_path)
                        info.size = len(data)
                        info.mode = entry.filemode & 0o7777
                        tf.addfile(info, io.BytesIO(data))
                    count += 1
        if to_stdout:
            click.get_binary_stream("stdout").write(dest.getvalue())
        _status(ctx, f"Wrote {count} file(s) to {filename}")


def _do_import(ctx, store, branch: str, filename: str, message: str | None, fmt: str):
    """Import an archive into a branch.

    *fmt* must be ``"zip"`` or ``"tar"``.  *filename* may be ``"-"`` for stdin.
    """
    fs = _get_branch_fs(store, branch)

    if fmt == "zip":
        from_stdin = filename == "-"
        if from_stdin:
            stdin_data = io.BytesIO(click.get_binary_stream("stdin").read())
            source = stdin_data
        else:
            source = filename
        if not zipfile.is_zipfile(source):
            raise click.ClickException(f"Not a valid zip file: {filename}")
        if from_stdin:
            stdin_data.seek(0)
        count = 0
        skipped = 0
        try:
            with fs.batch(message=message) as b:
                with zipfile.ZipFile(source, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        repo_path = _clean_archive_path(info.filename)
                        unix_mode = info.external_attr >> 16
                        if (unix_mode & 0o170000) == 0o120000:
                            target = zf.read(info.filename).decode()
                            b.write_symlink(repo_path, target)
                        else:
                            data = zf.read(info.filename)
                            fm = GIT_FILEMODE_BLOB_EXECUTABLE if unix_mode & 0o111 else None
                            b.write(repo_path, data, mode=fm)
                        count += 1
                if count == 0:
                    raise click.ClickException("Zip file contains no files")
        except StaleSnapshotError:
            raise click.ClickException("Branch modified concurrently — retry")
        msg = f"Imported {count} file(s) from {filename}"
        if skipped:
            msg += f" ({skipped} hard link(s) skipped)"
        _status(ctx, msg)
    else:
        import tarfile

        from_stdin = filename == "-"

        if from_stdin:
            source = click.get_binary_stream("stdin")
            try:
                tf = tarfile.open(fileobj=source, mode="r|*")
            except tarfile.TarError as exc:
                raise click.ClickException(f"Not a valid tar archive: {exc}")
        else:
            if not os.path.exists(filename):
                raise click.ClickException(f"File not found: {filename}")
            try:
                tf = tarfile.open(filename, mode="r:*")
            except tarfile.TarError as exc:
                raise click.ClickException(f"Not a valid tar archive: {exc}")

        count = 0
        skipped = 0
        member_info: dict[str, int] = {}
        try:
            with fs.batch(message=message) as b:
                with tf:
                    for member in tf:
                        if member.issym():
                            repo_path = _clean_archive_path(member.name)
                            b.write_symlink(repo_path, member.linkname)
                            count += 1
                        elif member.islnk():
                            repo_path = _clean_archive_path(member.name)
                            try:
                                target = tf.extractfile(member)
                            except Exception:
                                target = None
                            if target is None:
                                click.echo(
                                    f"Warning: skipping hard link (unresolvable in "
                                    f"streaming mode): {member.name} -> {member.linkname}",
                                    err=True,
                                )
                                skipped += 1
                                continue
                            data = target.read()
                            target_name = _clean_archive_path(member.linkname)
                            target_mode = member_info.get(target_name, member.mode)
                            fm = GIT_FILEMODE_BLOB_EXECUTABLE if target_mode & 0o111 else None
                            b.write(repo_path, data, mode=fm)
                            count += 1
                        elif member.isfile():
                            repo_path = _clean_archive_path(member.name)
                            member_info[repo_path] = member.mode
                            data = tf.extractfile(member).read()
                            fm = GIT_FILEMODE_BLOB_EXECUTABLE if member.mode & 0o111 else None
                            b.write(repo_path, data, mode=fm)
                            count += 1
                if count == 0:
                    raise click.ClickException("Tar archive contains no files")
        except StaleSnapshotError:
            raise click.ClickException("Branch modified concurrently — retry")
        msg = f"Imported {count} file(s) from {filename}"
        if skipped:
            msg += f" ({skipped} hard link(s) skipped)"
        _status(ctx, msg)


def _resolve_ref(store: GitStore, ref_str: str):
    """Try branches, then tags, then commit hash."""
    if ref_str in store.branches:
        return store.branches[ref_str]
    if ref_str in store.tags:
        return store.tags[ref_str]
    # Try as commit hash
    try:
        repo = store._repo
        obj = repo.get(ref_str)
        if obj is not None:
            if obj.type != pygit2.GIT_OBJECT_COMMIT:
                raise click.ClickException(
                    f"Object {ref_str} is not a commit"
                )
            from .fs import FS
            return FS(store, obj.id, branch=None)
    except click.ClickException:
        raise
    except (ValueError, KeyError):
        pass
    raise click.ClickException(f"Unknown ref: {ref_str}")



# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Verbose output on stderr.")
@click.pass_context
def main(ctx, verbose):
    """gitstore — a git-backed file store."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.option("--branch", "-b", default="main", help="Initial branch name (default: main).")
@click.option("-f", "--force", is_flag=True, help="Destroy existing repo and recreate.")
@click.pass_context
def init(ctx, branch, force):
    """Create a new bare git repository."""
    repo_path = _require_repo(ctx)
    if force and os.path.exists(repo_path):
        import shutil
        shutil.rmtree(repo_path)
    try:
        GitStore.open(repo_path, create=True, branch=branch)
    except FileExistsError as exc:
        raise click.ClickException(str(exc))
    _status(ctx, f"Initialized {repo_path}")


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.option("-f", "--force", is_flag=True, help="Required to destroy a non-empty repo.")
@click.pass_context
def destroy(ctx, force):
    """Remove a bare git repository.

    Requires -f if the repo contains any branches or tags.
    """
    repo_path = _require_repo(ctx)
    try:
        store = GitStore.open(repo_path)
    except FileNotFoundError:
        raise click.ClickException(f"Repository not found: {repo_path}")

    if not force:
        has_data = len(store.tags) > 0 or any(
            fs.ls() for fs in store.branches.values()
        )
        if has_data:
            raise click.ClickException(
                "Repository is not empty. Use -f to destroy."
            )

    import shutil
    shutil.rmtree(repo_path)
    _status(ctx, f"Destroyed {repo_path}")


# ---------------------------------------------------------------------------
# cp
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("args", nargs=-1, required=True)
@click.option("--branch", "-b", default="main", help="Branch to operate on.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to read from.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.option("--mode", type=click.Choice(["644", "755"]), default=None,
              help="File mode (default: 644).")
@click.option("--follow-symlinks", is_flag=True, default=False,
              help="Follow symlinks instead of preserving them (disk→repo only).")
@click.option("-n", "--dry-run", "dry_run", is_flag=True, default=False,
              help="Show what would be copied without writing.")
@click.option("--ignore-existing", is_flag=True, default=False,
              help="Skip files that already exist at the destination.")
@click.option("--delete", is_flag=True, default=False,
              help="Delete destination files not present in source (like rsync --delete).")
@click.option("--ignore-errors", is_flag=True, default=False,
              help="Skip files that fail and continue copying.")
@_no_create_option
@click.pass_context
def cp(ctx, args, branch, ref, message, mode, follow_symlinks, dry_run, ignore_existing, delete, ignore_errors, no_create):
    """Copy files and directories between disk and repo.

    The last argument is the destination; all preceding arguments are sources.
    Sources must all be the same type (all repo or all local), and the
    destination must be the opposite type.

    Directories are copied recursively with their name preserved.
    A trailing '/' on a source means "contents of" (like rsync).
    Glob patterns (* and ?) are expanded; they do not match leading dots.

    Prefix repo-side paths with ':'.
    """
    from .copy import (
        copy_to_repo, copy_from_repo,
        copy_to_repo_dry_run, copy_from_repo_dry_run,
    )

    if len(args) < 2:
        raise click.ClickException("cp requires at least two arguments (SRC... DEST)")

    raw_sources = args[:-1]
    raw_dest = args[-1]

    # Determine direction
    dest_is_repo = raw_dest.startswith(":")
    src_is_repo = raw_sources[0].startswith(":")
    if any((s.startswith(":")) != src_is_repo for s in raw_sources):
        raise click.ClickException(
            "All source paths must be the same type (all repo or all local)"
        )
    if src_is_repo == dest_is_repo:
        if src_is_repo:
            raise click.ClickException(
                "Both sources and DEST are repo paths — one side must be local"
            )
        raise click.ClickException(
            "Neither sources nor DEST is a repo path — prefix repo paths with ':'"
        )

    if ref and not src_is_repo:
        raise click.ClickException(
            "Cannot write to a commit hash — use --branch for writes"
        )

    repo_path = _require_repo(ctx)
    if not src_is_repo and not dry_run and not no_create:
        store = _open_or_create_store(repo_path, branch)
    else:
        store = _open_store(repo_path)
    fs = _get_fs(store, branch, ref)

    filemode = (GIT_FILEMODE_BLOB_EXECUTABLE if mode == "755"
                else GIT_FILEMODE_BLOB) if mode else None

    # Detect single-plain-file case (no glob, no trailing slash, no directory).
    # In this case, like standard `cp`, the dest is the exact path, not a
    # parent directory.
    single_file_src = (
        len(raw_sources) == 1
        and "*" not in raw_sources[0] and "?" not in raw_sources[0]
        and not raw_sources[0].endswith("/")
    )

    if not src_is_repo:
        # Disk → repo
        dest_path = raw_dest[1:]  # strip leading ':'
        if dest_path:
            dest_path = dest_path.rstrip("/")
            if dest_path:
                dest_path = _normalize_repo_path(dest_path)

        src_raw = raw_sources[0]
        is_single_file = single_file_src and os.path.isfile(src_raw)

        if is_single_file:
            if delete:
                raise click.ClickException(
                    "Cannot use --delete with a single file source."
                )
            # Single file: dest is the exact repo path, unless dest is an
            # existing directory — then place the file inside it.
            local = Path(src_raw)
            if dest_path and fs.is_dir(dest_path):
                repo_file = _normalize_repo_path(f"{dest_path}/{local.name}")
            elif dest_path:
                repo_file = dest_path
            else:
                repo_file = _normalize_repo_path(local.name)
            if ignore_existing and fs.exists(repo_file):
                return
            try:
                if dry_run:
                    click.echo(f"{local} -> :{repo_file}")
                else:
                    with fs.batch(message=message) as b:
                        b.write_from(repo_file, local, mode=filemode)
                    _status(ctx, f"Copied -> :{repo_file}")
            except (FileNotFoundError, OSError) as exc:
                if ignore_errors:
                    click.echo(f"ERROR: {local}: {exc}", err=True)
                    ctx.exit(1)
                else:
                    raise click.ClickException(str(exc))
            except StaleSnapshotError:
                raise click.ClickException("Branch modified concurrently — retry")
        else:
            source_paths = list(raw_sources)
            try:
                if dry_run:
                    plan = copy_to_repo_dry_run(
                        fs, source_paths, dest_path,
                        follow_symlinks=follow_symlinks,
                        ignore_existing=ignore_existing,
                        delete=delete,
                    )
                    for action in plan.actions():
                        prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                        click.echo(f"{prefix} :{dest_path}/{action.path}" if dest_path else f"{prefix} :{action.path}")
                else:
                    _new_fs, errs = copy_to_repo(
                        fs, source_paths, dest_path,
                        follow_symlinks=follow_symlinks,
                        message=message, mode=filemode,
                        ignore_existing=ignore_existing,
                        delete=delete,
                        ignore_errors=ignore_errors,
                    )
                    for e in errs:
                        click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                    _status(ctx, f"Copied -> :{dest_path or '/'}")
                    if errs:
                        ctx.exit(1)
            except (FileNotFoundError, NotADirectoryError) as exc:
                raise click.ClickException(str(exc))
            except StaleSnapshotError:
                raise click.ClickException("Branch modified concurrently — retry")
    else:
        # Repo → disk
        source_paths = [s[1:] for s in raw_sources]  # strip ':'
        dest_path = raw_dest

        src_raw = source_paths[0]
        is_single_repo_file = (
            single_file_src and src_raw
            and not fs.is_dir(_normalize_repo_path(src_raw))
        )

        if is_single_repo_file:
            if delete:
                raise click.ClickException(
                    "Cannot use --delete with a single file source."
                )
            # Single file: dest is the exact local path (or into dir if dir exists)
            src_path = _normalize_repo_path(src_raw)
            if not fs.exists(src_path):
                raise click.ClickException(f"File not found in repo: {src_path}")
            local_dest = Path(dest_path)
            if local_dest.is_dir():
                out = local_dest / Path(src_path).name
            else:
                out = local_dest
            if ignore_existing and out.exists():
                return
            if dry_run:
                click.echo(f":{src_path} -> {out}")
            else:
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    entry = _entry_at_path(fs._store._repo, fs._tree_oid, src_path)
                    if entry and entry[1] == GIT_FILEMODE_LINK:
                        target = fs.readlink(src_path)
                        out.symlink_to(target)
                    else:
                        out.write_bytes(fs.read(src_path))
                except OSError as exc:
                    if ignore_errors:
                        click.echo(f"ERROR: {out}: {exc}", err=True)
                        ctx.exit(1)
                    else:
                        raise click.ClickException(f"Cannot write {out}: {exc}")
                else:
                    _status(ctx, f"Copied :{src_path} -> {out}")
        else:
            try:
                if dry_run:
                    plan = copy_from_repo_dry_run(
                        fs, source_paths, dest_path,
                        ignore_existing=ignore_existing,
                        delete=delete,
                    )
                    for action in plan.actions():
                        prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                        click.echo(f"{prefix} {os.path.join(dest_path, action.path)}")
                else:
                    errs = copy_from_repo(
                        fs, source_paths, dest_path,
                        ignore_existing=ignore_existing,
                        delete=delete,
                        ignore_errors=ignore_errors,
                    )
                    for e in errs:
                        click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                    _status(ctx, f"Copied -> {dest_path}")
                    if errs:
                        ctx.exit(1)
            except (FileNotFoundError, NotADirectoryError) as exc:
                raise click.ClickException(str(exc))
            except OSError as exc:
                raise click.ClickException(str(exc))


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("path", required=False, default=None)
@click.option("--branch", "-b", default="main", help="Branch to list.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to read from.")
@click.pass_context
def ls(ctx, path, branch, ref):
    """List files/directories at PATH (or root)."""
    store = _open_store(_require_repo(ctx))
    fs = _get_fs(store, branch, ref)

    repo_path = None
    if path is not None:
        repo_path = _strip_colon(path)
        if repo_path:
            repo_path = _normalize_repo_path(repo_path)

    try:
        entries = fs.ls(repo_path if repo_path else None)
    except FileNotFoundError:
        raise click.ClickException(f"Path not found: {repo_path}")
    except NotADirectoryError:
        raise click.ClickException(f"Not a directory: {repo_path}")

    for entry in sorted(entries):
        click.echo(entry)


# ---------------------------------------------------------------------------
# cat
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("path")
@click.option("--branch", "-b", default="main", help="Branch to read from.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to read from.")
@click.pass_context
def cat(ctx, path, branch, ref):
    """Print file contents to stdout."""
    repo_path = _normalize_repo_path(_strip_colon(path))

    store = _open_store(_require_repo(ctx))
    fs = _get_fs(store, branch, ref)

    try:
        data = fs.read(repo_path)
    except FileNotFoundError:
        raise click.ClickException(f"File not found: {repo_path}")
    except IsADirectoryError:
        raise click.ClickException(f"{repo_path} is a directory, not a file")

    sys.stdout.buffer.write(data)


# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("path")
@click.option("--branch", "-b", default="main", help="Branch to remove from.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.pass_context
def rm(ctx, path, branch, message):
    """Remove a file from the repo."""
    store = _open_store(_require_repo(ctx))
    fs = _get_branch_fs(store, branch)

    repo_path = _normalize_repo_path(_strip_colon(path))

    try:
        fs.remove(repo_path, message=message)
    except FileNotFoundError:
        raise click.ClickException(f"File not found: {repo_path}")
    except IsADirectoryError:
        raise click.ClickException(f"{repo_path} is a directory, not a file")
    except StaleSnapshotError:
        raise click.ClickException(
            "Branch modified concurrently — retry"
        )
    _status(ctx, f"Removed :{repo_path}")


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.option("--path", "at_path", default=None, help="Filter to commits that changed this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.option("--before", "before", default=None, help="Only commits on or before this date (ISO 8601).")
@click.option("--branch", "-b", default="main", help="Branch to show log for.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to start from.")
@click.option("--format", "fmt", default="text",
              type=click.Choice(["text", "json", "jsonl"]),
              help="Output format.")
@click.pass_context
def log(ctx, at_path, deprecated_at, match_pattern, before, branch, ref, fmt):
    """Show commit log, optionally filtered by path and/or message pattern."""
    at_path = at_path or deprecated_at
    store = _open_store(_require_repo(ctx))
    fs = _get_fs(store, branch, ref)

    before = _parse_before(before)
    at_path = _normalize_at_path(at_path)
    entries = list(fs.log(path=at_path, match=match_pattern, before=before))

    if fmt == "json":
        click.echo(json.dumps([_log_entry_dict(e) for e in entries], indent=2))
    elif fmt == "jsonl":
        for entry in entries:
            click.echo(json.dumps(_log_entry_dict(entry)))
    else:
        for entry in entries:
            click.echo(f"{entry.hash[:7]}  {entry.time.isoformat()}  {entry.message}")


def _log_entry_dict(entry) -> dict:
    return {
        "hash": entry.hash,
        "message": entry.message,
        "time": entry.time.isoformat(),
        "author_name": entry.author_name,
        "author_email": entry.author_email,
        "branch": entry.branch,
    }


# ---------------------------------------------------------------------------
# branch (group)
# ---------------------------------------------------------------------------

@main.group(invoke_without_command=True)
@_repo_option
@click.pass_context
def branch(ctx):
    """Manage branches."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(branch_list)


@branch.command("list")
@_repo_option
@click.pass_context
def branch_list(ctx):
    """List all branches."""
    store = _open_store(_require_repo(ctx))
    for name in sorted(store.branches):
        click.echo(name)


@branch.command("create")
@_repo_option
@click.argument("name")
@click.option("--from", "from_ref", default=None, help="Ref to fork from.")
@click.option("--path", "at_path", default=None,
              help="Point to latest commit that modified this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.option("--before", "before", default=None, help="Only commits on or before this date (ISO 8601).")
@click.pass_context
def branch_create(ctx, name, from_ref, at_path, deprecated_at, match_pattern, before):
    """Create a new branch NAME, optionally forking from an existing ref."""
    at_path = at_path or deprecated_at
    store = _open_store(_require_repo(ctx))

    if name in store.branches:
        raise click.ClickException(f"Branch already exists: {name}")

    has_filters = at_path is not None or match_pattern is not None or before is not None
    if from_ref is None:
        if has_filters:
            raise click.ClickException("--path/--match/--before require --from")
        repo = store._repo
        sig = store._signature
        tree_oid = repo.TreeBuilder().write()
        commit_oid = repo.create_commit(
            f"refs/heads/{name}", sig, sig,
            f"Initialize {name}", tree_oid, [],
        )
    else:
        before = _parse_before(before)
        source_fs = _resolve_snapshot(_resolve_ref(store, from_ref), at_path, match_pattern, before)
        from .fs import FS
        new_fs = FS(store, source_fs._commit_oid, branch=name)
        store.branches[name] = new_fs
    _status(ctx, f"Created branch {name}")


@branch.command("delete")
@_repo_option
@click.argument("name")
@click.pass_context
def branch_delete(ctx, name):
    """Delete branch NAME."""
    store = _open_store(_require_repo(ctx))
    try:
        del store.branches[name]
    except KeyError:
        raise click.ClickException(f"Branch not found: {name}")
    _status(ctx, f"Deleted branch {name}")


# ---------------------------------------------------------------------------
# tag (group)
# ---------------------------------------------------------------------------

@main.group(invoke_without_command=True)
@_repo_option
@click.pass_context
def tag(ctx):
    """Manage tags."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(tag_list)


@tag.command("list")
@_repo_option
@click.pass_context
def tag_list(ctx):
    """List all tags."""
    store = _open_store(_require_repo(ctx))
    for name in sorted(store.tags):
        click.echo(name)


@tag.command("create")
@_repo_option
@click.argument("name")
@click.argument("from_ref", metavar="FROM")
@click.option("--path", "at_path", default=None,
              help="Point to latest commit that modified this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.option("--before", "before", default=None, help="Only commits on or before this date (ISO 8601).")
@click.pass_context
def tag_create(ctx, name, from_ref, at_path, deprecated_at, match_pattern, before):
    """Create a new tag NAME from FROM ref."""
    at_path = at_path or deprecated_at
    before = _parse_before(before)
    store = _open_store(_require_repo(ctx))

    if name in store.tags:
        raise click.ClickException(f"Tag already exists: {name}")

    source_fs = _resolve_snapshot(_resolve_ref(store, from_ref), at_path, match_pattern, before)

    from .fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=None)
    store.tags[name] = new_fs
    _status(ctx, f"Created tag {name}")


@tag.command("delete")
@_repo_option
@click.argument("name")
@click.pass_context
def tag_delete(ctx, name):
    """Delete tag NAME."""
    store = _open_store(_require_repo(ctx))
    try:
        del store.tags[name]
    except KeyError:
        raise click.ClickException(f"Tag not found: {name}")
    _status(ctx, f"Deleted tag {name}")


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------

@main.command("zip")
@_repo_option
@click.argument("filename", type=click.Path())
@click.option("--branch", "-b", default="main", help="Branch to export from.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to export from.")
@click.option("--path", "at_path", default=None, help="Filter to commits that changed this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.option("--before", "before", default=None, help="Only commits on or before this date (ISO 8601).")
@click.pass_context
def zip_cmd(ctx, filename, branch, ref, at_path, deprecated_at, match_pattern, before):
    """Export repo contents to a zip file.

    FILENAME is the output zip path on disk.  Use '-' to write to stdout.
    """
    at_path = at_path or deprecated_at
    before = _parse_before(before)
    store = _open_store(_require_repo(ctx))
    fs = _resolve_snapshot(_get_fs(store, branch, ref), at_path, match_pattern, before)
    _do_export(ctx, fs, filename, "zip")


# ---------------------------------------------------------------------------
# unzip
# ---------------------------------------------------------------------------

@main.command("unzip")
@_repo_option
@click.argument("filename", type=click.Path(exists=True))
@click.option("--branch", "-b", default="main", help="Branch to import into.")
@click.option("-m", "message", default=None, help="Commit message.")
@_no_create_option
@click.pass_context
def unzip_cmd(ctx, filename, branch, message, no_create):
    """Import a zip file into the repo.

    FILENAME is the path to the zip file on disk.
    """
    repo_path = _require_repo(ctx)
    store = _open_store(repo_path) if no_create else _open_or_create_store(repo_path, branch)
    _do_import(ctx, store, branch, filename, message, "zip")


# ---------------------------------------------------------------------------
# tar
# ---------------------------------------------------------------------------

@main.command("tar")
@_repo_option
@click.argument("filename", type=click.Path())
@click.option("--branch", "-b", default="main", help="Branch to export from.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to export from.")
@click.option("--path", "at_path", default=None, help="Filter to commits that changed this path.")
@click.option("--at", "deprecated_at", default=None, hidden=True)
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.option("--before", "before", default=None, help="Only commits on or before this date (ISO 8601).")
@click.pass_context
def tar_cmd(ctx, filename, branch, ref, at_path, deprecated_at, match_pattern, before):
    """Export repo contents to a tar archive.

    FILENAME is the output tar path on disk.  Use '-' to write to stdout.
    Compression is auto-detected from the filename extension (.tar.gz, .tar.bz2, .tar.xz).
    """
    at_path = at_path or deprecated_at
    before = _parse_before(before)
    store = _open_store(_require_repo(ctx))
    fs = _resolve_snapshot(_get_fs(store, branch, ref), at_path, match_pattern, before)
    _do_export(ctx, fs, filename, "tar")


# ---------------------------------------------------------------------------
# untar
# ---------------------------------------------------------------------------

@main.command("untar")
@_repo_option
@click.argument("filename", type=click.Path(), default="-")
@click.option("--branch", "-b", default="main", help="Branch to import into.")
@click.option("-m", "message", default=None, help="Commit message.")
@_no_create_option
@click.pass_context
def untar_cmd(ctx, filename, branch, message, no_create):
    """Import a tar archive into the repo.

    FILENAME is the path to the tar file on disk.  Use '-' to read from stdin
    (the default).  Compression is auto-detected.
    """
    repo_path = _require_repo(ctx)
    store = _open_store(repo_path) if no_create else _open_or_create_store(repo_path, branch)
    _do_import(ctx, store, branch, filename, message, "tar")


# ---------------------------------------------------------------------------
# archive / unarchive
# ---------------------------------------------------------------------------

@main.command("archive")
@_repo_option
@click.argument("filename", type=click.Path())
@click.option("--format", "fmt", type=click.Choice(["zip", "tar"]), default=None,
              help="Archive format (auto-detected from extension if omitted).")
@click.option("--branch", "-b", default="main", help="Branch to export from.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash.")
@click.option("--path", "at_path", default=None, help="Filter to commits that changed this path.")
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.option("--before", "before", default=None, help="Only commits on or before this date (ISO 8601).")
@click.pass_context
def archive_cmd(ctx, filename, fmt, branch, ref, at_path, match_pattern, before):
    """Export repo contents to an archive file.

    Format is auto-detected from FILENAME extension (.zip, .tar, .tar.gz, etc.).
    Use --format to override.  Use '-' for stdout (requires --format).
    """
    if fmt is None:
        if filename == "-":
            raise click.ClickException("Use --format with stdout (-)")
        fmt = _detect_archive_format(filename)
    before = _parse_before(before)
    store = _open_store(_require_repo(ctx))
    fs = _resolve_snapshot(_get_fs(store, branch, ref), at_path, match_pattern, before)
    _do_export(ctx, fs, filename, fmt)


@main.command("unarchive")
@_repo_option
@click.argument("filename", type=click.Path(), default=None, required=False)
@click.option("--format", "fmt", type=click.Choice(["zip", "tar"]), default=None,
              help="Archive format (auto-detected from extension if omitted).")
@click.option("--branch", "-b", default="main", help="Branch to import into.")
@click.option("-m", "message", default=None, help="Commit message.")
@_no_create_option
@click.pass_context
def unarchive_cmd(ctx, filename, fmt, branch, message, no_create):
    """Import an archive file into the repo.

    Format is auto-detected from FILENAME extension.
    Use --format to override.  Reads stdin when FILENAME is omitted or '-'
    (requires --format).
    """
    if filename is None or filename == "-":
        filename = "-"
        if fmt is None:
            raise click.ClickException("Use --format when reading from stdin")
    else:
        if fmt is None:
            fmt = _detect_archive_format(filename)
    repo_path = _require_repo(ctx)
    store = _open_store(repo_path) if no_create else _open_or_create_store(repo_path, branch)
    _do_import(ctx, store, branch, filename, message, fmt)


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

@main.command("backup")
@_repo_option
@click.argument("url")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would change without transferring data.")
@click.pass_context
def backup_cmd(ctx, url, dry_run):
    """Push all refs to a remote URL, creating an exact mirror.

    Force-overwrites diverged refs and deletes remote-only refs.
    """
    from .mirror import resolve_credentials, print_diff, progress_cb

    store = _open_store(_require_repo(ctx))
    auth_url = resolve_credentials(url)
    diff = store.backup(auth_url, dry_run=dry_run, progress=progress_cb(ctx))
    if dry_run:
        print_diff(diff, "push")
    else:
        _status(ctx, f"Backed up to {url}")


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

@main.command("restore")
@_repo_option
@click.argument("url")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would change without transferring data.")
@_no_create_option
@click.pass_context
def restore_cmd(ctx, url, dry_run, no_create):
    """Fetch all refs from a remote URL, overwriting local state.

    Force-overwrites diverged refs and deletes local-only refs.
    """
    from .mirror import resolve_credentials, print_diff, progress_cb

    repo_path = _require_repo(ctx)
    store = _open_store(repo_path) if no_create else _open_or_create_bare(repo_path)
    auth_url = resolve_credentials(url)
    diff = store.restore(auth_url, dry_run=dry_run, progress=progress_cb(ctx))
    if dry_run:
        print_diff(diff, "pull")
    else:
        _status(ctx, f"Restored from {url}")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

@main.command()
@_repo_option
@click.argument("args", nargs=-1, required=True)
@click.option("--branch", "-b", default="main", help="Branch to operate on.")
@click.option("--hash", "ref", default=None, help="Branch, tag, or commit hash to read from.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.option("-n", "--dry-run", "dry_run", is_flag=True, default=False,
              help="Show what would change without writing.")
@click.option("--ignore-errors", is_flag=True, default=False,
              help="Skip files that fail and continue.")
@_no_create_option
@click.pass_context
def sync(ctx, args, branch, ref, message, dry_run, ignore_errors, no_create):
    """Make one path identical to another (like rsync --delete).

    With one argument, syncs a local directory to the repo root:

        gitstore sync ./dir

    With two arguments, direction is determined by the ':' prefix:

        gitstore sync ./local :repo_path   (disk → repo)
        gitstore sync :repo_path ./local    (repo → disk)
    """
    from .copy import (
        sync_to_repo, sync_from_repo,
        sync_to_repo_dry_run, sync_from_repo_dry_run,
    )

    if len(args) == 1:
        # 1-arg form: sync local dir to repo root
        if args[0].startswith(":"):
            raise click.ClickException(
                "Single-argument sync must be a local path, not a repo path"
            )
        local_path = args[0]
        repo_dest = ""
        direction = "to_repo"
    elif len(args) == 2:
        src, dest = args
        src_is_repo = src.startswith(":")
        dest_is_repo = dest.startswith(":")
        if src_is_repo and dest_is_repo:
            raise click.ClickException(
                "Both arguments are repo paths — one side must be local"
            )
        if not src_is_repo and not dest_is_repo:
            raise click.ClickException(
                "Neither argument is a repo path — prefix repo paths with ':'"
            )
        if not src_is_repo:
            # disk → repo
            local_path = src
            repo_dest = dest[1:].rstrip("/")
            direction = "to_repo"
        else:
            # repo → disk
            repo_dest = src[1:].rstrip("/")
            local_path = dest
            direction = "from_repo"
    else:
        raise click.ClickException("sync requires 1 or 2 arguments")

    if ref and direction == "to_repo":
        raise click.ClickException(
            "Cannot write to a commit hash — use --branch for writes"
        )

    repo_path = _require_repo(ctx)
    if direction == "to_repo" and not dry_run and not no_create:
        store = _open_or_create_store(repo_path, branch)
    else:
        store = _open_store(repo_path)
    fs = _get_fs(store, branch, ref)

    try:
        if direction == "to_repo":
            if dry_run:
                plan = sync_to_repo_dry_run(fs, local_path, repo_dest)
                for action in plan.actions():
                    prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                    click.echo(f"{prefix} :{repo_dest}/{action.path}" if repo_dest else f"{prefix} :{action.path}")
            else:
                _new_fs, errs = sync_to_repo(
                    fs, local_path, repo_dest,
                    message=message, ignore_errors=ignore_errors,
                )
                for e in errs:
                    click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                _status(ctx, f"Synced -> :{repo_dest or '/'}")
                if errs:
                    ctx.exit(1)
        else:
            if dry_run:
                plan = sync_from_repo_dry_run(fs, repo_dest, local_path)
                for action in plan.actions():
                    prefix = {"add": "+", "update": "~", "delete": "-"}[action.action]
                    click.echo(f"{prefix} {os.path.join(local_path, action.path)}")
            else:
                errs = sync_from_repo(
                    fs, repo_dest, local_path,
                    ignore_errors=ignore_errors,
                )
                for e in errs:
                    click.echo(f"ERROR: {e.path}: {e.error}", err=True)
                _status(ctx, f"Synced -> {local_path}")
                if errs:
                    ctx.exit(1)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise click.ClickException(str(exc))
    except StaleSnapshotError:
        raise click.ClickException("Branch modified concurrently — retry")

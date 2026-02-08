"""gitstore CLI — copy files into/out of bare git repos."""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path

import click
import pygit2

from .exceptions import StaleSnapshotError
from .repo import GitStore
from .tree import GIT_FILEMODE_BLOB, GIT_FILEMODE_BLOB_EXECUTABLE, _normalize_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_repo_path(raw: str) -> tuple[bool, str]:
    """Return (is_repo, path).  A leading ':' marks a repo-side path."""
    if raw.startswith(":"):
        return True, raw[1:].rstrip("/")
    return False, raw


def _normalize_repo_path(path: str) -> str:
    """Normalize and validate a repo-side path via the library's _normalize_path."""
    if not path:
        raise click.ClickException("Repo path must not be empty")
    try:
        return _normalize_path(path)
    except ValueError as exc:
        raise click.ClickException(f"Invalid repo path: {exc}")


def _status(ctx, msg):
    """Emit a status message to stderr when verbose mode (-v) is on."""
    if ctx.obj.get("verbose"):
        click.echo(msg, err=True)


def _open_store(repo_path: str) -> GitStore:
    try:
        return GitStore.open(repo_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))


def _get_branch_fs(store: GitStore, branch: str):
    try:
        return store.branches[branch]
    except KeyError:
        raise click.ClickException(f"Branch not found: {branch}")


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


def _resolve_with_at(store: GitStore, ref_str: str, at_path: str | None):
    """Resolve ref; if --at given, find latest commit that touched that path."""
    fs = _resolve_ref(store, ref_str)
    if at_path is None:
        return fs
    at_path = _normalize_repo_path(at_path)
    for entry in fs.log(at_path):
        return entry
    raise click.ClickException(
        f"No commits found that modified path: {at_path}"
    )


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------

@click.group()
@click.argument("repo", type=click.Path())
@click.option("-v", "--verbose", is_flag=True, help="Verbose output on stderr.")
@click.pass_context
def main(ctx, repo, verbose):
    """gitstore — a git-backed file store.

    REPO is the path to a bare git repository.
    """
    ctx.ensure_object(dict)
    ctx.obj["repo_path"] = repo
    ctx.obj["verbose"] = verbose


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
@click.option("--branch", "-b", default="main", help="Initial branch name (default: main).")
@click.pass_context
def init(ctx, branch):
    """Create a new bare git repository."""
    repo_path = ctx.obj["repo_path"]
    try:
        GitStore.open(repo_path, create=True, branch=branch)
    except FileExistsError as exc:
        raise click.ClickException(str(exc))
    _status(ctx, f"Initialized {repo_path}")


# ---------------------------------------------------------------------------
# cp
# ---------------------------------------------------------------------------

@main.command()
@click.argument("args", nargs=-1, required=True)
@click.option("--branch", "-b", default="main", help="Branch to operate on.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.option("--mode", type=click.Choice(["644", "755"]), default=None,
              help="File mode (default: 644).")
@click.pass_context
def cp(ctx, args, branch, message, mode):
    """Copy files between disk and repo.

    The last argument is the destination; all preceding arguments are sources.
    Sources must all be the same type (all repo or all local), and the
    destination must be the opposite type.  With multiple sources the
    destination must be a directory.

    Prefix repo-side paths with ':'.
    """
    if len(args) < 2:
        raise click.ClickException("cp requires at least two arguments (SRC... DEST)")

    raw_sources = args[:-1]
    raw_dest = args[-1]

    # Parse all paths
    parsed_sources = [_parse_repo_path(s) for s in raw_sources]
    dest_is_repo, dest_path = _parse_repo_path(raw_dest)

    # Validate: all sources must be the same type
    src_is_repo = parsed_sources[0][0]
    if any(p[0] != src_is_repo for p in parsed_sources):
        raise click.ClickException(
            "All source paths must be the same type (all repo or all local)"
        )

    # Source and dest must be opposite types
    if src_is_repo == dest_is_repo:
        if src_is_repo:
            raise click.ClickException(
                "Both sources and DEST are repo paths — one side must be local"
            )
        raise click.ClickException(
            "Neither sources nor DEST is a repo path — prefix repo paths with ':'"
        )

    multi = len(parsed_sources) > 1

    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

    filemode = (GIT_FILEMODE_BLOB_EXECUTABLE if mode == "755"
                else GIT_FILEMODE_BLOB) if mode else None

    if not src_is_repo:
        # Disk → repo
        if multi:
            dest_path = _normalize_repo_path(dest_path) if dest_path else ""
        writes: dict[str, bytes | tuple[bytes, int]] = {}
        for _is_repo, src_path in parsed_sources:
            local = Path(src_path)
            if local.is_dir():
                raise click.ClickException(
                    f"{src_path} is a directory — use cptree for directories"
                )
            try:
                data = local.read_bytes()
            except FileNotFoundError:
                raise click.ClickException(f"Local file not found: {src_path}")
            except OSError as exc:
                raise click.ClickException(f"Cannot read {src_path}: {exc}")
            if dest_path:
                if multi:
                    repo_file = _normalize_repo_path(f"{dest_path}/{local.name}")
                else:
                    repo_file = _normalize_repo_path(dest_path)
            else:
                # Bare ":" — copy to root, keep original filename
                repo_file = _normalize_repo_path(local.name)
            writes[repo_file] = (data, filemode) if filemode else data
        msg = message or ""
        try:
            fs._commit_changes(writes, set(), msg)
        except StaleSnapshotError:
            raise click.ClickException(
                "Branch modified concurrently — retry"
            )
        for repo_file in writes:
            _status(ctx, f"Copied -> :{repo_file}")
    else:
        # Repo → disk
        local_dest = Path(dest_path)
        if multi and not local_dest.is_dir():
            try:
                local_dest.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise click.ClickException(f"Cannot create directory {local_dest}: {exc}")
        for _is_repo, src_path in parsed_sources:
            src_path = _normalize_repo_path(src_path)
            try:
                data = fs.read(src_path)
            except FileNotFoundError:
                raise click.ClickException(f"File not found in repo: {src_path}")
            except IsADirectoryError:
                raise click.ClickException(
                    f"{src_path} is a directory — use cptree for directories"
                )
            out = local_dest
            if local_dest.is_dir():
                out = local_dest / Path(src_path).name
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            except OSError as exc:
                raise click.ClickException(f"Cannot write {out}: {exc}")
            _status(ctx, f"Copied :{src_path} -> {out}")


# ---------------------------------------------------------------------------
# cptree
# ---------------------------------------------------------------------------

@main.command()
@click.argument("src")
@click.argument("dest")
@click.option("--branch", "-b", default="main", help="Branch to operate on.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.pass_context
def cptree(ctx, src, dest, branch, message):
    """Copy a directory tree between disk and repo.

    Prefix repo-side paths with ':'.
    """
    src_is_repo, src_path = _parse_repo_path(src)
    dest_is_repo, dest_path = _parse_repo_path(dest)

    if src_is_repo == dest_is_repo:
        if src_is_repo:
            raise click.ClickException(
                "Both SRC and DEST are repo paths — one must be a local path"
            )
        raise click.ClickException(
            "Neither SRC nor DEST is a repo path — prefix repo paths with ':'"
        )

    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

    if not src_is_repo:
        # Disk → repo
        if dest_path:
            dest_path = _normalize_repo_path(dest_path)
        local = Path(src_path)
        if not local.is_dir():
            raise click.ClickException(
                f"{src_path} is not a directory"
            )
        writes: dict[str, bytes] = {}
        for dirpath, _dirnames, filenames in os.walk(local):
            for fname in filenames:
                full = Path(dirpath) / fname
                rel = full.relative_to(local)
                repo_file = f"{dest_path}/{rel}" if dest_path else str(rel)
                repo_file = repo_file.replace(os.sep, "/")
                repo_file = _normalize_repo_path(repo_file)
                try:
                    writes[repo_file] = full.read_bytes()
                except OSError as exc:
                    raise click.ClickException(f"Cannot read {full}: {exc}")
        if not writes:
            raise click.ClickException(
                f"No files found in directory: {src_path}"
            )
        msg = message or ""
        try:
            fs._commit_changes(writes, set(), msg)
        except StaleSnapshotError:
            raise click.ClickException(
                "Branch modified concurrently — retry"
            )
        _status(ctx, f"Copied {len(writes)} file(s) -> :{dest_path or '/'}")
    else:
        # Repo → disk
        local_dest = Path(dest_path)
        try:
            local_dest.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise click.ClickException(f"Cannot create directory {local_dest}: {exc}")
        if src_path:
            src_path = _normalize_repo_path(src_path)
        src_repo_path = src_path or None
        try:
            for dirpath, _dirs, files in fs.walk(src_repo_path):
                for fname in files:
                    if dirpath:
                        store_path = f"{dirpath}/{fname}"
                    else:
                        store_path = fname
                    # Strip the src_path prefix to get relative path
                    if src_path and store_path.startswith(src_path + "/"):
                        rel = store_path[len(src_path) + 1:]
                    else:
                        rel = store_path
                    out = local_dest / rel
                    try:
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(fs.read(store_path))
                    except OSError as exc:
                        raise click.ClickException(f"Cannot write {out}: {exc}")
        except FileNotFoundError:
            raise click.ClickException(
                f"Path not found in repo: {src_path}"
            )
        except NotADirectoryError:
            raise click.ClickException(
                f"{src_path} is not a directory in the repo"
            )
        _status(ctx, f"Copied :{src_path or '/'} -> {local_dest}")


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

@main.command()
@click.argument("path", required=False, default=None)
@click.option("--branch", "-b", default="main", help="Branch to list.")
@click.pass_context
def ls(ctx, path, branch):
    """List files/directories at PATH (or root).

    Prefix repo paths with ':'.
    """
    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

    repo_path = None
    if path is not None:
        is_repo, repo_path = _parse_repo_path(path)
        if not is_repo:
            raise click.ClickException(
                "PATH must be a repo path prefixed with ':'"
            )
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
@click.argument("path")
@click.option("--branch", "-b", default="main", help="Branch to read from.")
@click.pass_context
def cat(ctx, path, branch):
    """Print file contents to stdout.

    PATH must be a repo path prefixed with ':'.
    """
    is_repo, repo_path = _parse_repo_path(path)
    if not is_repo:
        raise click.ClickException(
            "PATH must be a repo path prefixed with ':'"
        )

    repo_path = _normalize_repo_path(repo_path)

    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

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
@click.argument("path")
@click.option("--branch", "-b", default="main", help="Branch to remove from.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.pass_context
def rm(ctx, path, branch, message):
    """Remove a file from the repo.

    PATH must be a repo path prefixed with ':'.
    """
    is_repo, repo_path = _parse_repo_path(path)
    if not is_repo:
        raise click.ClickException(
            "PATH must be a repo path prefixed with ':'"
        )

    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

    repo_path = _normalize_repo_path(repo_path)

    if not fs.exists(repo_path):
        raise click.ClickException(f"File not found: {repo_path}")

    msg = message or ""
    try:
        fs._commit_changes({}, {repo_path}, msg)
    except StaleSnapshotError:
        raise click.ClickException(
            "Branch modified concurrently — retry"
        )
    _status(ctx, f"Removed :{repo_path}")


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@main.command()
@click.option("--at", "at_path", default=None, help="Filter to commits that changed this path.")
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.option("--branch", "-b", default="main", help="Branch to show log for.")
@click.option("--format", "fmt", default="text",
              type=click.Choice(["text", "json", "jsonl"]),
              help="Output format.")
@click.pass_context
def log(ctx, at_path, match_pattern, branch, fmt):
    """Show commit log, optionally filtered by path and/or message pattern."""
    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

    if at_path is not None:
        at_path = _normalize_repo_path(at_path)

    entries = list(fs.log(at=at_path, match=match_pattern))

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
@click.pass_context
def branch(ctx):
    """Manage branches."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(branch_list)


@branch.command("list")
@click.pass_context
def branch_list(ctx):
    """List all branches."""
    store = _open_store(ctx.obj["repo_path"])
    for name in sorted(store.branches):
        click.echo(name)


@branch.command("create")
@click.argument("name")
@click.argument("from_ref", metavar="FROM")
@click.option("--at", "at_path", default=None,
              help="Point to latest commit that modified this path.")
@click.pass_context
def branch_create(ctx, name, from_ref, at_path):
    """Create a new branch NAME from FROM ref."""
    store = _open_store(ctx.obj["repo_path"])

    if name in store.branches:
        raise click.ClickException(f"Branch already exists: {name}")

    source_fs = _resolve_with_at(store, from_ref, at_path)

    from .fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=name)
    store.branches[name] = new_fs
    _status(ctx, f"Created branch {name}")


@branch.command("delete")
@click.argument("name")
@click.pass_context
def branch_delete(ctx, name):
    """Delete branch NAME."""
    store = _open_store(ctx.obj["repo_path"])
    try:
        del store.branches[name]
    except KeyError:
        raise click.ClickException(f"Branch not found: {name}")
    _status(ctx, f"Deleted branch {name}")


# ---------------------------------------------------------------------------
# tag (group)
# ---------------------------------------------------------------------------

@main.group(invoke_without_command=True)
@click.pass_context
def tag(ctx):
    """Manage tags."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(tag_list)


@tag.command("list")
@click.pass_context
def tag_list(ctx):
    """List all tags."""
    store = _open_store(ctx.obj["repo_path"])
    for name in sorted(store.tags):
        click.echo(name)


@tag.command("create")
@click.argument("name")
@click.argument("from_ref", metavar="FROM")
@click.option("--at", "at_path", default=None,
              help="Point to latest commit that modified this path.")
@click.pass_context
def tag_create(ctx, name, from_ref, at_path):
    """Create a new tag NAME from FROM ref."""
    store = _open_store(ctx.obj["repo_path"])

    if name in store.tags:
        raise click.ClickException(f"Tag already exists: {name}")

    source_fs = _resolve_with_at(store, from_ref, at_path)

    from .fs import FS
    new_fs = FS(store, source_fs._commit_oid, branch=None)
    store.tags[name] = new_fs
    _status(ctx, f"Created tag {name}")


@tag.command("delete")
@click.argument("name")
@click.pass_context
def tag_delete(ctx, name):
    """Delete tag NAME."""
    store = _open_store(ctx.obj["repo_path"])
    try:
        del store.tags[name]
    except KeyError:
        raise click.ClickException(f"Tag not found: {name}")
    _status(ctx, f"Deleted tag {name}")


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------

@main.command("zip")
@click.argument("filename", type=click.Path())
@click.option("--branch", "-b", default="main", help="Branch to export from.")
@click.option("--at", "at_path", default=None, help="Filter to commits that changed this path.")
@click.option("--match", "match_pattern", default=None, help="Filter by message (supports * and ? wildcards).")
@click.pass_context
def zip_cmd(ctx, filename, branch, at_path, match_pattern):
    """Export repo contents to a zip file.

    FILENAME is the output zip path on disk.  Use '-' to write to stdout.
    """
    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

    if at_path is not None:
        at_path = _normalize_repo_path(at_path)
    if at_path is not None or match_pattern is not None:
        for entry in fs.log(at=at_path, match=match_pattern):
            fs = entry
            break
        else:
            raise click.ClickException("No matching commits found")

    to_stdout = filename == "-"
    dest = io.BytesIO() if to_stdout else filename
    repo = fs._store._repo
    root_tree = repo[fs._tree_oid]
    count = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in fs.walk():
            # Get the tree object for this directory
            tree = root_tree
            if dirpath:
                for seg in dirpath.split("/"):
                    tree = repo[tree[seg].id]
            for fname in files:
                repo_path = f"{dirpath}/{fname}" if dirpath else fname
                info = zipfile.ZipInfo(repo_path)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = tree[fname].filemode << 16
                zf.writestr(info, fs.read(repo_path))
                count += 1
    if to_stdout:
        click.get_binary_stream("stdout").write(dest.getvalue())
    _status(ctx, f"Wrote {count} file(s) to {filename}")


# ---------------------------------------------------------------------------
# unzip
# ---------------------------------------------------------------------------

@main.command("unzip")
@click.argument("filename", type=click.Path(exists=True))
@click.option("--branch", "-b", default="main", help="Branch to import into.")
@click.option("-m", "message", default=None, help="Commit message.")
@click.pass_context
def unzip_cmd(ctx, filename, branch, message):
    """Import a zip file into the repo.

    FILENAME is the path to the zip file on disk.
    """
    if not zipfile.is_zipfile(filename):
        raise click.ClickException(f"Not a valid zip file: {filename}")

    store = _open_store(ctx.obj["repo_path"])
    fs = _get_branch_fs(store, branch)

    writes: dict[str, bytes | tuple[bytes, int]] = {}
    with zipfile.ZipFile(filename, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            repo_path = _normalize_repo_path(info.filename)
            data = zf.read(info.filename)
            unix_mode = info.external_attr >> 16
            if unix_mode & 0o111:
                writes[repo_path] = (data, GIT_FILEMODE_BLOB_EXECUTABLE)
            else:
                writes[repo_path] = data

    if not writes:
        raise click.ClickException("Zip file contains no files")

    msg = message or ""
    try:
        fs._commit_changes(writes, set(), msg)
    except StaleSnapshotError:
        raise click.ClickException("Branch modified concurrently — retry")
    _status(ctx, f"Imported {len(writes)} file(s) from {filename}")

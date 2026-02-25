"""Archive commands: zip, unzip, tar, untar, archive_out, archive_in."""

from __future__ import annotations

import io
import os
import zipfile

import click

from ..copy._types import FileType
from ..exceptions import StaleSnapshotError
from ._helpers import (
    main,
    _repo_option,
    _branch_option,
    _message_option,
    _archive_format_option,
    _no_create_option,
    _require_repo,
    _status,
    _clean_archive_path,
    _open_store,
    _open_or_create_store,
    _current_branch,
    _get_branch_fs,
    _resolve_fs,
    _snapshot_options,
    _detect_archive_format,
    _tag_option,
    _apply_tag,
)


def _do_export(ctx, fs, filename: str, fmt: str):
    """Export *fs* contents to an archive file.

    *fmt* must be ``"zip"`` or ``"tar"``.  *filename* may be ``"-"`` for stdout.
    """
    if fmt == "zip":
        to_stdout = filename == "-"
        dest = io.BytesIO() if to_stdout else filename
        count = 0
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirs, files in fs.walk():
                for fe in files:
                    repo_path = f"{dirpath}/{fe.name}" if dirpath else fe.name
                    info = zipfile.ZipInfo(repo_path)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3  # Unix
                    if fe.file_type == FileType.LINK:
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
                        info.external_attr = fe.mode << 16
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
        count = 0
        with tarfile.open(fileobj=dest, mode=mode) if to_stdout else tarfile.open(dest, mode=mode) as tf:
            for dirpath, _dirs, files in fs.walk():
                for fe in files:
                    repo_path = f"{dirpath}/{fe.name}" if dirpath else fe.name
                    if fe.file_type == FileType.LINK:
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
                        info.mode = fe.mode & 0o7777
                        tf.addfile(info, io.BytesIO(data))
                    count += 1
        if to_stdout:
            click.get_binary_stream("stdout").write(dest.getvalue())
        _status(ctx, f"Wrote {count} file(s) to {filename}")


def _do_import(ctx, store, branch: str, filename: str, message: str | None, fmt: str):
    """Import an archive into a branch.

    *fmt* must be ``"zip"`` or ``"tar"``.  *filename* may be ``"-"`` for stdin.
    Returns the new FS after commit.
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
        try:
            with fs.batch(message=message, operation="ar") as b:
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
                            fm = FileType.EXECUTABLE.filemode if unix_mode & 0o111 else None
                            b.write(repo_path, data, mode=fm)
                        count += 1
                if count == 0:
                    raise click.ClickException("Zip file contains no files")
        except StaleSnapshotError:
            raise click.ClickException("Branch modified concurrently — retry")
        _status(ctx, f"Imported {count} file(s) from {filename}")
        return b.fs
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
            with fs.batch(message=message, operation="ar") as b:
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
                            fm = FileType.EXECUTABLE.filemode if target_mode & 0o111 else None
                            b.write(repo_path, data, mode=fm)
                            count += 1
                        elif member.isfile():
                            repo_path = _clean_archive_path(member.name)
                            member_info[repo_path] = member.mode
                            data = tf.extractfile(member).read()
                            fm = FileType.EXECUTABLE.filemode if member.mode & 0o111 else None
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
        return b.fs


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------

@main.command("zip")
@_repo_option
@click.argument("filename", type=click.Path())
@_branch_option
@_snapshot_options
@click.pass_context
def zip_cmd(ctx, filename, branch, ref, at_path, match_pattern, before, back):
    """Export repo contents to a zip file.

    FILENAME is the output zip path on disk.  Use '-' to write to stdout.
    """
    store = _open_store(_require_repo(ctx))
    branch = branch or _current_branch(store)
    fs = _resolve_fs(store, branch, ref, at_path=at_path,
                     match_pattern=match_pattern, before=before, back=back)
    _do_export(ctx, fs, filename, "zip")


# ---------------------------------------------------------------------------
# unzip
# ---------------------------------------------------------------------------

@main.command("unzip")
@_repo_option
@click.argument("filename", type=click.Path(exists=True))
@_branch_option
@_message_option
@_no_create_option
@_tag_option
@click.pass_context
def unzip_cmd(ctx, filename, branch, message, no_create, tag, force_tag):
    """Import a zip file into the repo.

    FILENAME is the path to the zip file on disk.
    """
    repo_path = _require_repo(ctx)
    if no_create:
        store = _open_store(repo_path)
    else:
        store = _open_or_create_store(repo_path, branch or "main")
    branch = branch or _current_branch(store)
    new_fs = _do_import(ctx, store, branch, filename, message, "zip")
    if tag:
        _apply_tag(store, new_fs, tag, force_tag)


# ---------------------------------------------------------------------------
# tar
# ---------------------------------------------------------------------------

@main.command("tar")
@_repo_option
@click.argument("filename", type=click.Path())
@_branch_option
@_snapshot_options
@click.pass_context
def tar_cmd(ctx, filename, branch, ref, at_path, match_pattern, before, back):
    """Export repo contents to a tar archive.

    FILENAME is the output tar path on disk.  Use '-' to write to stdout.
    Compression is auto-detected from the filename extension (.tar.gz, .tar.bz2, .tar.xz).
    """
    store = _open_store(_require_repo(ctx))
    branch = branch or _current_branch(store)
    fs = _resolve_fs(store, branch, ref, at_path=at_path,
                     match_pattern=match_pattern, before=before, back=back)
    _do_export(ctx, fs, filename, "tar")


# ---------------------------------------------------------------------------
# untar
# ---------------------------------------------------------------------------

@main.command("untar")
@_repo_option
@click.argument("filename", type=click.Path(), default="-")
@_branch_option
@_message_option
@_no_create_option
@_tag_option
@click.pass_context
def untar_cmd(ctx, filename, branch, message, no_create, tag, force_tag):
    """Import a tar archive into the repo.

    FILENAME is the path to the tar file on disk.  Use '-' to read from stdin
    (the default).  Compression is auto-detected.
    """
    repo_path = _require_repo(ctx)
    if no_create:
        store = _open_store(repo_path)
    else:
        store = _open_or_create_store(repo_path, branch or "main")
    branch = branch or _current_branch(store)
    new_fs = _do_import(ctx, store, branch, filename, message, "tar")
    if tag:
        _apply_tag(store, new_fs, tag, force_tag)


# ---------------------------------------------------------------------------
# archive / unarchive
# ---------------------------------------------------------------------------

@main.command("archive_out")
@_repo_option
@click.argument("filename", type=click.Path())
@_archive_format_option
@_branch_option
@_snapshot_options
@click.pass_context
def archive_cmd(ctx, filename, fmt, branch, ref, at_path, match_pattern, before, back):
    """Export repo contents to an archive file.

    Format is auto-detected from FILENAME extension (.zip, .tar, .tar.gz, etc.).
    Use --format to override.  Use '-' for stdout (requires --format).
    """
    if fmt is None:
        if filename == "-":
            raise click.ClickException("Use --format with stdout (-)")
        fmt = _detect_archive_format(filename)
    store = _open_store(_require_repo(ctx))
    branch = branch or _current_branch(store)
    fs = _resolve_fs(store, branch, ref, at_path=at_path,
                     match_pattern=match_pattern, before=before, back=back)
    _do_export(ctx, fs, filename, fmt)


@main.command("archive_in")
@_repo_option
@click.argument("filename", type=click.Path(), default=None, required=False)
@_archive_format_option
@_branch_option
@_message_option
@_no_create_option
@_tag_option
@click.pass_context
def unarchive_cmd(ctx, filename, fmt, branch, message, no_create, tag, force_tag):
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
    if no_create:
        store = _open_store(repo_path)
    else:
        store = _open_or_create_store(repo_path, branch or "main")
    branch = branch or _current_branch(store)
    new_fs = _do_import(ctx, store, branch, filename, message, fmt)
    if tag:
        _apply_tag(store, new_fs, tag, force_tag)

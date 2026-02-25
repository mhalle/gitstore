"""Mirror (backup/restore) operations for vost.

Ref-level mirroring: push all local refs to a remote (backup) or fetch
all remote refs to local (restore).  Extracted from repo.py and cli.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from dulwich.client import get_transport_and_path as _get_transport_and_path
from dulwich.errors import NotGitRepository
from dulwich.porcelain import ls_remote as _ls_remote
from dulwich.protocol import ZERO_SHA as _ZERO_SHA
from dulwich.repo import Repo as _DRepo

if TYPE_CHECKING:
    from .repo import GitStore


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RefChange:
    """A single ref change in a :class:`MirrorDiff`.

    Attributes:
        ref: Full ref name (e.g. ``"refs/heads/main"``).
        old_target: Previous 40-char hex SHA, or ``None`` for creates.
        new_target: New 40-char hex SHA, or ``None`` for deletes.
    """
    ref: str
    old_target: str | None = None
    new_target: str | None = None


@dataclass
class MirrorDiff:
    """Result of a :meth:`~vost.GitStore.backup` or :meth:`~vost.GitStore.restore` operation.

    Attributes:
        add: Refs to create.
        update: Refs to update.
        delete: Refs to delete.
    """
    add: list[RefChange] = field(default_factory=list)
    update: list[RefChange] = field(default_factory=list)
    delete: list[RefChange] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        """``True`` if there are no changes."""
        return not self.add and not self.update and not self.delete

    @property
    def total(self) -> int:
        """Total number of ref changes."""
        return len(self.add) + len(self.update) + len(self.delete)


# ---------------------------------------------------------------------------
# Transport helpers (operate on raw dulwich Repo)
# ---------------------------------------------------------------------------

def _diff_refs(drepo: _DRepo, url: str, direction: str) -> dict:
    """Compare local and remote refs.

    *direction* is ``"push"`` (local->remote) or ``"pull"`` (remote->local).
    Returns ``{"create": [...], "update": [...], "delete": [...],
    "src": {ref: sha}, "dest": {ref: sha}}`` with bytes keys.
    """
    # Auto-create remote for push if it's a local path that doesn't exist
    is_local = not any(url.startswith(proto) for proto in ["http://", "https://", "git://", "ssh://"])
    if is_local and not url.startswith("file://"):
        # Detect scp-style URLs: user@host:path or host:path
        # Exclude Windows drive letters (single letter before colon).
        if "@" in url and ":" in url.split("@", 1)[1]:
            raise ValueError(
                f"scp-style URL not supported: {url!r} — use ssh:// format instead"
            )
        colon_idx = url.find(":")
        # A colon after >1 chars with no path separator before it
        # looks like host:path.  Treat both / and \ as separators
        # to avoid rejecting Windows paths (e.g. \\?\C:\repo).
        prefix = url[:colon_idx]
        if colon_idx > 1 and "/" not in prefix and "\\" not in prefix:
            raise ValueError(
                f"scp-style URL not supported: {url!r} — use ssh:// format instead"
            )
    if is_local and direction == "push":
        local_path = url[7:] if url.startswith("file://") else url
        if not os.path.exists(local_path):
            _DRepo.init_bare(local_path, mkdir=True)

    try:
        remote_result = _ls_remote(url)
        refs_dict = remote_result.refs if hasattr(remote_result, "refs") else remote_result
        remote_refs = {
            ref: sha
            for ref, sha in refs_dict.items()
            if ref != b"HEAD" and not ref.endswith(b"^{}")
        }
    except NotGitRepository:
        # Remote doesn't exist - treat as empty for push, fail for pull
        if direction == "push":
            remote_refs = {}
        else:
            raise

    local_refs = {
        ref: sha
        for ref, sha in drepo.get_refs().items()
        if ref != b"HEAD"
    }

    if direction == "push":
        src, dest = local_refs, remote_refs
    else:
        src, dest = remote_refs, local_refs

    create, update, delete = [], [], []
    for ref, sha in src.items():
        if ref not in dest:
            create.append(ref)
        elif dest[ref] != sha:
            update.append(ref)
    for ref in dest:
        if ref not in src:
            delete.append(ref)

    return {"create": create, "update": update, "delete": delete,
            "src": src, "dest": dest}


def _mirror_push(drepo: _DRepo, url: str, *, progress=None):
    """Push all local refs to *url*, mirroring (force + delete stale)."""
    client, path = _get_transport_and_path(url)
    local_refs = {
        ref: sha
        for ref, sha in drepo.get_refs().items()
        if ref != b"HEAD"
    }

    def update_refs(remote_refs):
        new_refs = {}
        for ref, sha in local_refs.items():
            new_refs[ref] = sha
        for ref in remote_refs:
            if ref not in local_refs and ref != b"HEAD":
                new_refs[ref] = _ZERO_SHA
        return new_refs

    def gen_pack(have, want, *, ofs_delta=False, progress=progress):
        return drepo.object_store.generate_pack_data(
            have, want, ofs_delta=ofs_delta, progress=progress,
        )

    return client.send_pack(path, update_refs, gen_pack, progress=progress)


def _mirror_fetch(drepo: _DRepo, url: str, *, progress=None):
    """Fetch all remote refs from *url*, mirroring (force + delete stale)."""
    client, path = _get_transport_and_path(url)
    result = client.fetch(path, drepo, progress=progress)

    remote_refs = {
        ref: sha
        for ref, sha in result.refs.items()
        if ref != b"HEAD" and not ref.endswith(b"^{}")
    }

    # Set all remote refs locally
    for ref, sha in remote_refs.items():
        drepo.refs[ref] = sha

    # Delete local refs not on remote
    for ref in list(drepo.refs.allkeys()):
        if ref != b"HEAD" and ref not in remote_refs:
            drepo.refs.remove_if_equals(ref, drepo.refs[ref])

    return result


# ---------------------------------------------------------------------------
# Core mirror functions
# ---------------------------------------------------------------------------

def _raw_diff_to_sync_diff(raw: dict) -> MirrorDiff:
    """Convert bytes-keyed diff dict to MirrorDiff."""
    src, dest = raw["src"], raw["dest"]

    def _sha(b):
        return b.decode() if isinstance(b, bytes) else str(b)

    add = [
        RefChange(ref=ref.decode(), new_target=_sha(src[ref]))
        for ref in raw["create"]
    ]
    update = [
        RefChange(ref=ref.decode(), old_target=_sha(dest[ref]), new_target=_sha(src[ref]))
        for ref in raw["update"]
    ]
    delete = [
        RefChange(ref=ref.decode(), old_target=_sha(dest[ref]))
        for ref in raw["delete"]
    ]
    return MirrorDiff(add=add, update=update, delete=delete)


def backup(store: GitStore, url: str, *, dry_run: bool = False, progress=None) -> MirrorDiff:
    """Push all refs to *url*, creating an exact mirror.

    Returns a `MirrorDiff` describing what changed (or would change).
    """
    drepo = store._repo._drepo
    raw = _diff_refs(drepo, url, "push")
    diff = _raw_diff_to_sync_diff(raw)
    if not dry_run:
        _mirror_push(drepo, url, progress=progress)
    return diff


def restore(store: GitStore, url: str, *, dry_run: bool = False, progress=None) -> MirrorDiff:
    """Fetch all refs from *url*, overwriting local state.

    Returns a `MirrorDiff` describing what changed (or would change).
    """
    drepo = store._repo._drepo
    raw = _diff_refs(drepo, url, "pull")
    diff = _raw_diff_to_sync_diff(raw)
    if not dry_run:
        _mirror_fetch(drepo, url, progress=progress)
    return diff


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def resolve_credentials(url: str) -> str:
    """Inject credentials into an HTTPS URL if available.

    Tries ``git credential fill`` first (works with any configured helper:
    osxkeychain, wincred, libsecret, ``gh auth setup-git``, etc.).  Falls
    back to ``gh auth token`` for GitHub hosts.  Non-HTTPS URLs and URLs
    that already contain credentials are returned unchanged.
    """
    if not url.startswith("https://"):
        return url

    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.username:
        return url  # already has credentials

    import subprocess

    # Try git credential fill
    try:
        stdin = f"protocol={parsed.scheme}\nhost={parsed.hostname}\n\n"
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input=stdin, capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            creds = {}
            for line in proc.stdout.strip().splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    creds[k] = v
            username = creds.get("username")
            password = creds.get("password")
            if username and password:
                from urllib.parse import quote

                netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                return urlunparse(parsed._replace(netloc=netloc))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: gh auth token (GitHub-specific)
    try:
        proc = subprocess.run(
            ["gh", "auth", "token", "--hostname", parsed.hostname],
            capture_output=True, text=True, timeout=5,
        )
        token = proc.stdout.strip()
        if proc.returncode == 0 and token:
            netloc = f"x-access-token:{token}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return url

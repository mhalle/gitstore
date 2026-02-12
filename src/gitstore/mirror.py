"""Mirror (backup/restore) operations for gitstore.

Ref-level mirroring: push all local refs to a remote (backup) or fetch
all remote refs to local (restore).  Extracted from repo.py and cli.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .repo import GitStore


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RefChange:
    ref: str
    src_sha: str | None = None   # None for deletes
    dest_sha: str | None = None  # None for creates


@dataclass
class MirrorDiff:
    create: list[RefChange] = field(default_factory=list)
    update: list[RefChange] = field(default_factory=list)
    delete: list[RefChange] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.create and not self.update and not self.delete

    @property
    def total(self) -> int:
        return len(self.create) + len(self.update) + len(self.delete)


# ---------------------------------------------------------------------------
# Core mirror functions
# ---------------------------------------------------------------------------

def _raw_diff_to_sync_diff(raw: dict) -> MirrorDiff:
    """Convert bytes-keyed diff dict from _compat to MirrorDiff."""
    src, dest = raw["src"], raw["dest"]

    def _sha(b):
        return b.decode() if isinstance(b, bytes) else str(b)

    create = [
        RefChange(ref=ref.decode(), src_sha=_sha(src[ref]))
        for ref in raw["create"]
    ]
    update = [
        RefChange(ref=ref.decode(), src_sha=_sha(src[ref]), dest_sha=_sha(dest[ref]))
        for ref in raw["update"]
    ]
    delete = [
        RefChange(ref=ref.decode(), dest_sha=_sha(dest[ref]))
        for ref in raw["delete"]
    ]
    return MirrorDiff(create=create, update=update, delete=delete)


def backup(store: GitStore, url: str, *, dry_run: bool = False, progress=None) -> MirrorDiff:
    """Push all refs to *url*, creating an exact mirror.

    Returns a `MirrorDiff` describing what changed (or would change).
    """
    raw = store._repo.diff_refs(url, "push")
    diff = _raw_diff_to_sync_diff(raw)
    if not dry_run:
        store._repo.mirror_push(url, progress=progress)
    return diff


def restore(store: GitStore, url: str, *, dry_run: bool = False, progress=None) -> MirrorDiff:
    """Fetch all refs from *url*, overwriting local state.

    Returns a `MirrorDiff` describing what changed (or would change).
    """
    raw = store._repo.diff_refs(url, "pull")
    diff = _raw_diff_to_sync_diff(raw)
    if not dry_run:
        store._repo.mirror_fetch(url, progress=progress)
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

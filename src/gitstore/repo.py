"""GitStore: repository and ref management."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import _compat as pygit2
from .mirror import RefChange, MirrorDiff

if TYPE_CHECKING:
    from .fs import FS


@dataclass
class ReflogEntry:
    """A single reflog entry."""
    old_sha: str
    new_sha: str
    committer: str
    timestamp: float
    message: str


def _validate_ref_name(name: str) -> None:
    """Reject ref names containing ':', space, tab, or newline."""
    for ch, label in ((":", "colon"), (" ", "space"), ("\t", "tab"), ("\n", "newline")):
        if ch in name:
            raise ValueError(f"Invalid ref name {name!r}: contains {label}")


class GitStore:
    """A versioned filesystem backed by a bare git repository."""

    def __init__(self, pygit2_repo: pygit2.Repository, author: str, email: str):
        self._repo = pygit2_repo
        self._signature = pygit2.Signature(author, email)
        self.branches = RefDict(self, "refs/heads/")
        self.tags = RefDict(self, "refs/tags/")

    def __repr__(self) -> str:
        return f"GitStore({self._repo.path!r})"

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        create: bool = True,
        branch: str | None = "main",
        author: str = "gitstore",
        email: str = "gitstore@localhost",
    ) -> GitStore:
        """Open or create a bare git repository.

        Args:
            path: Path to the bare repository.
            create: If True (default), create the repo when it doesn't exist.
                    If False, raise FileNotFoundError when missing.
            branch: Initial branch name when creating (default "main").
                    None to create a bare repo with no branches.
            author: Default author name for commits.
            email: Default author email for commits.
        """
        path = Path(path)

        if path.exists():
            repo = pygit2.Repository(str(path))
            return cls(repo, author, email)

        if not create:
            raise FileNotFoundError(f"Repository not found: {path}")

        repo = pygit2.init_repository(str(path), bare=True)
        store = cls(repo, author, email)

        if branch is not None:
            sig = store._signature
            tree_oid = repo.TreeBuilder().write()
            repo.create_commit(
                f"refs/heads/{branch}",
                sig,
                sig,
                f"Initialize {branch}",
                tree_oid,
                [],
            )
            repo.set_head_branch(branch)

        return store

    def backup(self, url: str, *, dry_run: bool = False, progress: Callable | None = None) -> MirrorDiff:
        """Push all refs to *url*, creating an exact mirror.

        Returns a `MirrorDiff` describing what changed (or would change).
        """
        from .mirror import backup
        return backup(self, url, dry_run=dry_run, progress=progress)

    def restore(self, url: str, *, dry_run: bool = False, progress: Callable | None = None) -> MirrorDiff:
        """Fetch all refs from *url*, overwriting local state.

        Returns a `MirrorDiff` describing what changed (or would change).
        """
        from .mirror import restore
        return restore(self, url, dry_run=dry_run, progress=progress)


class RefDict(MutableMapping):
    """Dict-like access to branches or tags."""

    def __init__(self, store: GitStore, prefix: str):
        self._store = store
        self._prefix = prefix  # "refs/heads/" or "refs/tags/"

    @property
    def _is_tags(self) -> bool:
        return self._prefix == "refs/tags/"

    def __repr__(self) -> str:
        kind = "tags" if self._is_tags else "branches"
        return f"RefDict({kind!r}, len={len(self)})"

    def _ref_name(self, name: str) -> str:
        return f"{self._prefix}{name}"

    def __getitem__(self, name: str) -> FS:
        from .fs import FS

        repo = self._store._repo
        ref_name = self._ref_name(name)
        try:
            ref = repo.references[ref_name]
        except KeyError:
            raise KeyError(name)
        oid = ref.resolve().target
        if self._is_tags:
            obj = repo[oid]
            try:
                commit = obj.peel(pygit2.Commit)
            except Exception:
                raise ValueError(f"Tag {name!r} does not point to a commit")
            return FS(self._store, commit.id, branch=None)
        else:
            return FS(self._store, oid, branch=name)

    def __setitem__(self, name: str, fs: FS):
        from ._lock import repo_lock
        from .fs import FS

        _validate_ref_name(name)
        if not isinstance(fs, FS):
            raise TypeError(f"Expected FS, got {type(fs).__name__}")
        try:
            same = os.path.samefile(fs._store._repo.path, self._store._repo.path)
        except OSError:
            same = False
        if not same:
            raise ValueError("FS belongs to a different repository")

        repo = self._store._repo
        ref_name = self._ref_name(name)

        committer = self._store._signature._identity
        with repo_lock(repo.path):
            if ref_name in repo.references:
                if self._is_tags:
                    raise KeyError(f"Tag {name!r} already exists")
                # Get commit message for reflog
                commit = repo[fs._commit_oid]
                msg_str = commit.message.splitlines()[0] if commit.message else ""
                msg = f"branch: set to {msg_str}".encode()
                repo.references[ref_name].set_target(fs._commit_oid, message=msg, committer=committer)
            else:
                commit = repo[fs._commit_oid]
                msg_str = commit.message.splitlines()[0] if commit.message else ""
                msg = f"branch: Created from {msg_str}".encode()
                repo.references.create(ref_name, fs._commit_oid, message=msg, committer=committer)

    def __delitem__(self, name: str):
        from ._lock import repo_lock

        repo = self._store._repo
        ref_name = self._ref_name(name)

        with repo_lock(repo.path):
            try:
                repo.references[ref_name]
            except KeyError:
                raise KeyError(name)
            repo.references.delete(ref_name)

    def __contains__(self, name: str) -> bool:
        ref_name = self._ref_name(name)
        return ref_name in self._store._repo.references

    def __iter__(self) -> Iterator[str]:
        prefix_len = len(self._prefix)
        for ref_name in self._store._repo.references:
            if ref_name.startswith(self._prefix):
                yield ref_name[prefix_len:]

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def set(self, name: str, fs: FS) -> FS:
        """Set branch to FS snapshot and return writable FS bound to it.

        This is a convenience method that combines setting and getting:

            fs_new = repo.branches.set('feature', fs)

        Is equivalent to:

            repo.branches['feature'] = fs
            fs_new = repo.branches['feature']

        Args:
            name: Branch name
            fs: FS snapshot to set (can be read-only)

        Returns:
            New writable FS bound to the branch

        Example:
            >>> fs_wow = repo.branches.set('wow', fs_main)
            >>> fs_wow.branch  # 'wow' (not 'main')
        """
        self[name] = fs
        return self[name]

    def reflog(self, name: str) -> list[ReflogEntry]:
        """Read reflog entries for a branch.

        Args:
            name: Branch name (e.g., "main")

        Returns:
            List of :class:`ReflogEntry` objects.

        Raises:
            KeyError: If branch doesn't exist
            FileNotFoundError: If no reflog exists

        Example:
            >>> entries = repo.branches.reflog("main")
            >>> for e in entries:
            ...     print(f"{e.message}: {e.new_sha[:7]}")
        """
        from dulwich import reflog as dreflog

        if self._is_tags:
            raise ValueError("Tags do not have reflog")

        # Verify branch exists
        ref_name = self._ref_name(name)
        if ref_name not in self._store._repo.references:
            raise KeyError(name)

        # Read reflog file
        reflog_path = os.path.join(
            self._store._repo.path,
            "logs", "refs", "heads", name
        )

        if not os.path.exists(reflog_path):
            raise FileNotFoundError(f"No reflog found for branch {name!r}")

        # Parse reflog entries
        with open(reflog_path, 'rb') as f:
            entries = []
            for entry in dreflog.read_reflog(f):
                entries.append(ReflogEntry(
                    old_sha=entry.old_sha.decode(),
                    new_sha=entry.new_sha.decode(),
                    committer=entry.committer.decode(),
                    timestamp=entry.timestamp,
                    message=entry.message.decode(),
                ))
            return entries

"""GitStore: repository and ref management."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pygit2


class GitStore:
    """A versioned filesystem backed by a bare git repository."""

    def __init__(self, pygit2_repo: pygit2.Repository, author: str, email: str):
        self._repo = pygit2_repo
        self._signature = pygit2.Signature(author, email)
        self.branches = RefDict(self, "refs/heads/")
        self.tags = RefDict(self, "refs/tags/")

    @classmethod
    def open(
        cls,
        path: str | Path,
        create: str | bool | None = None,
        author: str = "gitstore",
        email: str = "gitstore@localhost",
    ) -> GitStore:
        """Open or create a bare git repository.

        Args:
            path: Path to the bare repository.
            create: None to open existing (fail if missing),
                    True to create bare repo with no branch,
                    str to create bare repo + bootstrap branch with that name.
            author: Default author name for commits.
            email: Default author email for commits.
        """
        path = Path(path)

        if create is not None:
            if path.exists():
                raise FileExistsError(f"Repository already exists: {path}")
            repo = pygit2.init_repository(str(path), bare=True)
            store = cls(repo, author, email)

            if isinstance(create, str):
                sig = store._signature
                tree_oid = repo.TreeBuilder().write()
                repo.create_commit(
                    f"refs/heads/{create}",
                    sig,
                    sig,
                    f"Initialize {create}",
                    tree_oid,
                    [],
                )

            return store
        else:
            if not path.exists():
                raise FileNotFoundError(f"Repository not found: {path}")
            repo = pygit2.Repository(str(path))
            return cls(repo, author, email)


class RefDict:
    """Dict-like access to branches or tags."""

    def __init__(self, store: GitStore, prefix: str):
        self._store = store
        self._prefix = prefix  # "refs/heads/" or "refs/tags/"

    @property
    def _is_tags(self) -> bool:
        return self._prefix == "refs/tags/"

    def _ref_name(self, name: str) -> str:
        return f"{self._prefix}{name}"

    def __getitem__(self, name: str):
        from .fs import FS

        repo = self._store._repo
        ref_name = self._ref_name(name)
        try:
            ref = repo.references[ref_name]
        except KeyError:
            raise KeyError(name)
        commit_oid = ref.resolve().target
        if self._is_tags:
            return FS(self._store, commit_oid, branch=None)
        else:
            return FS(self._store, commit_oid, branch=name)

    def __setitem__(self, name: str, fs):
        from .fs import FS

        if not isinstance(fs, FS):
            raise TypeError(f"Expected FS, got {type(fs).__name__}")

        repo = self._store._repo
        ref_name = self._ref_name(name)

        if ref_name in repo.references:
            repo.references[ref_name].set_target(fs._commit_oid)
        else:
            repo.references.create(ref_name, fs._commit_oid)

    def __delitem__(self, name: str):
        repo = self._store._repo
        ref_name = self._ref_name(name)
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

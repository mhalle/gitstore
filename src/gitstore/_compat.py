"""pygit2-compatible wrappers around dulwich.

This module exposes the same interface as pygit2 so that the rest of
gitstore can switch backends by changing a single import line.
"""

from __future__ import annotations

import time as _time

from dulwich.client import get_transport_and_path as _get_transport_and_path
from dulwich.objects import Blob as _DBlob
from dulwich.objects import Commit as _DCommit
from dulwich.objects import Tag as _DTag
from dulwich.objects import Tree as _DTree
from dulwich.porcelain import ls_remote as _ls_remote
from dulwich.protocol import ZERO_SHA as _ZERO_SHA
from dulwich.reflog import format_reflog_line as _format_reflog_line
from dulwich.repo import Repo as _DRepo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GIT_OBJECT_TREE = 2      # dulwich Tree.type_num
GIT_OBJECT_COMMIT = 1    # dulwich Commit.type_num

# ---------------------------------------------------------------------------
# Oid
# ---------------------------------------------------------------------------

class Oid:
    """pygit2.Oid-compatible wrapper around dulwich hex SHA bytes."""

    __slots__ = ("_sha",)

    def __init__(self, sha: bytes):
        # dulwich SHAs are 40-char hex bytes (e.g. b"abc123...")
        self._sha = sha

    def __str__(self) -> str:
        return self._sha.decode()

    def __repr__(self) -> str:
        return f"Oid({self._sha.decode()[:7]})"

    def __eq__(self, other):
        if isinstance(other, Oid):
            return self._sha == other._sha
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._sha)

    @property
    def raw(self) -> bytes:
        """The raw 40-char hex bytes (dulwich native format)."""
        return self._sha

# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------

class Signature:
    """pygit2.Signature-compatible identity."""

    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email
        self._identity = f"{name} <{email}>".encode()

# ---------------------------------------------------------------------------
# GitError
# ---------------------------------------------------------------------------

class GitError(Exception):
    """Drop-in for pygit2.GitError."""

# ---------------------------------------------------------------------------
# Commit (for isinstance checks — e.g. pygit2.Commit in _resolve_ref)
# ---------------------------------------------------------------------------

Commit = type("Commit", (), {})  # sentinel; never instantiated

# ---------------------------------------------------------------------------
# Wrapped objects
# ---------------------------------------------------------------------------

class _TreeEntry:
    """Mimics pygit2 tree entry: .name, .id, .filemode."""

    __slots__ = ("name", "id", "filemode")

    def __init__(self, name: str, oid: Oid, filemode: int):
        self.name = name
        self.id = oid
        self.filemode = filemode


class _WrappedObject:
    """Base wrapper for dulwich objects."""

    def __init__(self, dulwich_obj, repo: Repository):
        self._obj = dulwich_obj
        self._repo = repo

    @property
    def id(self) -> Oid:
        return Oid(self._obj.id)

    @property
    def type(self) -> int:
        return self._obj.type_num

    def peel(self, target_type=None):
        """Follow tags until we reach the target type."""
        obj = self
        for _ in range(50):  # safety limit
            if target_type is Commit and obj.type == GIT_OBJECT_COMMIT:
                return obj
            if not isinstance(obj._obj, _DTag):
                break
            # Follow the tag to its target
            target_sha = obj._obj.object[1]
            obj = self._repo[Oid(target_sha)]
        if target_type is Commit and obj.type != GIT_OBJECT_COMMIT:
            raise ValueError(f"Cannot peel to commit: got type {obj.type}")
        return obj


class _WrappedBlob(_WrappedObject):
    @property
    def data(self) -> bytes:
        return self._obj.data


class _WrappedTree(_WrappedObject):
    def __getitem__(self, name: str) -> _TreeEntry:
        name_bytes = name.encode() if isinstance(name, str) else name
        mode, sha = self._obj[name_bytes]
        return _TreeEntry(name if isinstance(name, str) else name.decode(), Oid(sha), mode)

    def __iter__(self):
        for entry in self._obj.iteritems():
            yield _TreeEntry(entry.path.decode(), Oid(entry.sha), entry.mode)

    def __len__(self) -> int:
        return len(self._obj)


class _WrappedCommit(_WrappedObject):
    @property
    def tree_id(self) -> Oid:
        return Oid(self._obj.tree)

    @property
    def message(self) -> str:
        return self._obj.message.decode()

    @property
    def commit_time(self) -> int:
        return self._obj.commit_time

    @property
    def commit_time_offset(self) -> int:
        # pygit2 offset is in minutes, dulwich is in seconds
        return self._obj.commit_timezone // 60

    @property
    def author(self) -> Signature:
        ident = self._obj.author.decode()
        name, _, email_part = ident.partition(" <")
        return Signature(name, email_part.rstrip(">"))

    @property
    def parents(self) -> list[_WrappedCommit]:
        return [self._repo[Oid(p)] for p in self._obj.parents]


# ---------------------------------------------------------------------------
# _wrap helper
# ---------------------------------------------------------------------------

def _wrap(dulwich_obj, repo: Repository) -> _WrappedObject:
    if isinstance(dulwich_obj, _DBlob):
        return _WrappedBlob(dulwich_obj, repo)
    elif isinstance(dulwich_obj, _DTree):
        return _WrappedTree(dulwich_obj, repo)
    elif isinstance(dulwich_obj, _DCommit):
        return _WrappedCommit(dulwich_obj, repo)
    elif isinstance(dulwich_obj, _DTag):
        return _WrappedObject(dulwich_obj, repo)
    return _WrappedObject(dulwich_obj, repo)


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

def _write_reflog_entry(repo_path: str, ref_name: bytes, old_sha: bytes, new_sha: bytes, committer: bytes, message: bytes):
    """Write a reflog entry for a ref update."""
    import os

    # Convert ref name to path: refs/heads/main -> logs/refs/heads/main
    ref_str = ref_name.decode() if isinstance(ref_name, bytes) else ref_name
    reflog_path = os.path.join(repo_path, "logs", ref_str)

    # Create parent directories
    os.makedirs(os.path.dirname(reflog_path), exist_ok=True)

    # Format and write entry
    timestamp = int(_time.time())
    line = _format_reflog_line(old_sha, new_sha, committer, timestamp, 0, message)

    with open(reflog_path, 'ab') as f:
        f.write(line + b'\n')


class _Reference:
    """Mimics a pygit2 reference."""

    def __init__(self, refs_container, ref_name: bytes, repo):
        self._refs = refs_container
        self._name = ref_name
        self._repo = repo

    def resolve(self) -> _Reference:
        # dulwich refs[] already follows symrefs
        return self

    @property
    def target(self) -> Oid:
        return Oid(self._refs[self._name])

    def set_target(self, oid: Oid, message: bytes | None = None):
        # Get old value for reflog
        try:
            old_sha = self._refs[self._name]
        except KeyError:
            old_sha = _ZERO_SHA

        # Update ref
        self._refs[self._name] = oid.raw

        # Write reflog entry
        if message is None:
            message = b"update ref"
        committer = b"gitstore <gitstore@localhost>"
        _write_reflog_entry(
            self._repo.path, self._name,
            old_sha, oid.raw,
            committer, message
        )


class _References:
    """Wraps dulwich refs to match repo.references API."""

    def __init__(self, dulwich_repo: _DRepo):
        self._dulwich_repo = dulwich_repo
        self._refs = dulwich_repo.refs

    def __getitem__(self, name: str) -> _Reference:
        ref_bytes = name.encode() if isinstance(name, str) else name
        if ref_bytes not in self._refs:
            raise KeyError(name)
        return _Reference(self._refs, ref_bytes, self._dulwich_repo)

    def __contains__(self, name: str) -> bool:
        ref_bytes = name.encode() if isinstance(name, str) else name
        return ref_bytes in self._refs

    def __iter__(self):
        for ref_bytes in self._refs.allkeys():
            yield ref_bytes.decode()

    def create(self, name: str, oid: Oid, message: bytes | None = None):
        ref_bytes = name.encode() if isinstance(name, str) else name

        # Update ref
        self._refs[ref_bytes] = oid.raw

        # Write reflog entry
        if message is None:
            message = b"create ref"
        committer = b"gitstore <gitstore@localhost>"
        _write_reflog_entry(
            self._dulwich_repo.path, ref_bytes,
            _ZERO_SHA, oid.raw,
            committer, message
        )

    def delete(self, name: str):
        ref_bytes = name.encode() if isinstance(name, str) else name
        del self._refs[ref_bytes]


# ---------------------------------------------------------------------------
# TreeBuilder
# ---------------------------------------------------------------------------

class TreeBuilder:
    """Wraps dulwich Tree construction to match pygit2's TreeBuilder."""

    def __init__(self, repo: _DRepo, base_tree=None):
        self._repo = repo
        self._entries: dict[bytes, tuple[int, bytes]] = {}
        if base_tree is not None:
            obj = base_tree._obj if isinstance(base_tree, _WrappedTree) else base_tree
            for entry in obj.iteritems():
                self._entries[entry.path] = (entry.mode, entry.sha)

    def insert(self, name: str, oid: Oid, mode: int):
        self._entries[name.encode()] = (mode, oid.raw)

    def remove(self, name: str):
        key = name.encode()
        if key not in self._entries:
            raise GitError(f"Entry not found: {name}")
        del self._entries[key]

    def write(self) -> Oid:
        tree = _DTree()
        for name_bytes, (mode, sha) in sorted(self._entries.items()):
            tree.add(name_bytes, mode, sha)
        self._repo.object_store.add_object(tree)
        return Oid(tree.id)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class Repository:
    """pygit2.Repository-compatible wrapper around dulwich Repo."""

    def __init__(self, path_or_repo):
        if isinstance(path_or_repo, str):
            self._repo = _DRepo(path_or_repo)
        elif isinstance(path_or_repo, _DRepo):
            self._repo = path_or_repo
        else:
            self._repo = path_or_repo

    @property
    def path(self) -> str:
        p = self._repo.path
        # pygit2 includes trailing slash for bare repos
        if not p.endswith("/"):
            p += "/"
        return p

    def __getitem__(self, oid: Oid) -> _WrappedObject:
        obj = self._repo.object_store[oid.raw]
        return _wrap(obj, self)

    def get(self, ref_str: str):
        """Lookup by full or short hex hash (like pygit2.Repository.get)."""
        ref_bytes = ref_str.encode() if isinstance(ref_str, str) else ref_str
        # Try full SHA first
        if len(ref_bytes) == 40:
            try:
                obj = self._repo.object_store[ref_bytes]
                return _wrap(obj, self)
            except KeyError:
                return None
        # Short hash: prefix scan
        for sha in self._repo.object_store:
            if sha.startswith(ref_bytes):
                obj = self._repo.object_store[sha]
                return _wrap(obj, self)
        return None

    def create_blob(self, data: bytes) -> Oid:
        blob = _DBlob.from_string(data)
        self._repo.object_store.add_object(blob)
        return Oid(blob.id)

    def create_blob_fromdisk(self, path: str) -> Oid:
        """Create a blob from a file on disk.

        Note: reads the entire file into memory because dulwich requires
        the full data to compute the SHA-1 hash and store the object.
        """
        with open(path, "rb") as f:
            data = f.read()
        return self.create_blob(data)

    def create_commit(
        self,
        ref_name,
        author: Signature,
        committer: Signature,
        message: str,
        tree_oid: Oid,
        parent_oids: list[Oid],
    ) -> Oid:
        c = _DCommit()
        c.tree = tree_oid.raw
        c.parents = [p.raw for p in parent_oids]
        c.author = author._identity
        c.committer = committer._identity
        now = int(_time.time())
        c.author_time = c.commit_time = now
        c.author_timezone = c.commit_timezone = 0
        msg = message.encode() if isinstance(message, str) else message
        if not msg.endswith(b"\n"):
            msg += b"\n"
        c.message = msg
        c.encoding = b"UTF-8"
        self._repo.object_store.add_object(c)

        if ref_name is not None:
            ref_bytes = ref_name.encode() if isinstance(ref_name, str) else ref_name
            self._repo.refs[ref_bytes] = c.id

        return Oid(c.id)

    def create_tag(
        self,
        name: str,
        target_oid: Oid,
        target_type: int,
        tagger: Signature,
        message: str,
    ) -> Oid:
        """Create an annotated tag (matches pygit2.Repository.create_tag)."""
        # dulwich Tag.object expects (class, sha), not (int, sha)
        _type_map = {1: _DCommit, 2: _DTree, 3: _DBlob, 4: _DTag}
        type_class = _type_map.get(target_type, _DCommit)
        tag = _DTag()
        tag.name = name.encode()
        tag.object = (type_class, target_oid.raw)
        tag.tagger = tagger._identity
        tag.tag_time = int(_time.time())
        tag.tag_timezone = 0
        msg = message.encode() if isinstance(message, str) else message
        if not msg.endswith(b"\n"):
            msg += b"\n"
        tag.message = msg
        self._repo.object_store.add_object(tag)
        # Create the ref
        ref_bytes = f"refs/tags/{name}".encode()
        self._repo.refs[ref_bytes] = tag.id
        return Oid(tag.id)

    @property
    def default_signature(self) -> Signature:
        return Signature("gitstore", "gitstore@localhost")

    def TreeBuilder(self, tree=None) -> TreeBuilder:
        return TreeBuilder(self._repo, tree)

    @property
    def references(self) -> _References:
        return _References(self._repo)

    @property
    def object_store(self):
        """Direct access to dulwich object_store (for tests)."""
        return self._repo.object_store

    # -- transport helpers --------------------------------------------------

    def diff_refs(self, url, direction):
        """Compare local and remote refs.

        *direction* is ``"push"`` (local->remote) or ``"pull"`` (remote->local).
        Returns ``{"create": [...], "update": [...], "delete": [...],
        "src": {ref: sha}, "dest": {ref: sha}}`` with bytes keys.
        """
        import os
        from dulwich.errors import NotGitRepository

        # Auto-create remote for push if it's a local path that doesn't exist
        is_local = not any(url.startswith(proto) for proto in ["http://", "https://", "git://", "ssh://"])
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
            for ref, sha in self._repo.get_refs().items()
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

    def mirror_push(self, url, *, progress=None):
        """Push all local refs to *url*, mirroring (force + delete stale)."""
        client, path = _get_transport_and_path(url)
        local_refs = {
            ref: sha
            for ref, sha in self._repo.get_refs().items()
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
            return self._repo.object_store.generate_pack_data(
                have, want, ofs_delta=ofs_delta, progress=progress,
            )

        return client.send_pack(path, update_refs, gen_pack, progress=progress)

    def mirror_fetch(self, url, *, progress=None):
        """Fetch all remote refs from *url*, mirroring (force + delete stale)."""
        client, path = _get_transport_and_path(url)
        result = client.fetch(path, self._repo, progress=progress)

        remote_refs = {
            ref: sha
            for ref, sha in result.refs.items()
            if ref != b"HEAD" and not ref.endswith(b"^{}")
        }

        # Set all remote refs locally
        for ref, sha in remote_refs.items():
            self._repo.refs[ref] = sha

        # Delete local refs not on remote
        for ref in list(self._repo.refs.allkeys()):
            if ref != b"HEAD" and ref not in remote_refs:
                self._repo.refs.remove_if_equals(ref, self._repo.refs[ref])

        return result


# ---------------------------------------------------------------------------
# init_repository
# ---------------------------------------------------------------------------

def init_repository(path: str, bare: bool = True) -> Repository:
    """Create a new git repository (matches pygit2.init_repository)."""
    repo = _DRepo.init_bare(path, mkdir=True)
    return Repository(repo)

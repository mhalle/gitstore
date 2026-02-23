"""Git notes support: per-namespace mapping of commit hashes to note text."""

from __future__ import annotations

import re
from collections.abc import Iterator, MutableMapping
from typing import TYPE_CHECKING

from ._lock import repo_lock
from .tree import GIT_FILEMODE_BLOB, GIT_FILEMODE_TREE, TreeBuilder

if TYPE_CHECKING:
    from .repo import GitStore

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")


def _validate_hash(h: str) -> None:
    if not isinstance(h, str):
        raise TypeError(f"Expected str, got {type(h).__name__}")
    if not _HEX40_RE.match(h):
        raise ValueError(f"Invalid commit hash: {h!r} (must be 40-char lowercase hex)")


class NoteNamespace(MutableMapping):
    """One git notes namespace, backed by ``refs/notes/<name>``.

    Maps 40-char hex commit hashes to UTF-8 note text.
    """

    def __init__(self, store: GitStore, namespace: str):
        self._store = store
        self._namespace = namespace
        self._ref = f"refs/notes/{namespace}"

    def __repr__(self) -> str:
        return f"NoteNamespace({self._namespace!r}, len={len(self)})"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tip_oid(self) -> bytes | None:
        """Return the OID of the notes ref commit, or None."""
        try:
            ref = self._store._repo.references[self._ref]
            return ref.resolve().target
        except KeyError:
            return None

    def _tree_oid(self) -> bytes | None:
        """Return the tree OID from the tip commit, or None."""
        tip = self._tip_oid()
        if tip is None:
            return None
        commit = self._store._repo[tip]
        return commit.tree

    def _find_note_in_tree(self, tree_oid: bytes, h: str) -> bytes | None:
        """Find the blob OID for *h* in the tree, handling flat and fanout."""
        repo = self._store._repo
        tree = repo[tree_oid]

        # Try flat: entry named by full 40-char hash
        h_bytes = h.encode()
        try:
            mode, sha = tree[h_bytes]
            if mode != GIT_FILEMODE_TREE:
                return sha
        except KeyError:
            pass

        # Try 2/38 fanout: h[:2] is a subtree, h[2:] is blob name
        prefix = h[:2].encode()
        suffix = h[2:].encode()
        try:
            mode, sha = tree[prefix]
            if mode == GIT_FILEMODE_TREE:
                subtree = repo[sha]
                try:
                    _m, blob_sha = subtree[suffix]
                    return blob_sha
                except KeyError:
                    pass
        except KeyError:
            pass

        return None

    def _iter_notes(self, tree_oid: bytes) -> Iterator[tuple[str, bytes]]:
        """Yield ``(hash_hex, blob_oid)`` for all notes in the tree."""
        repo = self._store._repo
        tree = repo[tree_oid]
        for entry in tree.iteritems():
            name = entry.path.decode()
            if entry.mode == GIT_FILEMODE_TREE and len(name) == 2:
                # Fanout subtree
                subtree = repo[entry.sha]
                for sub_entry in subtree.iteritems():
                    sub_name = sub_entry.path.decode()
                    full_hash = name + sub_name
                    if _HEX40_RE.match(full_hash):
                        yield (full_hash, sub_entry.sha)
            elif _HEX40_RE.match(name):
                yield (name, entry.sha)

    def _commit_note_tree(self, new_tree_oid: bytes, message: str) -> None:
        """Commit *new_tree_oid* to the notes ref under repo_lock."""
        repo = self._store._repo
        sig = self._store._signature
        ref_bytes = self._ref.encode()

        with repo_lock(repo.path):
            # Re-read tip inside lock
            try:
                ref = repo.references[self._ref]
                parent_oid = ref.resolve().target
                parents = [parent_oid]
            except KeyError:
                parents = []

            commit_oid = repo.create_commit(
                None,  # don't set ref yet — we do CAS below
                sig,
                sig,
                message,
                new_tree_oid,
                parents,
            )

            # Atomic ref update
            refs = repo._drepo.refs
            old = parents[0] if parents else None
            refs.set_if_equals(
                ref_bytes, old, commit_oid,
                committer=sig._identity,
                message=message.encode(),
            )

    # ------------------------------------------------------------------
    # MutableMapping interface
    # ------------------------------------------------------------------

    def __getitem__(self, h: str) -> str:
        _validate_hash(h)
        tree_oid = self._tree_oid()
        if tree_oid is None:
            raise KeyError(h)
        blob_oid = self._find_note_in_tree(tree_oid, h)
        if blob_oid is None:
            raise KeyError(h)
        return self._store._repo[blob_oid].data.decode()

    def __setitem__(self, h: str, text: str) -> None:
        _validate_hash(h)
        if not isinstance(text, str):
            raise TypeError(f"Expected str value, got {type(text).__name__}")

        repo = self._store._repo
        blob_oid = repo.create_blob(text.encode())

        tree_oid = self._tree_oid()
        h_bytes = h.encode()

        if tree_oid is not None:
            base_tree = repo[tree_oid]
        else:
            base_tree = None

        tb = TreeBuilder(repo._drepo, base_tree)

        # Remove fanout entry if it exists (we always write flat)
        if tree_oid is not None:
            prefix = h[:2].encode()
            suffix = h[2:].encode()
            try:
                mode, sha = repo[tree_oid][prefix]
                if mode == GIT_FILEMODE_TREE:
                    subtree = repo[sha]
                    try:
                        subtree[suffix]
                        # Fanout entry exists — rebuild subtree without it
                        sub_tb = TreeBuilder(repo._drepo, subtree)
                        sub_tb.remove(suffix.decode())
                        new_sub_oid = sub_tb.write()
                        new_sub = repo[new_sub_oid]
                        if len(new_sub) == 0:
                            tb.remove(prefix.decode())
                        else:
                            tb.insert(prefix.decode(), new_sub_oid, GIT_FILEMODE_TREE)
                    except KeyError:
                        pass
            except KeyError:
                pass

        # Write flat entry
        tb.insert(h, blob_oid, GIT_FILEMODE_BLOB)
        new_tree_oid = tb.write()

        self._commit_note_tree(new_tree_oid, f"Notes added by 'git notes' on {h[:7]}")

    def __delitem__(self, h: str) -> None:
        _validate_hash(h)
        tree_oid = self._tree_oid()
        if tree_oid is None:
            raise KeyError(h)

        repo = self._store._repo
        base_tree = repo[tree_oid]
        tb = TreeBuilder(repo._drepo, base_tree)
        h_bytes = h.encode()

        # Try flat removal first
        try:
            mode, _sha = base_tree[h_bytes]
            if mode != GIT_FILEMODE_TREE:
                tb.remove(h)
                new_tree_oid = tb.write()
                self._commit_note_tree(new_tree_oid, f"Notes removed by 'git notes' on {h[:7]}")
                return
        except KeyError:
            pass

        # Try fanout removal
        prefix = h[:2].encode()
        suffix = h[2:].encode()
        try:
            mode, sha = base_tree[prefix]
            if mode == GIT_FILEMODE_TREE:
                subtree = repo[sha]
                subtree[suffix]  # KeyError if missing
                sub_tb = TreeBuilder(repo._drepo, subtree)
                sub_tb.remove(suffix.decode())
                new_sub_oid = sub_tb.write()
                new_sub = repo[new_sub_oid]
                if len(new_sub) == 0:
                    tb.remove(prefix.decode())
                else:
                    tb.insert(prefix.decode(), new_sub_oid, GIT_FILEMODE_TREE)
                new_tree_oid = tb.write()
                self._commit_note_tree(new_tree_oid, f"Notes removed by 'git notes' on {h[:7]}")
                return
        except KeyError:
            pass

        raise KeyError(h)

    def __contains__(self, h: object) -> bool:
        if not isinstance(h, str):
            return False
        try:
            _validate_hash(h)
        except (TypeError, ValueError):
            return False
        tree_oid = self._tree_oid()
        if tree_oid is None:
            return False
        return self._find_note_in_tree(tree_oid, h) is not None

    def __iter__(self) -> Iterator[str]:
        tree_oid = self._tree_oid()
        if tree_oid is None:
            return
        for h, _ in self._iter_notes(tree_oid):
            yield h

    def __len__(self) -> int:
        tree_oid = self._tree_oid()
        if tree_oid is None:
            return 0
        return sum(1 for _ in self._iter_notes(tree_oid))

    # ------------------------------------------------------------------
    # current_ref property
    # ------------------------------------------------------------------

    @property
    def current_ref(self) -> str:
        """Note for the current HEAD commit."""
        current_fs = self._store.branches.current
        if current_fs is None:
            raise RuntimeError("HEAD is dangling — no current branch")
        return self[current_fs.commit_hash]

    @current_ref.setter
    def current_ref(self, text: str) -> None:
        current_fs = self._store.branches.current
        if current_fs is None:
            raise RuntimeError("HEAD is dangling — no current branch")
        self[current_fs.commit_hash] = text

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    def batch(self) -> NotesBatch:
        """Return a context manager that batches writes into a single commit."""
        return NotesBatch(self)


class NotesBatch:
    """Collects note writes/deletes and applies them in one commit on exit.

    Usage::

        with store.notes.commits.batch() as b:
            b[hash1] = "note 1"
            b[hash2] = "note 2"
            del b[hash3]
        # single commit
    """

    def __init__(self, ns: NoteNamespace):
        self._ns = ns
        self._writes: dict[str, str] = {}   # hash → text
        self._deletes: set[str] = set()

    def __enter__(self) -> NotesBatch:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            return
        if not self._writes and not self._deletes:
            return
        self._flush()

    def __setitem__(self, h: str, text: str) -> None:
        _validate_hash(h)
        if not isinstance(text, str):
            raise TypeError(f"Expected str value, got {type(text).__name__}")
        self._deletes.discard(h)
        self._writes[h] = text

    def __delitem__(self, h: str) -> None:
        _validate_hash(h)
        if h in self._writes:
            del self._writes[h]
        self._deletes.add(h)

    def _flush(self) -> None:
        ns = self._ns
        repo = ns._store._repo
        tree_oid = ns._tree_oid()

        if tree_oid is not None:
            base_tree = repo[tree_oid]
        else:
            base_tree = None

        tb = TreeBuilder(repo._drepo, base_tree)

        # Apply deletes
        for h in self._deletes:
            h_bytes = h.encode()
            removed = False

            # Try flat
            if base_tree is not None:
                try:
                    mode, _sha = base_tree[h_bytes]
                    if mode != GIT_FILEMODE_TREE:
                        tb.remove(h)
                        removed = True
                except KeyError:
                    pass

            # Try fanout
            if not removed and base_tree is not None:
                prefix = h[:2].encode()
                suffix = h[2:].encode()
                try:
                    mode, sha = base_tree[prefix]
                    if mode == GIT_FILEMODE_TREE:
                        subtree = repo[sha]
                        subtree[suffix]  # KeyError if missing
                        sub_tb = TreeBuilder(repo._drepo, subtree)
                        sub_tb.remove(suffix.decode())
                        new_sub_oid = sub_tb.write()
                        new_sub = repo[new_sub_oid]
                        if len(new_sub) == 0:
                            tb.remove(prefix.decode())
                        else:
                            tb.insert(prefix.decode(), new_sub_oid, GIT_FILEMODE_TREE)
                        removed = True
                except KeyError:
                    pass

            if not removed:
                raise KeyError(h)

        # Apply writes (flat, clearing fanout if present)
        for h, text in self._writes.items():
            blob_oid = repo.create_blob(text.encode())

            # Remove fanout entry if present
            if tree_oid is not None:
                prefix = h[:2].encode()
                suffix = h[2:].encode()
                try:
                    mode, sha = repo[tree_oid][prefix]
                    if mode == GIT_FILEMODE_TREE:
                        subtree = repo[sha]
                        try:
                            subtree[suffix]
                            sub_tb = TreeBuilder(repo._drepo, subtree)
                            sub_tb.remove(suffix.decode())
                            new_sub_oid = sub_tb.write()
                            new_sub = repo[new_sub_oid]
                            if len(new_sub) == 0:
                                tb.remove(prefix.decode())
                            else:
                                tb.insert(prefix.decode(), new_sub_oid, GIT_FILEMODE_TREE)
                        except KeyError:
                            pass
                except KeyError:
                    pass

            tb.insert(h, blob_oid, GIT_FILEMODE_BLOB)

        new_tree_oid = tb.write()
        count = len(self._writes) + len(self._deletes)
        ns._commit_note_tree(new_tree_oid, f"Notes batch update ({count} changes)")


class NoteDict:
    """Outer container for git notes namespaces on a :class:`GitStore`.

    ``store.notes.commits`` → default namespace (``refs/notes/commits``).
    ``store.notes['reviews']`` → custom namespace.
    """

    def __init__(self, store: GitStore):
        self._store = store

    def __repr__(self) -> str:
        return f"NoteDict({self._store!r})"

    def __getitem__(self, namespace: str) -> NoteNamespace:
        return NoteNamespace(self._store, namespace)

    @property
    def commits(self) -> NoteNamespace:
        """The default ``refs/notes/commits`` namespace."""
        return NoteNamespace(self._store, "commits")

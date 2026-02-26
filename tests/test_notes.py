"""Tests for git notes support (NoteDict / NoteNamespace)."""

import pytest
from dulwich.objects import Blob as DBlob, Tree as DTree
from dulwich.repo import Repo as DulwichRepo

from vost import GitStore, NoteDict, NoteNamespace
from vost.tree import GIT_FILEMODE_BLOB, GIT_FILEMODE_TREE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return GitStore.open(tmp_path / "test.git")


@pytest.fixture
def commit_hash(store):
    """Return the commit hash of the current HEAD commit."""
    return store.branches["main"].commit_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_fanout_note(store, namespace, commit_hash, text):
    """Write a note in 2/38 fanout layout directly via dulwich (for interop tests)."""
    repo = store._repo
    drepo = repo._drepo

    # Create blob
    blob = DBlob.from_string(text.encode())
    drepo.object_store.add_object(blob)

    # Build subtree: h[2:] → blob
    prefix = commit_hash[:2]
    suffix = commit_hash[2:]
    sub_tree = DTree()
    sub_tree.add(suffix.encode(), GIT_FILEMODE_BLOB, blob.id)
    drepo.object_store.add_object(sub_tree)

    # Build root tree: read existing entries + add fanout dir
    ref_name = f"refs/notes/{namespace}"
    ref_bytes = ref_name.encode()

    existing_entries = []
    try:
        tip_oid = drepo.refs[ref_bytes]
        commit = drepo[tip_oid]
        old_tree = drepo[commit.tree]
        for entry in old_tree.iteritems():
            existing_entries.append((entry.path, entry.mode, entry.sha))
        parents = [tip_oid]
    except KeyError:
        parents = []

    root_tree = DTree()
    for name, mode, sha in existing_entries:
        root_tree.add(name, mode, sha)
    root_tree.add(prefix.encode(), GIT_FILEMODE_TREE, sub_tree.id)
    drepo.object_store.add_object(root_tree)

    # Create commit
    from dulwich.objects import Commit as DCommit
    import time

    c = DCommit()
    c.tree = root_tree.id
    c.parents = parents
    c.author = c.committer = b"test <test@test>"
    c.author_time = c.commit_time = int(time.time())
    c.author_timezone = c.commit_timezone = 0
    c.encoding = b"UTF-8"
    c.message = b"fanout note\n"
    drepo.object_store.add_object(c)
    drepo.refs[ref_bytes] = c.id


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

class TestBasicCRUD:
    def test_set_and_get(self, store, commit_hash):
        store.notes.commits[commit_hash] = "hello"
        assert store.notes.commits[commit_hash] == "hello"

    def test_get_missing_raises(self, store, commit_hash):
        with pytest.raises(KeyError):
            store.notes.commits[commit_hash]

    def test_contains_true(self, store, commit_hash):
        store.notes.commits[commit_hash] = "note"
        assert commit_hash in store.notes.commits

    def test_contains_false(self, store, commit_hash):
        assert commit_hash not in store.notes.commits

    def test_delete(self, store, commit_hash):
        store.notes.commits[commit_hash] = "note"
        del store.notes.commits[commit_hash]
        assert commit_hash not in store.notes.commits

    def test_delete_missing_raises(self, store, commit_hash):
        with pytest.raises(KeyError):
            del store.notes.commits[commit_hash]

    def test_overwrite(self, store, commit_hash):
        store.notes.commits[commit_hash] = "first"
        store.notes.commits[commit_hash] = "second"
        assert store.notes.commits[commit_hash] == "second"

    def test_empty_note_text(self, store, commit_hash):
        store.notes.commits[commit_hash] = ""
        assert store.notes.commits[commit_hash] == ""


# ---------------------------------------------------------------------------
# for_current_branch
# ---------------------------------------------------------------------------

class TestForCurrentBranch:
    def test_for_current_branch_read(self, store, commit_hash):
        store.notes.commits[commit_hash] = "my note"
        assert store.notes.commits.for_current_branch == "my note"

    def test_for_current_branch_write(self, store, commit_hash):
        store.notes.commits.for_current_branch = "written via property"
        assert store.notes.commits[commit_hash] == "written via property"

    def test_for_current_branch_when_no_note_raises(self, store):
        with pytest.raises(KeyError):
            store.notes.commits.for_current_branch

    def test_for_current_branch_after_new_commit(self, store):
        fs = store.branches["main"]
        store.notes.commits[fs.commit_hash] = "note on old"
        # Create a new commit
        fs2 = fs.write("file.txt", b"data")
        # for_current_branch should now point to the new commit (which has no note)
        with pytest.raises(KeyError):
            store.notes.commits.for_current_branch


# ---------------------------------------------------------------------------
# Iteration
# ---------------------------------------------------------------------------

class TestIteration:
    def test_iter_empty(self, store):
        assert list(store.notes.commits) == []

    def test_iter_multiple(self, store):
        fs1 = store.branches["main"]
        h1 = fs1.commit_hash
        fs2 = fs1.write("a.txt", b"a")
        h2 = fs2.commit_hash
        store.notes.commits[h1] = "note1"
        store.notes.commits[h2] = "note2"
        hashes = set(store.notes.commits)
        assert hashes == {h1, h2}

    def test_len_empty(self, store):
        assert len(store.notes.commits) == 0

    def test_len_after_adds(self, store):
        fs1 = store.branches["main"]
        h1 = fs1.commit_hash
        fs2 = fs1.write("a.txt", b"a")
        h2 = fs2.commit_hash
        store.notes.commits[h1] = "n1"
        store.notes.commits[h2] = "n2"
        assert len(store.notes.commits) == 2

    def test_len_after_delete(self, store, commit_hash):
        store.notes.commits[commit_hash] = "note"
        assert len(store.notes.commits) == 1
        del store.notes.commits[commit_hash]
        assert len(store.notes.commits) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unicode_text(self, store, commit_hash):
        store.notes.commits[commit_hash] = "Unicode: \u00e9\u00e8\u00ea \u2603 \U0001f600"
        assert store.notes.commits[commit_hash] == "Unicode: \u00e9\u00e8\u00ea \u2603 \U0001f600"

    def test_multiline_text(self, store, commit_hash):
        text = "line1\nline2\nline3\n"
        store.notes.commits[commit_hash] = text
        assert store.notes.commits[commit_hash] == text

    def test_invalid_target_raises(self, store):
        with pytest.raises(ValueError, match="Cannot resolve"):
            store.notes.commits["not-a-hash"] = "note"

    def test_invalid_target_too_short(self, store):
        with pytest.raises(ValueError, match="Cannot resolve"):
            store.notes.commits["abcd"] = "note"

    def test_non_string_value_raises(self, store, commit_hash):
        with pytest.raises(TypeError, match="str"):
            store.notes.commits[commit_hash] = 42

    def test_note_on_nonexistent_commit(self, store):
        fake_hash = "a" * 40
        store.notes.commits[fake_hash] = "orphan note"
        assert store.notes.commits[fake_hash] == "orphan note"


# ---------------------------------------------------------------------------
# Commit chain
# ---------------------------------------------------------------------------

class TestCommitChain:
    def test_first_note_no_parent(self, store, commit_hash):
        store.notes.commits[commit_hash] = "first"
        ns = store.notes.commits
        tip = ns._tip_oid()
        commit = store._repo[tip]
        assert commit.parents == []

    def test_second_note_has_parent(self, store):
        fs = store.branches["main"]
        h1 = fs.commit_hash
        fs2 = fs.write("f.txt", b"x")
        h2 = fs2.commit_hash

        store.notes.commits[h1] = "first"
        ns = store.notes.commits
        first_tip = ns._tip_oid()

        store.notes.commits[h2] = "second"
        second_tip = ns._tip_oid()
        commit = store._repo[second_tip]
        assert commit.parents == [first_tip]

    def test_multiple_notes_chain(self, store):
        fs = store.branches["main"]
        hashes = [fs.commit_hash]
        for i in range(3):
            fs = fs.write(f"f{i}.txt", b"x")
            hashes.append(fs.commit_hash)

        for i, h in enumerate(hashes):
            store.notes.commits[h] = f"note {i}"

        # Verify chain length: 4 commits, each parented to the previous
        ns = store.notes.commits
        tip = ns._tip_oid()
        chain_len = 0
        while tip is not None:
            commit = store._repo[tip]
            chain_len += 1
            tip = commit.parents[0] if commit.parents else None
        assert chain_len == 4


# ---------------------------------------------------------------------------
# Fanout interop
# ---------------------------------------------------------------------------

class TestFanoutInterop:
    def test_read_fanout_note(self, store, commit_hash):
        _create_fanout_note(store, "commits", commit_hash, "fanout note")
        assert store.notes.commits[commit_hash] == "fanout note"

    def test_iter_fanout(self, store, commit_hash):
        _create_fanout_note(store, "commits", commit_hash, "fanout")
        assert commit_hash in list(store.notes.commits)

    def test_contains_fanout(self, store, commit_hash):
        _create_fanout_note(store, "commits", commit_hash, "fanout")
        assert commit_hash in store.notes.commits

    def test_delete_fanout(self, store, commit_hash):
        _create_fanout_note(store, "commits", commit_hash, "fanout")
        del store.notes.commits[commit_hash]
        assert commit_hash not in store.notes.commits

    def test_overwrite_fanout_with_flat(self, store, commit_hash):
        _create_fanout_note(store, "commits", commit_hash, "fanout original")
        store.notes.commits[commit_hash] = "flat replacement"
        assert store.notes.commits[commit_hash] == "flat replacement"
        # Verify it's now flat (no fanout dir for this hash)
        ns = store.notes.commits
        tree_oid = ns._tree_oid()
        tree = store._repo[tree_oid]
        # The flat entry should exist
        try:
            mode, _ = tree[commit_hash.encode()]
            assert mode == GIT_FILEMODE_BLOB
        except KeyError:
            pytest.fail("Expected flat entry in tree")


# ---------------------------------------------------------------------------
# NoteDict outer container
# ---------------------------------------------------------------------------

class TestNoteDict:
    def test_commits_property(self, store):
        ns = store.notes.commits
        assert isinstance(ns, NoteNamespace)
        assert ns._namespace == "commits"

    def test_getitem_custom_namespace(self, store, commit_hash):
        reviews = store.notes["reviews"]
        assert isinstance(reviews, NoteNamespace)
        reviews[commit_hash] = "LGTM"
        assert store.notes["reviews"][commit_hash] == "LGTM"

    def test_separate_namespaces_independent(self, store, commit_hash):
        store.notes.commits[commit_hash] = "default note"
        store.notes["reviews"][commit_hash] = "review note"
        assert store.notes.commits[commit_hash] == "default note"
        assert store.notes["reviews"][commit_hash] == "review note"

    def test_repr(self, store):
        assert "NoteDict" in repr(store.notes)

    def test_namespace_repr(self, store):
        assert "NoteNamespace('commits', len=0)" == repr(store.notes.commits)


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------

class TestBackupRestore:
    def test_backup_preserves_notes(self, tmp_path):
        src = GitStore.open(tmp_path / "src.git")
        h = src.branches["main"].commit_hash
        src.notes.commits[h] = "important note"

        remote_path = str(tmp_path / "remote.git")
        DulwichRepo.init_bare(remote_path, mkdir=True)
        src.backup(remote_path)

        dst = GitStore.open(tmp_path / "remote.git", create=False)
        assert dst.notes.commits[h] == "important note"

    def test_restore_preserves_notes(self, tmp_path):
        # Create remote with a note
        remote = GitStore.open(tmp_path / "remote.git")
        h = remote.branches["main"].commit_hash
        remote.notes.commits[h] = "remote note"

        local_path = str(tmp_path / "local.git")
        DulwichRepo.init_bare(local_path, mkdir=True)
        local = GitStore.open(tmp_path / "local.git", create=False)
        local.restore(str(tmp_path / "remote.git"))

        # Re-open to pick up restored refs
        local = GitStore.open(tmp_path / "local.git", create=False)
        assert local.notes.commits[h] == "remote note"


# ---------------------------------------------------------------------------
# Mapping protocol extras
# ---------------------------------------------------------------------------

class TestMappingProtocol:
    def test_get_with_default(self, store, commit_hash):
        assert store.notes.commits.get(commit_hash, "default") == "default"
        store.notes.commits[commit_hash] = "note"
        assert store.notes.commits.get(commit_hash, "default") == "note"

    def test_keys_values_items(self, store):
        fs = store.branches["main"]
        h1 = fs.commit_hash
        fs2 = fs.write("a.txt", b"a")
        h2 = fs2.commit_hash
        store.notes.commits[h1] = "n1"
        store.notes.commits[h2] = "n2"

        assert set(store.notes.commits.keys()) == {h1, h2}
        assert set(store.notes.commits.values()) == {"n1", "n2"}
        assert set(store.notes.commits.items()) == {(h1, "n1"), (h2, "n2")}


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

class TestBatch:
    def test_batch_multiple_writes_single_commit(self, store):
        fs = store.branches["main"]
        h1 = fs.commit_hash
        fs2 = fs.write("a.txt", b"a")
        h2 = fs2.commit_hash

        with store.notes.commits.batch() as b:
            b[h1] = "note 1"
            b[h2] = "note 2"

        assert store.notes.commits[h1] == "note 1"
        assert store.notes.commits[h2] == "note 2"

        # Only one commit on the notes ref (no parents)
        ns = store.notes.commits
        tip = ns._tip_oid()
        commit = store._repo[tip]
        assert commit.parents == []

    def test_batch_write_and_delete(self, store, commit_hash):
        store.notes.commits[commit_hash] = "old"

        fs2 = store.branches["main"].write("a.txt", b"a")
        h2 = fs2.commit_hash

        with store.notes.commits.batch() as b:
            del b[commit_hash]
            b[h2] = "new"

        assert commit_hash not in store.notes.commits
        assert store.notes.commits[h2] == "new"

    def test_batch_delete_missing_raises(self, store, commit_hash):
        with pytest.raises(KeyError):
            with store.notes.commits.batch() as b:
                del b[commit_hash]

    def test_batch_overwrite_in_batch(self, store, commit_hash):
        with store.notes.commits.batch() as b:
            b[commit_hash] = "first"
            b[commit_hash] = "second"

        assert store.notes.commits[commit_hash] == "second"

    def test_batch_noop_no_commit(self, store):
        # Empty batch should not create any notes ref
        with store.notes.commits.batch() as b:
            pass
        assert store.notes.commits._tip_oid() is None

    def test_batch_set_then_delete_same_hash_no_prior(self, store, commit_hash):
        # Hash never existed in tree — set then delete raises on flush
        with pytest.raises(KeyError):
            with store.notes.commits.batch() as b:
                b[commit_hash] = "will be deleted"
                del b[commit_hash]

    def test_batch_set_then_delete_same_hash_with_prior(self, store, commit_hash):
        # Hash exists in tree — set then delete removes it
        store.notes.commits[commit_hash] = "original"

        with store.notes.commits.batch() as b:
            b[commit_hash] = "overwritten"
            del b[commit_hash]

        assert commit_hash not in store.notes.commits

    def test_batch_delete_then_set_same_hash(self, store, commit_hash):
        store.notes.commits[commit_hash] = "original"

        with store.notes.commits.batch() as b:
            del b[commit_hash]
            b[commit_hash] = "restored"

        assert store.notes.commits[commit_hash] == "restored"

    def test_batch_exception_aborts(self, store, commit_hash):
        with pytest.raises(RuntimeError):
            with store.notes.commits.batch() as b:
                b[commit_hash] = "should not persist"
                raise RuntimeError("abort")

        assert commit_hash not in store.notes.commits

    def test_batch_validation(self, store):
        with pytest.raises(ValueError):
            with store.notes.commits.batch() as b:
                b["bad"] = "note"

        with pytest.raises(TypeError):
            with store.notes.commits.batch() as b:
                b["a" * 40] = 42


# ---------------------------------------------------------------------------
# Ref-based target resolution
# ---------------------------------------------------------------------------

class TestRefTargets:
    def test_set_and_get_by_branch_name(self, store):
        ns = store.notes.commits
        ns["main"] = "note for main"
        assert ns["main"] == "note for main"

    def test_set_and_get_by_tag_name(self, store):
        fs = store.branches["main"]
        store.tags["v1.0"] = fs
        ns = store.notes.commits
        ns["v1.0"] = "note for tag"
        assert ns["v1.0"] == "note for tag"

    def test_ref_and_hash_access_same_note(self, store):
        fs = store.branches["main"]
        ns = store.notes.commits
        ns["main"] = "via ref"
        assert ns[fs.commit_hash] == "via ref"

    def test_contains_by_ref(self, store):
        ns = store.notes.commits
        assert "main" not in ns
        ns["main"] = "note"
        assert "main" in ns

    def test_delete_by_ref(self, store):
        ns = store.notes.commits
        ns["main"] = "note"
        assert "main" in ns
        del ns["main"]
        assert "main" not in ns

    def test_batch_with_ref_targets(self, store):
        fs = store.branches["main"]
        store.branches["dev"] = fs
        # Advance main so the two branches have different tips
        fs2 = fs.write("a.txt", b"a")

        with store.notes.commits.batch() as b:
            b["main"] = "note for main"
            b["dev"] = "note for dev"

        assert store.notes.commits["main"] == "note for main"
        assert store.notes.commits["dev"] == "note for dev"

    def test_batch_delete_by_ref(self, store):
        ns = store.notes.commits
        ns["main"] = "note"

        with ns.batch() as b:
            del b["main"]

        assert "main" not in ns

    def test_nonexistent_ref_raises(self, store):
        with pytest.raises(ValueError, match="Cannot resolve"):
            store.notes.commits["nonexistent"] = "note"

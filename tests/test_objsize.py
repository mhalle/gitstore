"""Tests for _objsize.ObjectSizer."""

import pytest

from gitstore import GitStore
from gitstore._objsize import ObjectSizer


@pytest.fixture
def store_with_files(tmp_path):
    """Repo with several files of known content."""
    store = GitStore.open(tmp_path / "test.git")
    fs = store.branches["main"]
    with fs.batch() as b:
        b.write("empty.txt", b"")
        b.write("hello.txt", b"hello world")
        b.write("binary.bin", b"\x00" * 1024)
        b.write("nested/deep/file.txt", b"deep content here")
    return store


def _all_file_entries(fs):
    """Yield (full_path, WalkEntry) for every file in the tree."""
    for dirpath, _dirs, files in fs.walk():
        for fe in files:
            full = f"{dirpath}/{fe.name}" if dirpath else fe.name
            yield full, fe


class TestObjectSizer:
    def test_blob_sizes_match_content(self, store_with_files):
        store = store_with_files
        fs = store.branches["main"]
        obj_store = store._repo._repo.object_store

        expected = {
            "empty.txt": 0,
            "hello.txt": 11,
            "binary.bin": 1024,
            "nested/deep/file.txt": 17,
        }

        with ObjectSizer(obj_store) as sizer:
            for path, fe in _all_file_entries(fs):
                if path in expected:
                    assert sizer.size(fe.oid.raw) == expected[path], path

    def test_matches_raw_length(self, store_with_files):
        """ObjectSizer must agree with dulwich raw_length() for every blob."""
        store = store_with_files
        fs = store.branches["main"]
        obj_store = store._repo._repo.object_store

        with ObjectSizer(obj_store) as sizer:
            for path, fe in _all_file_entries(fs):
                fast = sizer.size(fe.oid.raw)
                full = obj_store[fe.oid.raw].raw_length()
                assert fast == full, f"{path}: sizer={fast}, raw_length={full}"

    def test_tree_and_commit_sizes(self, store_with_files):
        """ObjectSizer works on any object type, not just blobs."""
        store = store_with_files
        fs = store.branches["main"]
        obj_store = store._repo._repo.object_store

        # Commit
        commit_sha = fs.commit_hash.encode()
        with ObjectSizer(obj_store) as sizer:
            commit_size = sizer.size(commit_sha)
        assert commit_size == obj_store[commit_sha].raw_length()

        # Tree (root tree from commit)
        commit_obj = obj_store[commit_sha]
        tree_sha = commit_obj.tree
        with ObjectSizer(obj_store) as sizer:
            tree_size = sizer.size(tree_sha)
        assert tree_size == obj_store[tree_sha].raw_length()

    def test_context_manager_closes_fds(self, store_with_files):
        store = store_with_files
        obj_store = store._repo._repo.object_store

        sizer = ObjectSizer(obj_store)
        fs = store.branches["main"]
        _, fe = next(_all_file_entries(fs))
        sizer.size(fe.oid.raw)

        sizer.close()
        assert sizer._pack_fds == {}
        assert sizer._pack_index is None

    def test_reusable_across_many_lookups(self, store_with_files):
        """Single sizer instance handles repeated lookups correctly."""
        store = store_with_files
        fs = store.branches["main"]
        obj_store = store._repo._repo.object_store

        with ObjectSizer(obj_store) as sizer:
            for _, fe in _all_file_entries(fs):
                s1 = sizer.size(fe.oid.raw)
                s2 = sizer.size(fe.oid.raw)
                assert s1 == s2

    def test_large_blob(self, tmp_path):
        """Correct size for a blob larger than the 64-byte read window."""
        store = GitStore.open(tmp_path / "test.git")
        fs = store.branches["main"]
        big = b"x" * 100_000
        fs = fs.write("big.bin", big)

        obj_store = store._repo._repo.object_store
        _, fe = next(
            (p, e) for p, e in _all_file_entries(fs) if p == "big.bin"
        )

        with ObjectSizer(obj_store) as sizer:
            assert sizer.size(fe.oid.raw) == 100_000

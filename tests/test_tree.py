"""Tests for gitstore.tree module."""

import pytest

from gitstore.tree import (
    _normalize_path,
    rebuild_tree,
    read_blob_at_path,
    list_tree_at_path,
    walk_tree,
    exists_at_path,
)


class TestNormalizePath:
    def test_simple(self):
        assert _normalize_path("foo/bar") == "foo/bar"

    def test_strips_slashes(self):
        assert _normalize_path("/foo/bar/") == "foo/bar"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _normalize_path("")

    def test_rejects_dot(self):
        with pytest.raises(ValueError):
            _normalize_path("foo/./bar")

    def test_rejects_dotdot(self):
        with pytest.raises(ValueError):
            _normalize_path("foo/../bar")

    def test_rejects_empty_segment(self):
        with pytest.raises(ValueError):
            _normalize_path("foo//bar")


class TestRebuildTree:
    def test_single_file(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"hello.txt": b"Hello"}, set())
        data = read_blob_at_path(bare_repo, oid, "hello.txt")
        assert data == b"Hello"

    def test_nested_path(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"a/b/c.txt": b"deep"}, set())
        assert read_blob_at_path(bare_repo, oid, "a/b/c.txt") == b"deep"

    def test_structural_sharing(self, bare_repo):
        """Modifying one file should not change sibling subtree OIDs."""
        oid1 = rebuild_tree(
            bare_repo,
            None,
            {"a/x.txt": b"x", "b/y.txt": b"y"},
            set(),
        )
        # Modify only a/x.txt
        oid2 = rebuild_tree(
            bare_repo,
            oid1,
            {"a/x.txt": b"x2"},
            set(),
        )
        # b subtree should be identical
        tree1 = bare_repo[oid1]
        tree2 = bare_repo[oid2]
        b_oid1 = tree1["b"].id
        b_oid2 = tree2["b"].id
        assert b_oid1 == b_oid2

        # a subtree should differ
        a_oid1 = tree1["a"].id
        a_oid2 = tree2["a"].id
        assert a_oid1 != a_oid2

    def test_remove_file(self, bare_repo):
        oid = rebuild_tree(
            bare_repo, None, {"a.txt": b"a", "b.txt": b"b"}, set()
        )
        oid2 = rebuild_tree(bare_repo, oid, {}, {"a.txt"})
        assert not exists_at_path(bare_repo, oid2, "a.txt")
        assert exists_at_path(bare_repo, oid2, "b.txt")

    def test_remove_last_file_prunes_dir(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"d/only.txt": b"x"}, set())
        oid2 = rebuild_tree(bare_repo, oid, {}, {"d/only.txt"})
        assert not exists_at_path(bare_repo, oid2, "d")

    def test_remove_missing_is_noop(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"a.txt": b"a"}, set())
        oid2 = rebuild_tree(bare_repo, oid, {}, {"nope.txt"})
        # Tree should be unchanged
        assert oid == oid2

    def test_overwrite_file_with_directory(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"x": b"file"}, set())
        oid2 = rebuild_tree(bare_repo, oid, {"x/sub.txt": b"sub"}, set())
        assert read_blob_at_path(bare_repo, oid2, "x/sub.txt") == b"sub"

    def test_overwrite_directory_with_file(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"x/sub.txt": b"sub"}, set())
        oid2 = rebuild_tree(bare_repo, oid, {"x": b"file"}, set())
        assert read_blob_at_path(bare_repo, oid2, "x") == b"file"


class TestReadHelpers:
    def test_read_blob(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"f.txt": b"data"}, set())
        assert read_blob_at_path(bare_repo, oid, "f.txt") == b"data"

    def test_read_missing_raises(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"f.txt": b"data"}, set())
        with pytest.raises(FileNotFoundError):
            read_blob_at_path(bare_repo, oid, "nope.txt")

    def test_read_directory_raises(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"d/f.txt": b"data"}, set())
        with pytest.raises(IsADirectoryError):
            read_blob_at_path(bare_repo, oid, "d")

    def test_list_root(self, bare_repo):
        oid = rebuild_tree(
            bare_repo, None, {"a.txt": b"a", "b/c.txt": b"c"}, set()
        )
        entries = list_tree_at_path(bare_repo, oid)
        assert sorted(entries) == ["a.txt", "b"]

    def test_list_subdir(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"d/x.txt": b"x", "d/y.txt": b"y"}, set())
        entries = list_tree_at_path(bare_repo, oid, "d")
        assert sorted(entries) == ["x.txt", "y.txt"]

    def test_list_file_raises(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"f.txt": b"data"}, set())
        with pytest.raises(NotADirectoryError):
            list_tree_at_path(bare_repo, oid, "f.txt")

    def test_exists(self, bare_repo):
        oid = rebuild_tree(bare_repo, None, {"a/b.txt": b"x"}, set())
        assert exists_at_path(bare_repo, oid, "a/b.txt")
        assert exists_at_path(bare_repo, oid, "a")
        assert not exists_at_path(bare_repo, oid, "nope")


class TestWalkTree:
    def test_walk_empty(self, bare_repo):
        oid = bare_repo.TreeBuilder().write()
        result = list(walk_tree(bare_repo, oid))
        assert result == [("", [], [])]

    def test_walk_nested(self, bare_repo):
        oid = rebuild_tree(
            bare_repo,
            None,
            {"a.txt": b"a", "d/x.txt": b"x", "d/sub/y.txt": b"y"},
            set(),
        )
        result = list(walk_tree(bare_repo, oid))
        # Root
        assert result[0][0] == ""
        assert sorted(result[0][1]) == ["d"]
        assert sorted(result[0][2]) == ["a.txt"]
        # d/
        d_entry = [r for r in result if r[0] == "d"][0]
        assert sorted(d_entry[1]) == ["sub"]
        assert sorted(d_entry[2]) == ["x.txt"]
        # d/sub/
        sub_entry = [r for r in result if r[0] == "d/sub"][0]
        assert sub_entry[1] == []
        assert sub_entry[2] == ["y.txt"]

"""Tests for GitStore.pack() and GitStore.gc()."""

import pytest

from vost import GitStore


@pytest.fixture
def store(tmp_path):
    return GitStore.open(tmp_path / "test.git")


class TestPack:
    def test_pack_returns_count(self, store):
        fs = store.branches["main"]
        fs = fs.write("a.txt", b"aaa")
        fs = fs.write("b.txt", b"bbb")
        count = store.pack()
        assert count > 0

    def test_pack_idempotent(self, store):
        fs = store.branches["main"]
        fs = fs.write("a.txt", b"aaa")
        store.pack()
        count = store.pack()
        assert count == 0

    def test_pack_preserves_data(self, store):
        fs = store.branches["main"]
        fs = fs.write("a.txt", b"hello")
        fs = fs.write("b.txt", b"world")
        store.pack()
        fs = store.branches["main"]
        assert fs.read("a.txt") == b"hello"
        assert fs.read("b.txt") == b"world"

    def test_pack_empty_repo(self, tmp_path):
        store = GitStore.open(tmp_path / "empty.git", branch=None)
        count = store.pack()
        assert count >= 0


class TestGc:
    def test_gc_returns_count(self, store):
        fs = store.branches["main"]
        fs = fs.write("a.txt", b"aaa")
        count = store.gc()
        assert count > 0

    def test_gc_idempotent(self, store):
        fs = store.branches["main"]
        fs = fs.write("a.txt", b"aaa")
        store.gc()
        count = store.gc()
        assert count == 0

    def test_gc_preserves_data(self, store):
        fs = store.branches["main"]
        fs = fs.write("a.txt", b"hello")
        store.gc()
        fs = store.branches["main"]
        assert fs.read("a.txt") == b"hello"

    def test_gc_empty_repo(self, tmp_path):
        store = GitStore.open(tmp_path / "empty.git", branch=None)
        count = store.gc()
        assert count >= 0

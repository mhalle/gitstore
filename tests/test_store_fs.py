"""Tests for GitStore.fs() — unified ref resolution."""

import pytest

from vost import GitStore


@pytest.fixture
def store(tmp_path):
    return GitStore.open(str(tmp_path / "test.git"), branch="main")


def test_fs_branch(store):
    fs = store.branches["main"]
    fs.write("hello.txt", b"hello")

    result = store.fs("main")
    assert result.read("hello.txt") == b"hello"
    assert result.writable is True
    assert result.ref_name == "main"


def test_fs_tag(store):
    fs = store.branches["main"].write("data.txt", b"data")
    store.tags["v1"] = fs

    result = store.fs("v1")
    assert result.read("data.txt") == b"data"
    assert result.writable is False


def test_fs_full_hash(store):
    fs = store.branches["main"].write("file.txt", b"content")
    commit_hash = fs.commit_hash

    result = store.fs(commit_hash)
    assert result.read("file.txt") == b"content"
    assert result.writable is False


def test_fs_short_hash(store):
    fs = store.branches["main"].write("file.txt", b"content")
    short = fs.commit_hash[:8]

    result = store.fs(short)
    assert result.read("file.txt") == b"content"
    assert result.writable is False


def test_fs_back(store):
    fs1 = store.branches["main"].write("a.txt", b"a")
    fs2 = fs1.write("b.txt", b"b")

    result = store.fs("main", back=1)
    assert result.exists("a.txt")
    assert not result.exists("b.txt")


def test_fs_missing_ref(store):
    with pytest.raises(KeyError, match="ref not found"):
        store.fs("nonexistent")


def test_fs_branch_before_tag(store):
    """Branch resolution takes priority over tags."""
    fs = store.branches["main"].write("x.txt", b"x")
    # Create a branch and tag with same name (contrived but tests priority)
    store.tags["main"] = fs  # tag named 'main' too
    result = store.fs("main")
    assert result.writable is True  # branch wins

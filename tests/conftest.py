"""Shared fixtures for gitstore tests."""

import pygit2
import pytest


@pytest.fixture
def bare_repo(tmp_path):
    """Create a bare pygit2 repository."""
    repo_path = str(tmp_path / "test.git")
    return pygit2.init_repository(repo_path, bare=True)


@pytest.fixture
def bootstrapped_repo(tmp_path):
    """Create a bare repo with an initial empty commit on 'main'."""
    repo_path = str(tmp_path / "test.git")
    repo = pygit2.init_repository(repo_path, bare=True)
    sig = pygit2.Signature("test", "test@test.com")
    tree_oid = repo.TreeBuilder().write()
    repo.create_commit("refs/heads/main", sig, sig, "Initialize main", tree_oid, [])
    return repo

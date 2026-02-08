"""Shared fixtures for gitstore tests."""

from gitstore import _compat as pygit2
import pytest


@pytest.fixture
def bare_repo(tmp_path):
    """Create a bare pygit2-compatible repository."""
    repo_path = str(tmp_path / "test.git")
    return pygit2.init_repository(repo_path, bare=True)

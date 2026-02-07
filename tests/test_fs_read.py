"""Tests for FS read operations."""

import pytest

from gitstore import GitStore


@pytest.fixture
def repo_with_files(tmp_path):
    repo = GitStore.open(tmp_path / "test.git", create="main")
    fs = repo.branches["main"]
    fs = fs.write("hello.txt", b"Hello!")
    fs = fs.write("src/main.py", b"print('hi')")
    fs = fs.write("src/lib/util.py", b"# util")
    return repo, fs


class TestRead:
    def test_read_file(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.read("hello.txt") == b"Hello!"

    def test_read_nested(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.read("src/main.py") == b"print('hi')"

    def test_read_missing(self, repo_with_files):
        _, fs = repo_with_files
        with pytest.raises(FileNotFoundError):
            fs.read("nope.txt")

    def test_read_directory(self, repo_with_files):
        _, fs = repo_with_files
        with pytest.raises(IsADirectoryError):
            fs.read("src")


class TestLs:
    def test_ls_root(self, repo_with_files):
        _, fs = repo_with_files
        assert sorted(fs.ls()) == ["hello.txt", "src"]

    def test_ls_subdir(self, repo_with_files):
        _, fs = repo_with_files
        assert sorted(fs.ls("src")) == ["lib", "main.py"]

    def test_ls_file_raises(self, repo_with_files):
        _, fs = repo_with_files
        with pytest.raises(NotADirectoryError):
            fs.ls("hello.txt")


class TestWalk:
    def test_walk(self, repo_with_files):
        _, fs = repo_with_files
        result = list(fs.walk())
        root = result[0]
        assert root[0] == ""
        assert sorted(root[1]) == ["src"]
        assert sorted(root[2]) == ["hello.txt"]

    def test_walk_subdir(self, repo_with_files):
        _, fs = repo_with_files
        result = list(fs.walk("src"))
        assert result[0][0] == "src"
        assert sorted(result[0][2]) == ["main.py"]

    def test_walk_on_file_raises(self, repo_with_files):
        _, fs = repo_with_files
        with pytest.raises(NotADirectoryError):
            list(fs.walk("hello.txt"))


class TestExists:
    def test_exists_file(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.exists("hello.txt")

    def test_exists_dir(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.exists("src")

    def test_not_exists(self, repo_with_files):
        _, fs = repo_with_files
        assert not fs.exists("nope.txt")


class TestDump:
    def test_dump_creates_files(self, repo_with_files, tmp_path):
        _, fs = repo_with_files
        out = tmp_path / "out"
        fs.dump(out)
        assert (out / "hello.txt").read_bytes() == b"Hello!"
        assert (out / "src" / "main.py").read_bytes() == b"print('hi')"
        assert (out / "src" / "lib" / "util.py").read_bytes() == b"# util"

    def test_dump_empty_tree(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git", create="main")
        fs = repo.branches["main"]
        out = tmp_path / "out"
        fs.dump(out)
        assert out.is_dir()
        assert list(out.iterdir()) == []

    def test_dump_overwrites_existing(self, repo_with_files, tmp_path):
        _, fs = repo_with_files
        out = tmp_path / "out"
        out.mkdir()
        (out / "hello.txt").write_bytes(b"old")
        fs.dump(out)
        assert (out / "hello.txt").read_bytes() == b"Hello!"


class TestProperties:
    def test_hash(self, repo_with_files):
        _, fs = repo_with_files
        assert isinstance(fs.hash, str)
        assert len(fs.hash) == 40

    def test_branch(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.branch == "main"

    def test_message(self, repo_with_files):
        _, fs = repo_with_files
        assert "util.py" in fs.message

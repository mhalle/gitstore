"""Tests for FS read operations."""

from pathlib import PurePosixPath

import pytest

from vost import GitStore


@pytest.fixture
def repo_with_files(tmp_path):
    repo = GitStore.open(tmp_path / "test.git")
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


class TestReadText:
    def test_read_text(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.read_text("hello.txt") == "Hello!"

    def test_read_text_encoding(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("latin.txt", "café".encode("latin-1"))
        assert fs.read_text("latin.txt", encoding="latin-1") == "café"


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
        assert sorted(e.name for e in root[2]) == ["hello.txt"]

    def test_walk_subdir(self, repo_with_files):
        _, fs = repo_with_files
        result = list(fs.walk("src"))
        assert result[0][0] == "src"
        assert sorted(e.name for e in result[0][2]) == ["main.py"]

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


class TestCopyOutRoot:
    def test_copy_out_creates_files(self, repo_with_files, tmp_path):
        _, fs = repo_with_files
        out = tmp_path / "out"
        fs.copy_out("/", str(out))
        assert (out / "hello.txt").read_bytes() == b"Hello!"
        assert (out / "src" / "main.py").read_bytes() == b"print('hi')"
        assert (out / "src" / "lib" / "util.py").read_bytes() == b"# util"

    def test_copy_out_empty_repo(self, tmp_path):
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        out = tmp_path / "out"
        out.mkdir()
        fs.copy_out("/", str(out))
        assert out.is_dir()
        assert list(out.iterdir()) == []

    def test_copy_out_overwrites_existing_files(self, repo_with_files, tmp_path):
        _, fs = repo_with_files
        out = tmp_path / "out"
        out.mkdir()
        (out / "hello.txt").write_bytes(b"old")
        fs.copy_out("/", str(out))
        assert (out / "hello.txt").read_bytes() == b"Hello!"

    def test_copy_out_symlinks(self, tmp_path):
        import os
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs = fs.write_symlink("link.txt", "target.txt")
        out = tmp_path / "out"
        fs.copy_out("/", str(out))
        assert (out / "target.txt").read_bytes() == b"content"
        assert (out / "link.txt").is_symlink()
        assert os.readlink(out / "link.txt") == "target.txt"

    def test_copy_out_symlinks_overwrite_regular_files(self, tmp_path):
        import os
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write_symlink("link.txt", "target.txt")
        out = tmp_path / "out"
        out.mkdir()
        (out / "link.txt").write_bytes(b"old regular file")
        fs.copy_out("/", str(out))
        assert (out / "link.txt").is_symlink()
        assert os.readlink(out / "link.txt") == "target.txt"


class TestFileType:
    def test_type_blob(self, repo_with_files):
        _, fs = repo_with_files
        from vost import FileType
        assert fs.file_type("hello.txt") == FileType.BLOB

    def test_type_tree(self, repo_with_files):
        _, fs = repo_with_files
        from vost import FileType
        assert fs.file_type("src") == FileType.TREE

    def test_type_nested(self, repo_with_files):
        _, fs = repo_with_files
        from vost import FileType
        assert fs.file_type("src/main.py") == FileType.BLOB

    def test_type_executable(self, tmp_path):
        from vost import FileType
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("run.sh", b"#!/bin/sh\n", mode=FileType.EXECUTABLE)
        assert fs.file_type("run.sh") == FileType.EXECUTABLE

    def test_type_symlink(self, tmp_path):
        from vost import FileType
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs = fs.write_symlink("link.txt", "target.txt")
        assert fs.file_type("link.txt") == FileType.LINK

    def test_type_missing(self, repo_with_files):
        _, fs = repo_with_files
        with pytest.raises(FileNotFoundError):
            fs.file_type("nope.txt")

    def test_type_pathlike(self, repo_with_files):
        _, fs = repo_with_files
        from vost import FileType
        assert fs.file_type(PurePosixPath("src/main.py")) == FileType.BLOB


class TestSize:
    def test_size_file(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.size("hello.txt") == len(b"Hello!")

    def test_size_nested(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.size("src/main.py") == len(b"print('hi')")

    def test_size_missing(self, repo_with_files):
        _, fs = repo_with_files
        with pytest.raises(FileNotFoundError):
            fs.size("nope.txt")

    def test_size_matches_read(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.size("hello.txt") == len(fs.read("hello.txt"))

    def test_size_pathlike(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.size(PurePosixPath("hello.txt")) == len(b"Hello!")


class TestObjectHash:
    def test_hash_is_hex(self, repo_with_files):
        _, fs = repo_with_files
        h = fs.object_hash("hello.txt")
        assert isinstance(h, str)
        assert len(h) == 40
        int(h, 16)  # valid hex

    def test_hash_same_content(self, tmp_path):
        """Same content in different paths produces the same blob hash."""
        repo = GitStore.open(tmp_path / "test.git")
        fs = repo.branches["main"]
        fs = fs.write("a.txt", b"same")
        fs = fs.write("b.txt", b"same")
        assert fs.object_hash("a.txt") == fs.object_hash("b.txt")

    def test_hash_different_content(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.object_hash("hello.txt") != fs.object_hash("src/main.py")

    def test_hash_tree(self, repo_with_files):
        _, fs = repo_with_files
        h = fs.object_hash("src")
        assert isinstance(h, str)
        assert len(h) == 40

    def test_hash_missing(self, repo_with_files):
        _, fs = repo_with_files
        with pytest.raises(FileNotFoundError):
            fs.object_hash("nope.txt")

    def test_hash_stable(self, repo_with_files):
        """Hash doesn't change across reads."""
        _, fs = repo_with_files
        assert fs.object_hash("hello.txt") == fs.object_hash("hello.txt")

    def test_hash_pathlike(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.object_hash(PurePosixPath("hello.txt")) == fs.object_hash("hello.txt")


class TestPathLikeSupport:
    def test_read_with_path(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.read(PurePosixPath("hello.txt")) == b"Hello!"

    def test_write_with_path(self, repo_with_files):
        _, fs = repo_with_files
        fs2 = fs.write(PurePosixPath("new.txt"), b"data")
        assert fs2.read("new.txt") == b"data"

    def test_exists_with_path(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.exists(PurePosixPath("src/main.py"))

    def test_ls_with_path(self, repo_with_files):
        _, fs = repo_with_files
        assert "main.py" in fs.ls(PurePosixPath("src"))

    def test_walk_with_path(self, repo_with_files):
        _, fs = repo_with_files
        entries = list(fs.walk(PurePosixPath("src")))
        assert len(entries) > 0

    def test_remove_with_path(self, repo_with_files):
        _, fs = repo_with_files
        fs2 = fs.remove(PurePosixPath("hello.txt"))
        assert not fs2.exists("hello.txt")

    def test_read_text_with_path(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.read_text(PurePosixPath("hello.txt")) == "Hello!"


class TestProperties:
    def test_hash(self, repo_with_files):
        _, fs = repo_with_files
        assert isinstance(fs.commit_hash, str)
        assert len(fs.commit_hash) == 40

    def test_ref_name(self, repo_with_files):
        _, fs = repo_with_files
        assert fs.ref_name == "main"

    def test_message(self, repo_with_files):
        _, fs = repo_with_files
        assert "util.py" in fs.message

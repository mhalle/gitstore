"""Tests for the vost CLI — zip, unzip, tar, untar, archive, unarchive."""

import io
import time
import zipfile

import pytest
from click.testing import CliRunner

from vost.cli import main


class TestZip:
    def test_zip_basic(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "hello.txt" in names
            assert "data/data.bin" in names

    def test_zip_contents(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            assert zf.read("hello.txt") == b"hello world\n"
            assert zf.read("data/data.bin") == b"\x00\x01\x02"

    def test_zip_with_at(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out, "--path", "a.txt"])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "a.txt" in names
            # b.txt was added after a.txt, so the snapshot at a.txt shouldn't have it
            assert "b.txt" not in names

    def test_zip_with_match(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out, "--match", "deploy*"])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            assert zf.read("a.txt") == b"v1"

    def test_zip_stdout(self, runner, repo_with_files):
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, "-"])
        assert result.exit_code == 0, result.output
        zf = zipfile.ZipFile(io.BytesIO(result.output_bytes))
        names = zf.namelist()
        assert "hello.txt" in names
        assert zf.read("hello.txt") == b"hello world\n"

    def test_zip_preserves_executable(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh\necho hi")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":run.sh", "--type", "executable"
        ])
        assert result.exit_code == 0, result.output

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            info = zf.getinfo("run.sh")
            unix_mode = info.external_attr >> 16
            assert unix_mode & 0o111  # executable bit set

    def test_zip_no_match_error(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", repo_with_files, out, "--match", "zzz-no-match*"])
        assert result.exit_code != 0
        assert "No matching commits" in result.output

    def test_zip_preserves_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in the repo are exported as symlinks in the zip."""
        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            info = zf.getinfo("link.txt")
            unix_mode = info.external_attr >> 16
            assert (unix_mode & 0o170000) == 0o120000
            assert zf.read("link.txt") == b"target.txt"

    def test_zip_create_system_unix(self, runner, initialized_repo, tmp_path):
        """Zip entries have create_system=3 (Unix) for correct external_attr."""
        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("file.txt", b"data")
        fs.write_symlink("link.txt", "file.txt")

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["zip", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            for info in zf.infolist():
                assert info.create_system == 3, f"{info.filename}: create_system={info.create_system}"


class TestUnzip:
    def test_unzip_basic(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("file1.txt", "hello")
            zf.writestr("file2.txt", "world")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "file1.txt" in result.output
        assert "file2.txt" in result.output

    def test_unzip_contents(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("greet.txt", "hi there")
        runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":greet.txt"])
        assert result.exit_code == 0
        assert "hi there" in result.output

    def test_unzip_custom_message(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("msg.txt", "data")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath, "-m", "bulk import"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "bulk import" in result.output

    def test_unzip_nested(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("dir/sub/deep.txt", "nested content")
            zf.writestr("top.txt", "top level")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":dir/sub"])
        assert "deep.txt" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/sub/deep.txt"])
        assert "nested content" in result.output

    def test_unzip_preserves_executable(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            info = zipfile.ZipInfo("script.sh")
            info.external_attr = 0o100755 << 16
            zf.writestr(info, "#!/bin/sh\necho hi")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output

        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.file_type("script.sh") == FileType.EXECUTABLE

    def test_unzip_roundtrip_permissions(self, runner, initialized_repo, tmp_path):
        """Zip then unzip preserves executable bit."""
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":run.sh", "--type", "executable"])
        f2 = tmp_path / "data.txt"
        f2.write_text("plain")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":data.txt"])

        # Zip it
        archive = str(tmp_path / "archive.zip")
        runner.invoke(main, ["zip", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["unzip", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(p2, create=False)
        fs = store.branches["main"]
        assert fs.file_type("run.sh") == FileType.EXECUTABLE
        assert fs.file_type("data.txt") == FileType.BLOB

    def test_unzip_invalid_zip(self, runner, initialized_repo, tmp_path):
        bad = tmp_path / "notazip.bin"
        bad.write_bytes(b"this is not a zip")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, str(bad)])
        assert result.exit_code != 0
        assert "Not a valid zip" in result.output

    def test_unzip_empty_zip(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "empty.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            pass  # no files
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code != 0
        assert "no files" in result.output.lower()

    def test_unzip_imports_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in a zip are imported as symlinks in the repo."""
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("target.txt", "content")
            info = zipfile.ZipInfo("link.txt")
            info.external_attr = 0o120000 << 16
            zf.writestr(info, "target.txt")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output

        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.file_type("link.txt") == FileType.LINK
        assert fs.readlink("link.txt") == "target.txt"

    def test_unzip_roundtrip_symlinks(self, runner, initialized_repo, tmp_path):
        """Zip then unzip preserves symlinks."""
        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        # Zip it
        archive = str(tmp_path / "archive.zip")
        runner.invoke(main, ["zip", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["unzip", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        store2 = GitStore.open(p2, create=False)
        fs2 = store2.branches["main"]
        assert fs2.readlink("link.txt") == "target.txt"
        assert fs2.file_type("link.txt") == FileType.LINK
        assert fs2.file_type("target.txt") == FileType.BLOB

    def test_unzip_leading_dot_slash(self, runner, initialized_repo, tmp_path):
        """Zip entries with leading ./ are accepted and normalized."""
        zpath = str(tmp_path / "import.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("./dir/file.txt", "hello")
            zf.writestr("./top.txt", "top")
        result = runner.invoke(main, ["unzip", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/file.txt"])
        assert "hello" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":top.txt"])
        assert "top" in result.output


class TestTar:
    def test_tar_basic(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "hello.txt" in names
            assert "data/data.bin" in names

    def test_tar_contents(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            assert tf.extractfile("hello.txt").read() == b"hello world\n"
            assert tf.extractfile("data/data.bin").read() == b"\x00\x01\x02"

    def test_tar_gz(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar.gz")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        import gzip
        with open(out, "rb") as f:
            # gzip magic bytes
            assert f.read(2) == b"\x1f\x8b"
        import tarfile
        with tarfile.open(out, "r:gz") as tf:
            names = tf.getnames()
            assert "hello.txt" in names

    def test_tar_with_at(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out, "--path", "a.txt"])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "a.txt" in names
            assert "b.txt" not in names

    def test_tar_with_match(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "fix bug"])

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out, "--match", "deploy*"])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            assert tf.extractfile("a.txt").read() == b"v1"

    def test_tar_stdout(self, runner, repo_with_files):
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, "-"])
        assert result.exit_code == 0, result.output
        import tarfile
        tf = tarfile.open(fileobj=io.BytesIO(result.output_bytes), mode="r:")
        names = tf.getnames()
        assert "hello.txt" in names
        assert tf.extractfile("hello.txt").read() == b"hello world\n"
        tf.close()

    def test_tar_preserves_executable(self, runner, initialized_repo, tmp_path):
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh\necho hi")
        result = runner.invoke(main, [
            "cp", "--repo", initialized_repo, str(f), ":run.sh", "--type", "executable"
        ])
        assert result.exit_code == 0, result.output

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        import tarfile
        with tarfile.open(out, "r") as tf:
            info = tf.getmember("run.sh")
            assert info.mode & 0o111  # executable bit set

    def test_tar_no_match_error(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", repo_with_files, out, "--match", "zzz-no-match*"])
        assert result.exit_code != 0
        assert "No matching commits" in result.output

    def test_tar_preserves_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in the repo are exported as symlinks in the tar."""
        import tarfile
        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["tar", "--repo", initialized_repo, out])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r") as tf:
            member = tf.getmember("link.txt")
            assert member.issym()
            assert member.linkname == "target.txt"


class TestUntar:
    def test_untar_basic(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="file1.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            data2 = b"world"
            info2 = tarfile.TarInfo(name="file2.txt")
            info2.size = len(data2)
            tf.addfile(info2, io.BytesIO(data2))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["ls", "--repo", initialized_repo])
        assert "file1.txt" in result.output
        assert "file2.txt" in result.output

    def test_untar_contents(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"hi there"
            info = tarfile.TarInfo(name="greet.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])

        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":greet.txt"])
        assert result.exit_code == 0
        assert "hi there" in result.output

    def test_untar_custom_message(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"data"
            info = tarfile.TarInfo(name="msg.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath, "-m", "bulk import"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "bulk import" in result.output

    def test_untar_nested(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"nested content"
            info = tarfile.TarInfo(name="dir/sub/deep.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            data2 = b"top level"
            info2 = tarfile.TarInfo(name="top.txt")
            info2.size = len(data2)
            tf.addfile(info2, io.BytesIO(data2))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output

        result = runner.invoke(main, ["ls", "--repo", initialized_repo, ":dir/sub"])
        assert "deep.txt" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/sub/deep.txt"])
        assert "nested content" in result.output

    def test_untar_preserves_executable(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"#!/bin/sh\necho hi"
            info = tarfile.TarInfo(name="script.sh")
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output

        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.file_type("script.sh") == FileType.EXECUTABLE

    def test_untar_roundtrip_permissions(self, runner, initialized_repo, tmp_path):
        """Tar then untar preserves executable bit."""
        f = tmp_path / "run.sh"
        f.write_text("#!/bin/sh")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":run.sh", "--type", "executable"])
        f2 = tmp_path / "data.txt"
        f2.write_text("plain")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":data.txt"])

        # Tar it
        archive = str(tmp_path / "archive.tar")
        runner.invoke(main, ["tar", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["untar", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(p2, create=False)
        fs = store.branches["main"]
        assert fs.file_type("run.sh") == FileType.EXECUTABLE
        assert fs.file_type("data.txt") == FileType.BLOB

    def test_untar_invalid_archive(self, runner, initialized_repo, tmp_path):
        bad = tmp_path / "notatar.bin"
        bad.write_bytes(b"this is not a tar")
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, str(bad)])
        assert result.exit_code != 0
        assert "Not a valid tar" in result.output

    def test_untar_empty_archive(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "empty.tar")
        with tarfile.open(tpath, "w") as tf:
            pass  # no files
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code != 0
        assert "no files" in result.output.lower()

    def test_untar_stdin(self, runner, initialized_repo, tmp_path):
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:") as tf:
            data = b"from stdin"
            info = tarfile.TarInfo(name="piped.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, "-"], input=buf.getvalue())
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":piped.txt"])
        assert "from stdin" in result.output

    def test_untar_gz(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "import.tar.gz")
        with tarfile.open(tpath, "w:gz") as tf:
            data = b"compressed"
            info = tarfile.TarInfo(name="comp.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":comp.txt"])
        assert "compressed" in result.output

    def test_untar_imports_symlink(self, runner, initialized_repo, tmp_path):
        """Symlinks in a tar are imported as symlinks in the repo."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            # regular file
            data = b"content"
            info = tarfile.TarInfo(name="target.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            # symlink
            info = tarfile.TarInfo(name="link.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "target.txt"
            tf.addfile(info)
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output

        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.file_type("link.txt") == FileType.LINK
        assert fs.readlink("link.txt") == "target.txt"

    def test_untar_roundtrip_symlinks(self, runner, initialized_repo, tmp_path):
        """Tar then untar preserves symlinks."""
        import tarfile
        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        fs = fs.write("target.txt", b"content")
        fs.write_symlink("link.txt", "target.txt")

        # Tar it
        archive = str(tmp_path / "archive.tar")
        runner.invoke(main, ["tar", "--repo", initialized_repo, archive])

        # Import into a fresh repo
        p2 = str(tmp_path / "repo2.git")
        runner.invoke(main, ["init", "--repo", p2])
        result = runner.invoke(main, ["untar", "--repo", p2, archive])
        assert result.exit_code == 0, result.output

        store2 = GitStore.open(p2, create=False)
        fs2 = store2.branches["main"]
        assert fs2.readlink("link.txt") == "target.txt"
        assert fs2.file_type("link.txt") == FileType.LINK
        assert fs2.file_type("target.txt") == FileType.BLOB

    def test_untar_leading_dot_slash(self, runner, initialized_repo, tmp_path):
        """Tar entries with leading ./ are accepted and normalized."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="./dir/file.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            data2 = b"top"
            info2 = tarfile.TarInfo(name="./top.txt")
            info2.size = len(data2)
            tf.addfile(info2, io.BytesIO(data2))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":dir/file.txt"])
        assert "hello" in result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":top.txt"])
        assert "top" in result.output

    def test_untar_hard_link(self, runner, initialized_repo, tmp_path):
        """Hard links in tar are materialized as regular files."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"shared content"
            info = tarfile.TarInfo(name="original.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            # Hard link pointing to original.txt
            link_info = tarfile.TarInfo(name="hardlink.txt")
            link_info.type = tarfile.LNKTYPE
            link_info.linkname = "original.txt"
            tf.addfile(link_info)
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":hardlink.txt"])
        assert result.exit_code == 0
        assert "shared content" in result.output

    def test_untar_hard_link_preserves_exec_from_target(self, runner, initialized_repo, tmp_path):
        """Hard link inherits executable bit from the original target member."""
        import tarfile
        tpath = str(tmp_path / "import.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"#!/bin/sh\necho hi"
            info = tarfile.TarInfo(name="script.sh")
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
            # Hard link with mode=0 (common in real tars)
            link_info = tarfile.TarInfo(name="link.sh")
            link_info.type = tarfile.LNKTYPE
            link_info.linkname = "script.sh"
            link_info.mode = 0
            tf.addfile(link_info)
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        from vost import GitStore
        from vost.copy._types import FileType
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        assert fs.file_type("link.sh") == FileType.EXECUTABLE

    def test_untar_hard_link_stdin_skip_warning(self, runner, initialized_repo, tmp_path):
        """Hard links that can't be resolved in streaming mode are skipped with a warning."""
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:") as tf:
            # Hard link BEFORE the target — unresolvable in streaming mode
            link_info = tarfile.TarInfo(name="link.txt")
            link_info.type = tarfile.LNKTYPE
            link_info.linkname = "original.txt"
            tf.addfile(link_info)
            data = b"content"
            info = tarfile.TarInfo(name="original.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["untar", "--repo", initialized_repo, "-"], input=buf.getvalue())
        assert result.exit_code == 0, result.output
        # The regular file should be imported
        result2 = runner.invoke(main, ["cat", "--repo", initialized_repo, ":original.txt"])
        assert result2.exit_code == 0
        assert "content" in result2.output
        # The hard link should NOT exist (skipped)
        result3 = runner.invoke(main, ["cat", "--repo", initialized_repo, ":link.txt"])
        assert result3.exit_code != 0


class TestArchiveOut:
    def test_archive_zip(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, ["archive_out", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "hello.txt" in names
            assert "data/data.bin" in names
            assert zf.read("hello.txt") == b"hello world\n"

    def test_archive_tar_gz(self, runner, repo_with_files, tmp_path):
        import tarfile
        out = str(tmp_path / "archive.tar.gz")
        result = runner.invoke(main, ["archive_out", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r:gz") as tf:
            names = tf.getnames()
            assert "hello.txt" in names
            assert "data/data.bin" in names

    def test_archive_format_override(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.dat")
        result = runner.invoke(main, [
            "archive_out", "--repo", repo_with_files, out, "--format", "zip"
        ])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            assert "hello.txt" in zf.namelist()

    def test_archive_stdout_requires_format(self, runner, repo_with_files):
        result = runner.invoke(main, ["archive_out", "--repo", repo_with_files, "-"])
        assert result.exit_code != 0
        assert "--format" in result.output

    def test_archive_unknown_extension(self, runner, repo_with_files, tmp_path):
        out = str(tmp_path / "archive.xyz")
        result = runner.invoke(main, ["archive_out", "--repo", repo_with_files, out])
        assert result.exit_code != 0
        assert "Cannot detect" in result.output

    def test_archive_stdout_with_format(self, runner, repo_with_files):
        result = runner.invoke(main, [
            "archive_out", "--repo", repo_with_files, "-", "--format", "zip"
        ])
        assert result.exit_code == 0
        zf = zipfile.ZipFile(io.BytesIO(result.output_bytes))
        assert "hello.txt" in zf.namelist()

    def test_archive_tar(self, runner, repo_with_files, tmp_path):
        import tarfile
        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, ["archive_out", "--repo", repo_with_files, out])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "hello.txt" in names


class TestArchiveIn:
    def test_unarchive_zip(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "data.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("file1.txt", "hello")
        result = runner.invoke(main, ["archive_in", "--repo", initialized_repo, zpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":file1.txt"])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_unarchive_tar(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "data.tar")
        with tarfile.open(tpath, "w") as tf:
            data = b"world"
            info = tarfile.TarInfo(name="file2.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, ["archive_in", "--repo", initialized_repo, tpath])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":file2.txt"])
        assert result.exit_code == 0
        assert "world" in result.output

    def test_unarchive_stdin_requires_format(self, runner, initialized_repo):
        result = runner.invoke(main, ["archive_in", "--repo", initialized_repo])
        assert result.exit_code != 0
        assert "--format" in result.output

    def test_unarchive_stdin_dash_requires_format(self, runner, initialized_repo):
        result = runner.invoke(main, ["archive_in", "--repo", initialized_repo, "-"])
        assert result.exit_code != 0
        assert "--format" in result.output

    def test_unarchive_format_override(self, runner, initialized_repo, tmp_path):
        import tarfile
        tpath = str(tmp_path / "data.bin")
        with tarfile.open(tpath, "w") as tf:
            data = b"content"
            info = tarfile.TarInfo(name="fromtar.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        result = runner.invoke(main, [
            "archive_in", "--repo", initialized_repo, tpath, "--format", "tar"
        ])
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":fromtar.txt"])
        assert result.exit_code == 0
        assert "content" in result.output

    def test_unarchive_unknown_extension(self, runner, initialized_repo, tmp_path):
        p = tmp_path / "data.xyz"
        p.write_bytes(b"not an archive")
        result = runner.invoke(main, [
            "archive_in", "--repo", initialized_repo, str(p)
        ])
        assert result.exit_code != 0
        assert "Cannot detect" in result.output

    def test_unarchive_zip_from_stdin(self, runner, initialized_repo):
        """unarchive --format zip - reads zip from stdin."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("stdin_file.txt", "from stdin")
        zip_bytes = buf.getvalue()

        result = runner.invoke(
            main,
            ["archive_in", "--repo", initialized_repo, "--format", "zip", "-"],
            input=zip_bytes,
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["cat", "--repo", initialized_repo, ":stdin_file.txt"])
        assert result.exit_code == 0
        assert "from stdin" in result.output

    def test_unarchive_custom_message(self, runner, initialized_repo, tmp_path):
        zpath = str(tmp_path / "data.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("msg.txt", "data")
        result = runner.invoke(main, [
            "archive_in", "--repo", initialized_repo, zpath, "-m", "bulk import"
        ])
        assert result.exit_code == 0
        result = runner.invoke(main, ["log", "--repo", initialized_repo])
        assert "bulk import" in result.output


class TestBefore:
    """Tests for the --before date filter."""

    def test_log_before(self, runner, initialized_repo, tmp_path):
        """--before excludes commits after the cutoff."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "first"])
        time.sleep(1.1)
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "second"])

        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        entries = list(fs.log())
        # cutoff = time of "first" commit (second entry, since log is newest-first)
        cutoff = entries[1].time

        result = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert "second" not in result.output
        assert "first" in result.output

    def test_log_before_date_only(self, runner, repo_with_files):
        """Date-only --before: 2099-01-01 includes all; 2000-01-01 includes none."""
        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--before", "2099-01-01"
        ])
        assert result.exit_code == 0
        all_lines = result.output.strip().split("\n")
        assert len(all_lines) >= 3  # init + hello.txt + data

        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--before", "2000-01-01"
        ])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_log_before_with_path(self, runner, initialized_repo, tmp_path):
        """--before and --path combined."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])

        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time  # time of "add a" commit

        time.sleep(1.1)
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "update a"])

        result = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--path", "a.txt", "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "add a" in lines[0]

    def test_log_before_with_match(self, runner, initialized_repo, tmp_path):
        """--before and --match combined."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v1"])

        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time

        time.sleep(1.1)
        f.write_text("v2")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "deploy v2"])

        result = runner.invoke(main, [
            "log", "--repo", initialized_repo,
            "--match", "deploy*", "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "deploy v1" in lines[0]

    def test_zip_before(self, runner, initialized_repo, tmp_path):
        """--before exports the correct snapshot."""
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])

        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time

        time.sleep(1.1)
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, [
            "zip", "--repo", initialized_repo, out, "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            assert "a.txt" in names
            assert "b.txt" not in names

    def test_tar_before(self, runner, initialized_repo, tmp_path):
        """--before exports the correct snapshot."""
        import tarfile
        f = tmp_path / "a.txt"
        f.write_text("v1")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f), ":a.txt", "-m", "add a"])

        from vost import GitStore
        store = GitStore.open(initialized_repo, create=False)
        fs = store.branches["main"]
        cutoff = fs.time

        time.sleep(1.1)
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        runner.invoke(main, ["cp", "--repo", initialized_repo, str(f2), ":b.txt", "-m", "add b"])

        out = str(tmp_path / "archive.tar")
        result = runner.invoke(main, [
            "tar", "--repo", initialized_repo, out, "--before", cutoff.isoformat()
        ])
        assert result.exit_code == 0, result.output
        with tarfile.open(out, "r") as tf:
            names = tf.getnames()
            assert "a.txt" in names
            assert "b.txt" not in names

    def test_before_invalid_date(self, runner, repo_with_files, tmp_path):
        """Invalid --before value produces a clear error."""
        result = runner.invoke(main, [
            "log", "--repo", repo_with_files, "--before", "not-a-date"
        ])
        assert result.exit_code != 0
        assert "Invalid date" in result.output

    def test_before_no_matching_commits(self, runner, repo_with_files, tmp_path):
        """--before with a very old date produces error for zip/tar."""
        out = str(tmp_path / "archive.zip")
        result = runner.invoke(main, [
            "zip", "--repo", repo_with_files, out, "--before", "2000-01-01"
        ])
        assert result.exit_code != 0
        assert "No matching commits" in result.output

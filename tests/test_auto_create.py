"""Tests for auto-create repo on write commands."""

import io
import os
import tarfile
import zipfile

import pytest
from click.testing import CliRunner

from gitstore.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def new_repo(tmp_path):
    """Return a path to a repo that does NOT exist yet."""
    return str(tmp_path / "auto.git")


# ---------------------------------------------------------------------------
# cp auto-creates
# ---------------------------------------------------------------------------

def test_cp_auto_creates_repo(runner, new_repo, tmp_path):
    src = tmp_path / "hello.txt"
    src.write_text("hello")
    r = runner.invoke(main, ["cp", "-r", new_repo, str(src), ":hello.txt"])
    assert r.exit_code == 0, r.output
    # Verify the file was written
    r = runner.invoke(main, ["cat", "-r", new_repo, ":hello.txt"])
    assert r.exit_code == 0
    assert r.output == "hello"


def test_cp_auto_create_uses_branch(runner, new_repo, tmp_path):
    src = tmp_path / "f.txt"
    src.write_text("data")
    r = runner.invoke(main, ["cp", "-r", new_repo, "-b", "dev", str(src), ":f.txt"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["cat", "-r", new_repo, "-b", "dev", ":f.txt"])
    assert r.exit_code == 0
    assert r.output == "data"


def test_cp_no_create_prevents_auto_create(runner, new_repo, tmp_path):
    src = tmp_path / "hello.txt"
    src.write_text("hello")
    r = runner.invoke(main, ["cp", "-r", new_repo, "--no-create", str(src), ":hello.txt"])
    assert r.exit_code != 0
    assert not os.path.exists(new_repo)


def test_cp_repo_to_disk_no_auto_create(runner, new_repo, tmp_path):
    """Read direction (repo→disk) should NOT auto-create."""
    dest = tmp_path / "out.txt"
    r = runner.invoke(main, ["cp", "-r", new_repo, ":hello.txt", str(dest)])
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# cptree auto-creates
# ---------------------------------------------------------------------------

def test_cptree_auto_creates_repo(runner, new_repo, tmp_path):
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "a.txt").write_text("aaa")
    r = runner.invoke(main, ["cptree", "-r", new_repo, str(d), ":stuff"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["cat", "-r", new_repo, ":stuff/a.txt"])
    assert r.exit_code == 0
    assert r.output == "aaa"


def test_cptree_no_create_prevents_auto_create(runner, new_repo, tmp_path):
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "a.txt").write_text("aaa")
    r = runner.invoke(main, ["cptree", "-r", new_repo, "--no-create", str(d), ":stuff"])
    assert r.exit_code != 0
    assert not os.path.exists(new_repo)


# ---------------------------------------------------------------------------
# unzip auto-creates
# ---------------------------------------------------------------------------

def test_unzip_auto_creates_repo(runner, new_repo, tmp_path):
    zpath = tmp_path / "data.zip"
    with zipfile.ZipFile(str(zpath), "w") as zf:
        zf.writestr("doc.txt", "zip content")
    r = runner.invoke(main, ["unzip", "-r", new_repo, str(zpath)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["cat", "-r", new_repo, ":doc.txt"])
    assert r.exit_code == 0
    assert r.output == "zip content"


def test_unzip_no_create_prevents_auto_create(runner, new_repo, tmp_path):
    zpath = tmp_path / "data.zip"
    with zipfile.ZipFile(str(zpath), "w") as zf:
        zf.writestr("doc.txt", "zip content")
    r = runner.invoke(main, ["unzip", "-r", new_repo, "--no-create", str(zpath)])
    assert r.exit_code != 0
    assert not os.path.exists(new_repo)


# ---------------------------------------------------------------------------
# untar auto-creates
# ---------------------------------------------------------------------------

def test_untar_auto_creates_repo(runner, new_repo, tmp_path):
    tpath = tmp_path / "data.tar"
    with tarfile.open(str(tpath), "w") as tf:
        data = b"tar content"
        info = tarfile.TarInfo(name="doc.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    r = runner.invoke(main, ["untar", "-r", new_repo, str(tpath)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["cat", "-r", new_repo, ":doc.txt"])
    assert r.exit_code == 0
    assert r.output == "tar content"


def test_untar_no_create_prevents_auto_create(runner, new_repo, tmp_path):
    tpath = tmp_path / "data.tar"
    with tarfile.open(str(tpath), "w") as tf:
        data = b"tar content"
        info = tarfile.TarInfo(name="doc.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    r = runner.invoke(main, ["untar", "-r", new_repo, "--no-create", str(tpath)])
    assert r.exit_code != 0
    assert not os.path.exists(new_repo)


# ---------------------------------------------------------------------------
# unarchive auto-creates
# ---------------------------------------------------------------------------

def test_unarchive_auto_creates_repo(runner, new_repo, tmp_path):
    zpath = tmp_path / "data.zip"
    with zipfile.ZipFile(str(zpath), "w") as zf:
        zf.writestr("arc.txt", "archive content")
    r = runner.invoke(main, ["unarchive", "-r", new_repo, str(zpath)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["cat", "-r", new_repo, ":arc.txt"])
    assert r.exit_code == 0
    assert r.output == "archive content"


def test_unarchive_no_create_prevents_auto_create(runner, new_repo, tmp_path):
    zpath = tmp_path / "data.zip"
    with zipfile.ZipFile(str(zpath), "w") as zf:
        zf.writestr("arc.txt", "archive content")
    r = runner.invoke(main, ["unarchive", "-r", new_repo, "--no-create", str(zpath)])
    assert r.exit_code != 0
    assert not os.path.exists(new_repo)


# ---------------------------------------------------------------------------
# Read commands still error on missing repo
# ---------------------------------------------------------------------------

def test_ls_errors_on_missing_repo(runner, new_repo):
    r = runner.invoke(main, ["ls", "-r", new_repo])
    assert r.exit_code != 0


def test_cat_errors_on_missing_repo(runner, new_repo):
    r = runner.invoke(main, ["cat", "-r", new_repo, ":file.txt"])
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# Auto-create on existing repo is a no-op (doesn't clobber)
# ---------------------------------------------------------------------------

def test_cp_existing_repo_not_recreated(runner, tmp_path):
    repo = str(tmp_path / "exist.git")
    r = runner.invoke(main, ["init", "-r", repo, "-b", "main"])
    assert r.exit_code == 0

    f1 = tmp_path / "a.txt"
    f1.write_text("first")
    r = runner.invoke(main, ["cp", "-r", repo, str(f1), ":a.txt"])
    assert r.exit_code == 0

    f2 = tmp_path / "b.txt"
    f2.write_text("second")
    r = runner.invoke(main, ["cp", "-r", repo, str(f2), ":b.txt"])
    assert r.exit_code == 0

    # Both files should exist
    r = runner.invoke(main, ["cat", "-r", repo, ":a.txt"])
    assert r.exit_code == 0 and r.output == "first"
    r = runner.invoke(main, ["cat", "-r", repo, ":b.txt"])
    assert r.exit_code == 0 and r.output == "second"

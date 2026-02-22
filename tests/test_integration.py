"""End-to-end integration test."""

from gitstore import GitStore


def test_full_workflow(tmp_path):
    repo = GitStore.open(
        tmp_path / "test.git", author="test", email="t@t.com"
    )
    fs = repo.branches["main"]
    fs = fs.write("hello.txt", b"Hello!")
    fs = fs.write("src/main.py", b"print('hi')")

    with fs.batch() as b:
        b.write("README.md", b"# Project")
        b.remove("hello.txt")
    fs = b.fs

    assert not fs.exists("hello.txt")
    assert fs.read("README.md") == b"# Project"
    assert fs.read("src/main.py") == b"print('hi')"
    assert len(list(fs.log())) == 4  # init + 2 writes + batch

    repo.branches["dev"] = fs
    repo.tags["v1"] = fs

    dev = repo.branches["dev"]
    dev = dev.write("dev.txt", b"dev only")
    assert not repo.branches["main"].exists("dev.txt")
    assert dev.exists("dev.txt")

    # Tag is read-only
    tag_fs = repo.tags["v1"]
    assert tag_fs.ref_name == "v1"
    assert not tag_fs.writable
    assert tag_fs.read("README.md") == b"# Project"

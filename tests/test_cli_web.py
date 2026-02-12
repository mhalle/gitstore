"""Tests for the gitstore serve command (WSGI app)."""

import json

import pytest
from click.testing import CliRunner

from gitstore.cli import main
from gitstore.cli._web import _make_app
from gitstore.repo import GitStore


# ---------------------------------------------------------------------------
# WSGI test helper
# ---------------------------------------------------------------------------

def _wsgi_get(app, path="/", accept=None):
    """Call the WSGI app with a GET request, return (status, headers, body)."""
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "HTTP_HOST": "localhost:8000",
        "wsgi.input": None,
        "wsgi.errors": None,
    }
    if accept:
        environ["HTTP_ACCEPT"] = accept

    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body_parts = app(environ, start_response)
    body = b"".join(body_parts)
    return captured["status"], captured["headers"], body


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store_with_files(tmp_path):
    """Store with files on 'main' and a tag."""
    store = GitStore.open(str(tmp_path / "test.git"), branch="main")
    fs = store.branches["main"]
    fs = fs.write("hello.txt", b"hello world\n")
    fs = fs.write("data/info.json", b'{"key": "value"}')
    fs = fs.write("data/image.png", b"\x89PNG\r\n\x1a\n")
    fs = fs.write("readme.md", b"# Readme\n")
    store.tags["v1"] = fs
    return store


@pytest.fixture
def store_with_branches(tmp_path):
    """Store with two branches and a tag."""
    store = GitStore.open(str(tmp_path / "test.git"), branch="main")
    fs = store.branches["main"]
    fs = fs.write("main-file.txt", b"on main")

    # Create a second branch
    repo = store._repo
    sig = store._signature
    tree_oid = repo.TreeBuilder().write()
    repo.create_commit(
        "refs/heads/dev",
        sig, sig,
        "Initialize dev",
        tree_oid,
        [],
    )
    fs_dev = store.branches["dev"]
    fs_dev = fs_dev.write("dev-file.txt", b"on dev")

    store.tags["v1"] = store.branches["main"]
    return store


@pytest.fixture
def store_with_symlink(tmp_path):
    """Store with a symlink."""
    store = GitStore.open(str(tmp_path / "test.git"), branch="main")
    fs = store.branches["main"]
    fs = fs.write("target.txt", b"target content")
    fs = fs.write_symlink("link.txt", "target.txt")
    return store


# ---------------------------------------------------------------------------
# Single-ref mode tests (default)
# ---------------------------------------------------------------------------

class TestSingleRefRoot:
    def test_root_html(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(app, "/")
        assert status == "200 OK"
        assert "text/html" in headers["Content-Type"]
        html = body.decode()
        assert "hello.txt" in html

    def test_root_json(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(app, "/", accept="application/json")
        assert status == "200 OK"
        data = json.loads(body)
        assert "hello.txt" in data["entries"]
        assert data["ref"] == "main"


class TestSingleRefFile:
    def test_text_file(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(app, "/hello.txt")
        assert status == "200 OK"
        assert body == b"hello world\n"
        assert "text/plain" in headers["Content-Type"]

    def test_nested_file(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, _, body = _wsgi_get(app, "/data/info.json")
        assert status == "200 OK"
        assert body == b'{"key": "value"}'

    def test_binary_file(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(app, "/data/image.png")
        assert status == "200 OK"
        assert body == b"\x89PNG\r\n\x1a\n"
        assert "image/png" in headers["Content-Type"]

    def test_file_json_metadata(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(
            app, "/hello.txt", accept="application/json"
        )
        assert status == "200 OK"
        data = json.loads(body)
        assert data["path"] == "hello.txt"
        assert data["ref"] == "main"
        assert data["size"] == len(b"hello world\n")
        assert data["type"] == "file"

    def test_serve_tag_snapshot(self, store_with_files):
        """Can serve a tag FS in single-ref mode."""
        fs = store_with_files.tags["v1"]
        app = _make_app(store_with_files, fs=fs, ref_label="v1")
        status, _, body = _wsgi_get(app, "/hello.txt")
        assert status == "200 OK"
        assert body == b"hello world\n"

    def test_serve_historical_snapshot(self, store_with_files):
        """Can serve an older snapshot via back()."""
        fs = store_with_files.branches["main"]
        old_fs = fs.back(1)  # before readme.md was added
        app = _make_app(store_with_files, fs=old_fs, ref_label="main")
        status, _, _ = _wsgi_get(app, "/readme.md")
        assert status == "404 Not Found"
        # But earlier files still present
        status, _, body = _wsgi_get(app, "/data/image.png")
        assert status == "200 OK"


class TestSingleRefDir:
    def test_dir_html(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(app, "/data")
        assert status == "200 OK"
        assert "text/html" in headers["Content-Type"]
        html = body.decode()
        assert "info.json" in html
        assert "image.png" in html

    def test_dir_json(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(
            app, "/data", accept="application/json"
        )
        assert status == "200 OK"
        data = json.loads(body)
        assert data["path"] == "data"
        assert data["ref"] == "main"
        assert data["type"] == "directory"
        assert "info.json" in data["entries"]
        assert "image.png" in data["entries"]


# ---------------------------------------------------------------------------
# Multi-ref mode tests (--all)
# ---------------------------------------------------------------------------

class TestMultiRefRoot:
    def test_root_html(self, store_with_files):
        app = _make_app(store_with_files)
        status, headers, body = _wsgi_get(app, "/")
        assert status == "200 OK"
        assert "text/html" in headers["Content-Type"]
        html = body.decode()
        assert "main" in html
        assert "v1" in html

    def test_root_json(self, store_with_files):
        app = _make_app(store_with_files)
        status, headers, body = _wsgi_get(app, "/", accept="application/json")
        assert status == "200 OK"
        data = json.loads(body)
        assert "main" in data["branches"]
        assert "v1" in data["tags"]


class TestMultiRefFile:
    def test_text_file(self, store_with_files):
        app = _make_app(store_with_files)
        status, headers, body = _wsgi_get(app, "/main/hello.txt")
        assert status == "200 OK"
        assert body == b"hello world\n"
        assert "text/plain" in headers["Content-Type"]

    def test_file_via_tag(self, store_with_files):
        app = _make_app(store_with_files)
        status, _, body = _wsgi_get(app, "/v1/hello.txt")
        assert status == "200 OK"
        assert body == b"hello world\n"

    def test_file_json_metadata(self, store_with_files):
        app = _make_app(store_with_files)
        status, _, body = _wsgi_get(
            app, "/main/hello.txt", accept="application/json"
        )
        data = json.loads(body)
        assert data["ref"] == "main"
        assert data["type"] == "file"


class TestMultiRefDir:
    def test_dir_html(self, store_with_files):
        app = _make_app(store_with_files)
        status, headers, body = _wsgi_get(app, "/main/data")
        assert status == "200 OK"
        assert "text/html" in headers["Content-Type"]
        html = body.decode()
        assert "info.json" in html

    def test_dir_json(self, store_with_files):
        app = _make_app(store_with_files)
        status, _, body = _wsgi_get(
            app, "/main/data", accept="application/json"
        )
        data = json.loads(body)
        assert data["type"] == "directory"
        assert "info.json" in data["entries"]

    def test_root_dir_listing(self, store_with_files):
        app = _make_app(store_with_files)
        status, _, body = _wsgi_get(app, "/main/")
        assert status == "200 OK"
        html = body.decode()
        assert "hello.txt" in html

    def test_root_dir_json(self, store_with_files):
        app = _make_app(store_with_files)
        status, _, body = _wsgi_get(
            app, "/main/", accept="application/json"
        )
        data = json.loads(body)
        assert data["ref"] == "main"
        assert "hello.txt" in data["entries"]


class TestMultiRefBranches:
    def test_different_branches(self, store_with_branches):
        app = _make_app(store_with_branches)

        status, _, body = _wsgi_get(app, "/main/main-file.txt")
        assert status == "200 OK"
        assert body == b"on main"

        status, _, body = _wsgi_get(app, "/dev/dev-file.txt")
        assert status == "200 OK"
        assert body == b"on dev"


# ---------------------------------------------------------------------------
# 404 tests
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_missing_ref_multi(self, store_with_files):
        app = _make_app(store_with_files)
        status, _, _ = _wsgi_get(app, "/nonexistent/file.txt")
        assert status == "404 Not Found"

    def test_missing_path_multi(self, store_with_files):
        app = _make_app(store_with_files)
        status, _, _ = _wsgi_get(app, "/main/nonexistent.txt")
        assert status == "404 Not Found"

    def test_missing_path_single(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, _, _ = _wsgi_get(app, "/nonexistent.txt")
        assert status == "404 Not Found"


# ---------------------------------------------------------------------------
# Symlink handling
# ---------------------------------------------------------------------------

class TestSymlinks:
    def test_symlink_served_as_file(self, store_with_symlink):
        """Symlinks should serve the blob content (the link target string)."""
        fs = store_with_symlink.branches["main"]
        app = _make_app(store_with_symlink, fs=fs, ref_label="main")
        status, _, body = _wsgi_get(app, "/link.txt")
        assert status == "200 OK"
        assert body == b"target.txt"


# ---------------------------------------------------------------------------
# MIME type fallback
# ---------------------------------------------------------------------------

class TestMimeTypes:
    def test_unknown_extension(self, tmp_path):
        store = GitStore.open(str(tmp_path / "test.git"), branch="main")
        fs = store.branches["main"]
        fs.write("data.xyz123", b"some data")
        fs = store.branches["main"]
        app = _make_app(store, fs=fs, ref_label="main")
        status, headers, _ = _wsgi_get(app, "/data.xyz123")
        assert status == "200 OK"
        assert headers["Content-Type"] == "application/octet-stream"

    def test_markdown_type(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, _ = _wsgi_get(app, "/readme.md")
        assert status == "200 OK"
        # Markdown may be text/markdown or text/x-markdown depending on platform
        assert "text/" in headers["Content-Type"]


# ---------------------------------------------------------------------------
# CLI command registration
# ---------------------------------------------------------------------------

class TestServeCommand:
    def test_serve_registered(self):
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "Serve repository files" in result.output
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--branch" in result.output
        assert "--ref" in result.output
        assert "--back" in result.output
        assert "--all" in result.output

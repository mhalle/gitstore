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

def _wsgi_get(app, path="/", accept=None, method="GET"):
    """Call the WSGI app with a request, return (status, headers, body)."""
    environ = {
        "REQUEST_METHOD": method,
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
# Single-ref link correctness
# ---------------------------------------------------------------------------

class TestSingleRefLinks:
    """In single-ref mode, HTML links must NOT include the ref prefix."""

    def test_root_links_no_ref_prefix(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, _, body = _wsgi_get(app, "/")
        html = body.decode()
        # Links should be /hello.txt, not /main/hello.txt
        assert 'href="/hello.txt"' in html
        assert 'href="/data"' in html
        assert 'href="/main/' not in html

    def test_subdir_links_no_ref_prefix(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, _, body = _wsgi_get(app, "/data")
        html = body.decode()
        # Links should be /data/info.json, not /main/data/info.json
        assert 'href="/data/info.json"' in html
        assert 'href="/main/' not in html


# ---------------------------------------------------------------------------
# Multi-ref link correctness
# ---------------------------------------------------------------------------

class TestMultiRefLinks:
    """In multi-ref mode, HTML links MUST include the ref prefix."""

    def test_root_dir_links_include_ref(self, store_with_files):
        app = _make_app(store_with_files)
        _, _, body = _wsgi_get(app, "/main/")
        html = body.decode()
        assert 'href="/main/hello.txt"' in html
        assert 'href="/main/data"' in html

    def test_subdir_links_include_ref(self, store_with_files):
        app = _make_app(store_with_files)
        _, _, body = _wsgi_get(app, "/main/data")
        html = body.decode()
        assert 'href="/main/data/info.json"' in html


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
# ETag tests
# ---------------------------------------------------------------------------

class TestETag:
    def test_file_has_etag(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/hello.txt")
        assert "ETag" in headers
        assert headers["ETag"] == f'"{fs.hash}"'

    def test_dir_has_etag(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/data")
        assert "ETag" in headers
        assert headers["ETag"] == f'"{fs.hash}"'

    def test_json_has_etag(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/hello.txt", accept="application/json")
        assert "ETag" in headers
        assert headers["ETag"] == f'"{fs.hash}"'

    def test_root_has_etag(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/")
        assert "ETag" in headers

    def test_multi_ref_file_has_etag(self, store_with_files):
        app = _make_app(store_with_files)
        _, headers, _ = _wsgi_get(app, "/main/hello.txt")
        assert "ETag" in headers
        fs = store_with_files.branches["main"]
        assert headers["ETag"] == f'"{fs.hash}"'

    def test_different_snapshots_different_etags(self, store_with_files):
        fs = store_with_files.branches["main"]
        old_fs = fs.back(1)
        app_new = _make_app(store_with_files, fs=fs, ref_label="main")
        app_old = _make_app(store_with_files, fs=old_fs, ref_label="main")
        _, h_new, _ = _wsgi_get(app_new, "/hello.txt")
        _, h_old, _ = _wsgi_get(app_old, "/hello.txt")
        assert h_new["ETag"] != h_old["ETag"]

    def test_404_has_no_etag(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/nonexistent.txt")
        assert "ETag" not in headers


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

    def test_json_served_as_text(self, store_with_files):
        """JSON files should display inline, not trigger download."""
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        status, headers, body = _wsgi_get(app, "/data/info.json")
        assert status == "200 OK"
        assert headers["Content-Type"] == "text/plain; charset=utf-8"
        assert body == b'{"key": "value"}'

    def test_xml_served_as_text(self, tmp_path):
        store = GitStore.open(str(tmp_path / "test.git"), branch="main")
        fs = store.branches["main"]
        fs.write("data.xml", b"<root/>")
        fs = store.branches["main"]
        app = _make_app(store, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/data.xml")
        assert headers["Content-Type"] == "text/xml; charset=utf-8"

    def test_geojson_served_as_text(self, tmp_path):
        store = GitStore.open(str(tmp_path / "test.git"), branch="main")
        fs = store.branches["main"]
        fs.write("map.geojson", b'{"type":"Feature"}')
        fs = store.branches["main"]
        app = _make_app(store, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/map.geojson")
        assert headers["Content-Type"] == "text/plain; charset=utf-8"


# ---------------------------------------------------------------------------
# CORS tests
# ---------------------------------------------------------------------------

class TestCORS:
    def test_cors_disabled_by_default(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/hello.txt")
        assert "Access-Control-Allow-Origin" not in headers

    def test_cors_adds_headers(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main", cors=True)
        _, headers, _ = _wsgi_get(app, "/hello.txt")
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert "GET" in headers["Access-Control-Allow-Methods"]
        assert "ETag" in headers["Access-Control-Expose-Headers"]

    def test_cors_on_json_response(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main", cors=True)
        _, headers, _ = _wsgi_get(app, "/", accept="application/json")
        assert headers["Access-Control-Allow-Origin"] == "*"

    def test_cors_on_404(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main", cors=True)
        status, headers, _ = _wsgi_get(app, "/nonexistent.txt")
        assert status == "404 Not Found"
        assert headers["Access-Control-Allow-Origin"] == "*"

    def test_cors_options_preflight(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main", cors=True)
        status, headers, body = _wsgi_get(app, "/hello.txt", method="OPTIONS")
        assert status == "204 No Content"
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert body == b""

    def test_cors_multi_ref(self, store_with_files):
        app = _make_app(store_with_files, cors=True)
        _, headers, _ = _wsgi_get(app, "/main/hello.txt")
        assert headers["Access-Control-Allow-Origin"] == "*"


# ---------------------------------------------------------------------------
# No-cache tests
# ---------------------------------------------------------------------------

class TestNoCache:
    def test_no_cache_disabled_by_default(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main")
        _, headers, _ = _wsgi_get(app, "/hello.txt")
        assert "Cache-Control" not in headers

    def test_no_cache_adds_header(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main", no_cache=True)
        _, headers, _ = _wsgi_get(app, "/hello.txt")
        assert headers["Cache-Control"] == "no-store"

    def test_no_cache_on_dir(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main", no_cache=True)
        _, headers, _ = _wsgi_get(app, "/data")
        assert headers["Cache-Control"] == "no-store"

    def test_no_cache_on_404(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main", no_cache=True)
        status, headers, _ = _wsgi_get(app, "/nonexistent.txt")
        assert status == "404 Not Found"
        assert headers["Cache-Control"] == "no-store"

    def test_no_cache_combined_with_cors(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main",
                        cors=True, no_cache=True)
        _, headers, _ = _wsgi_get(app, "/hello.txt")
        assert headers["Cache-Control"] == "no-store"
        assert headers["Access-Control-Allow-Origin"] == "*"


# ---------------------------------------------------------------------------
# Base-path tests
# ---------------------------------------------------------------------------

class TestBasePath:
    def test_base_path_file(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main",
                        base_path="/data")
        status, _, body = _wsgi_get(app, "/data/hello.txt")
        assert status == "200 OK"
        assert body == b"hello world\n"

    def test_base_path_root(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main",
                        base_path="/data")
        status, headers, body = _wsgi_get(app, "/data/")
        assert status == "200 OK"
        assert "text/html" in headers["Content-Type"]
        html = body.decode()
        assert "hello.txt" in html

    def test_base_path_404_outside_prefix(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main",
                        base_path="/data")
        status, _, _ = _wsgi_get(app, "/hello.txt")
        assert status == "404 Not Found"

    def test_base_path_links_include_prefix(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main",
                        base_path="/data")
        _, _, body = _wsgi_get(app, "/data/")
        html = body.decode()
        assert 'href="/data/hello.txt"' in html

    def test_base_path_multi_ref(self, store_with_files):
        app = _make_app(store_with_files, base_path="/data")
        status, _, body = _wsgi_get(app, "/data/main/hello.txt")
        assert status == "200 OK"
        assert body == b"hello world\n"

    def test_base_path_multi_ref_root(self, store_with_files):
        app = _make_app(store_with_files, base_path="/data")
        status, headers, body = _wsgi_get(app, "/data/")
        assert status == "200 OK"
        assert "text/html" in headers["Content-Type"]
        html = body.decode()
        assert "main" in html

    def test_base_path_combined_with_cors(self, store_with_files):
        fs = store_with_files.branches["main"]
        app = _make_app(store_with_files, fs=fs, ref_label="main",
                        base_path="/data", cors=True)
        _, headers, _ = _wsgi_get(app, "/data/hello.txt")
        assert headers["Access-Control-Allow-Origin"] == "*"


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
        assert "--cors" in result.output
        assert "--no-cache" in result.output
        assert "--base-path" in result.output
        assert "--open" in result.output
        assert "--quiet" in result.output

"""Tests for the gitserve command."""

import io
import subprocess
import threading

import pytest
from click.testing import CliRunner

from gitstore.cli import main
from gitstore.repo import GitStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def repo_with_file(tmp_path):
    """Create a repo with one file and return its path."""
    p = str(tmp_path / "test.git")
    store = GitStore.open(p, branch="main")
    fs = store.branches["main"]
    fs.write("hello.txt", b"hello world\n")
    return p


def _make_app(repo_path):
    """Build the WSGI app the same way gitserve does."""
    from dulwich.server import DictBackend, UploadPackHandler
    from dulwich.web import HTTPGitApplication, GunzipFilter, LimitedInputFilter
    from gitstore.cli._serve import _fix_head

    store = GitStore.open(repo_path, create=False)
    _fix_head(store)
    dulwich_repo = store._repo._drepo
    backend = DictBackend({"/": dulwich_repo})
    git_app = HTTPGitApplication(backend)
    git_app.handlers = {b"git-upload-pack": UploadPackHandler}
    return LimitedInputFilter(GunzipFilter(git_app))


# ---------------------------------------------------------------------------
# WSGI unit tests (no network)
# ---------------------------------------------------------------------------

class TestWSGI:
    def _call(self, app, method, path, query="", content_type=""):
        """Invoke the WSGI app and return (status, body)."""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_TYPE": content_type,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "8000",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(b""),
            "wsgi.errors": io.BytesIO(),
        }
        status_holder = {}
        body_chunks = []

        def start_response(status, headers, exc_info=None):
            status_holder["status"] = status
            return body_chunks.append

        result = app(environ, start_response)
        body = b"".join(result)
        return status_holder["status"], body

    def test_info_refs_upload_pack(self, repo_with_file):
        app = _make_app(repo_with_file)
        status, body = self._call(
            app, "GET", "/info/refs",
            query="service=git-upload-pack",
        )
        assert status.startswith("200"), f"Expected 200, got {status}"

    def test_info_refs_receive_pack_forbidden(self, repo_with_file):
        app = _make_app(repo_with_file)
        status, body = self._call(
            app, "GET", "/info/refs",
            query="service=git-receive-pack",
        )
        assert status.startswith("403"), f"Expected 403, got {status}"

    def test_receive_pack_post_forbidden(self, repo_with_file):
        app = _make_app(repo_with_file)
        status, body = self._call(
            app, "POST", "/git-receive-pack",
            content_type="application/x-git-receive-pack-request",
        )
        assert status.startswith("403"), f"Expected 403, got {status}"


# ---------------------------------------------------------------------------
# CLI tests (CliRunner, no server)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_missing_repo(self, runner):
        result = runner.invoke(main, ["gitserve"])
        assert result.exit_code != 0
        assert "No repository specified" in result.output

    def test_nonexistent_repo(self, runner, tmp_path):
        result = runner.invoke(main, ["gitserve", "--repo", str(tmp_path / "nope.git")])
        assert result.exit_code != 0

    def test_help(self, runner):
        result = runner.invoke(main, ["gitserve", "--help"])
        assert result.exit_code == 0
        assert "read-only" in result.output.lower() or "Serve" in result.output


# ---------------------------------------------------------------------------
# Integration test (real HTTP)
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_clone_via_http(self, repo_with_file, tmp_path):
        from wsgiref.simple_server import make_server, WSGIRequestHandler

        app = _make_app(repo_with_file)

        class _Silent(WSGIRequestHandler):
            def log_message(self, format, *args):
                pass

        server = make_server("127.0.0.1", 0, app, handler_class=_Silent)
        port = server.server_port

        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        clone_dest = str(tmp_path / "cloned")
        try:
            result = subprocess.run(
                ["git", "clone", f"http://127.0.0.1:{port}/", clone_dest],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, (
                f"git clone failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
            hello = (tmp_path / "cloned" / "hello.txt").read_text()
            assert hello == "hello world\n"
        finally:
            server.shutdown()

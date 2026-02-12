"""serve — HTTP file server for repo contents."""

from __future__ import annotations

import json
import mimetypes

import click

from ._helpers import (
    main,
    _repo_option,
    _branch_option,
    _snapshot_options,
    _require_repo,
    _open_store,
    _default_branch,
    _resolve_fs,
)


def _make_app(store, *, fs=None, ref_label=None):
    """Return a WSGI application serving *store* contents over HTTP.

    If *fs* is given, operate in single-ref mode (all URLs are repo paths
    within that snapshot).  Otherwise, multi-ref mode: first URL segment
    selects the branch or tag.

    *ref_label* is the display name shown in JSON responses for single-ref
    mode (e.g. the branch name).
    """

    def app(environ, start_response):
        path_info = environ.get("PATH_INFO", "/")
        path = path_info.strip("/")
        accept = environ.get("HTTP_ACCEPT", "")
        want_json = "application/json" in accept

        if fs is not None:
            # --- Single-ref mode ---
            return _serve_path(start_response, fs, ref_label or "", path, want_json)
        else:
            # --- Multi-ref mode ---
            if not path:
                return _serve_ref_listing(start_response, store, want_json)

            # First segment is the ref
            parts = path.split("/", 1)
            ref_name = parts[0]
            rest = parts[1] if len(parts) > 1 else ""

            # Resolve ref: branches first, then tags
            if ref_name not in store.branches and ref_name not in store.tags:
                return _send_404(start_response, f"Unknown ref: {ref_name}")

            resolved = _resolve_fs_for_ref(store, ref_name)
            return _serve_path(start_response, resolved, ref_name, rest, want_json)

    return app


def _resolve_fs_for_ref(store, ref_name):
    """Resolve a ref name to an FS, trying branches then tags."""
    if ref_name in store.branches:
        return store.branches[ref_name]
    return store.tags[ref_name]


def _serve_ref_listing(start_response, store, want_json):
    """Serve the list of branches and tags."""
    branches = sorted(store.branches)
    tags = sorted(store.tags)

    if want_json:
        body = json.dumps({"branches": branches, "tags": tags}).encode()
        start_response("200 OK", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    # HTML listing
    lines = ["<html><body>", "<h1>Branches</h1>", "<ul>"]
    for b in branches:
        lines.append(f'<li><a href="/{b}/">{b}</a></li>')
    lines.append("</ul>")
    lines.append("<h1>Tags</h1>")
    lines.append("<ul>")
    for t in tags:
        lines.append(f'<li><a href="/{t}/">{t}</a></li>')
    lines.append("</ul>")
    lines.append("</body></html>")
    body = "\n".join(lines).encode()
    start_response("200 OK", [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ])
    return [body]


def _serve_path(start_response, fs, ref_label, path, want_json):
    """Serve a file or directory listing within a resolved FS."""
    if not path:
        return _serve_dir(start_response, fs, ref_label, "", want_json)

    if not fs.exists(path):
        return _send_404(start_response, f"Not found: {path}")

    if fs.is_dir(path):
        return _serve_dir(start_response, fs, ref_label, path, want_json)

    return _serve_file(start_response, fs, ref_label, path, want_json)


def _serve_file(start_response, fs, ref_label, path, want_json):
    """Serve file contents or JSON metadata."""
    data = fs.read(path)

    if want_json:
        body = json.dumps({
            "path": path,
            "ref": ref_label,
            "size": len(data),
            "type": "file",
        }).encode()
        start_response("200 OK", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    mime, _ = mimetypes.guess_type(path)
    if mime is None:
        mime = "application/octet-stream"

    start_response("200 OK", [
        ("Content-Type", mime),
        ("Content-Length", str(len(data))),
    ])
    return [data]


def _serve_dir(start_response, fs, ref_label, path, want_json):
    """Serve directory listing as JSON or HTML."""
    entries = fs.ls(path if path else None)

    if want_json:
        body = json.dumps({
            "path": path,
            "ref": ref_label,
            "entries": sorted(entries),
            "type": "directory",
        }).encode()
        start_response("200 OK", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    # HTML listing — in single-ref mode links are just /<path>,
    # in multi-ref mode they include /<ref>/<path>.
    display_path = path or "/"
    lines = ["<html><body>", f"<h1>{display_path}</h1>", "<ul>"]
    for entry in sorted(entries):
        if ref_label:
            href = f"/{ref_label}/{path}/{entry}" if path else f"/{ref_label}/{entry}"
        else:
            href = f"/{path}/{entry}" if path else f"/{entry}"
        lines.append(f'<li><a href="{href}">{entry}</a></li>')
    lines.append("</ul>")
    lines.append("</body></html>")
    body = "\n".join(lines).encode()
    start_response("200 OK", [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ])
    return [body]


def _send_404(start_response, message="Not found"):
    """Send a 404 response."""
    body = message.encode()
    start_response("404 Not Found", [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(len(body))),
    ])
    return [body]


@main.command()
@_repo_option
@click.option("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
@click.option("--port", "-p", default=8000, type=int,
              help="Port to listen on (default: 8000, use 0 for OS-assigned).")
@_branch_option
@_snapshot_options
@click.option("--all", "all_refs", is_flag=True, default=False,
              help="Multi-ref mode: expose all branches and tags via /<ref>/<path>.")
@click.pass_context
def serve(ctx, host, port, branch, ref, at_path, match_pattern, before, back, all_refs):
    """Serve repository files over HTTP.

    By default, serves the current branch at /<path>.  Use --ref, --back,
    --before, etc. to pin a specific snapshot.  Use --all to expose every
    branch and tag via /<ref>/<path>.

    \b
    Examples:
        gitstore serve -r data.git
        gitstore serve -r data.git -b dev
        gitstore serve -r data.git --ref v1.0
        gitstore serve -r data.git --back 3
        gitstore serve -r data.git --all
        gitstore serve -r data.git --all -p 9000
    """
    from wsgiref.simple_server import make_server, WSGIRequestHandler

    store = _open_store(_require_repo(ctx))

    if all_refs:
        if ref or at_path or match_pattern or before or back:
            raise click.ClickException(
                "--all cannot be combined with --ref, --path, --match, --before, or --back"
            )
        app = _make_app(store)
        mode = "multi-ref"
    else:
        branch = branch or _default_branch(store)
        fs = _resolve_fs(store, branch, ref,
                         at_path=at_path, match_pattern=match_pattern,
                         before=before, back=back)
        ref_label = ref or branch
        app = _make_app(store, fs=fs, ref_label=ref_label)
        mode = f"ref {ref_label}"
        if back:
            mode += f" ~{back}"

    class _QuietHandler(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            click.echo(
                f"{self.client_address[0]} - {self.command} {self.path} {code}",
                err=True,
            )

    server = make_server(host, port, app, handler_class=_QuietHandler)
    url = f"http://{host}:{server.server_port}/"
    click.echo(f"Serving {_require_repo(ctx)} ({mode}) at {url}", err=True)
    click.echo("Press Ctrl+C to stop.", err=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.", err=True)
    finally:
        server.server_close()

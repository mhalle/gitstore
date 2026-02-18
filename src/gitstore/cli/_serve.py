"""gitserve — read-only HTTP git server."""

from __future__ import annotations

import click

from ._helpers import main, _repo_option, _require_repo, _open_store


def _fix_head(store):
    """Point HEAD at an existing branch if it currently dangles.

    Uses the Repository helpers from _compat.  This is a safety net for
    pre-existing repos whose HEAD was never set properly.
    """
    if store._repo.get_head_branch() is not None:
        return  # HEAD already resolves
    # Pick the first branch alphabetically
    for name in sorted(store.branches):
        store._repo.set_head_branch(name)
        return


@main.command()
@_repo_option
@click.option("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
@click.option("--port", "-p", default=8000, type=int,
              help="Port to listen on (default: 8000, use 0 for OS-assigned).")
@click.pass_context
def gitserve(ctx, host, port):
    """Serve the repository read-only over HTTP.

    Standard git clients can clone/fetch from the URL. Pushes are rejected.

    \b
    Examples:
        gitstore gitserve -r data.git
        gitstore gitserve -r data.git -p 9000
        git clone http://127.0.0.1:8000/
    """
    from dulwich.server import DictBackend, UploadPackHandler
    from dulwich.web import HTTPGitApplication, GunzipFilter, LimitedInputFilter
    from wsgiref.simple_server import make_server, WSGIRequestHandler

    store = _open_store(_require_repo(ctx))

    # Ensure HEAD points to an existing branch so git clone checks out files.
    _fix_head(store)

    dulwich_repo = store._repo._drepo
    backend = DictBackend({"/": dulwich_repo})
    git_app = HTTPGitApplication(backend)
    # Replace default handlers — only allow git-upload-pack (clone/fetch).
    # Omitting git-receive-pack makes pushes return 403.
    git_app.handlers = {b"git-upload-pack": UploadPackHandler}
    app = LimitedInputFilter(GunzipFilter(git_app))

    class _QuietHandler(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            click.echo(
                f"{self.client_address[0]} - {self.command} {self.path} {code}",
                err=True,
            )

    server = make_server(host, port, app, handler_class=_QuietHandler)
    url = f"http://{host}:{server.server_port}/"
    click.echo(f"Serving {_require_repo(ctx)} at {url}", err=True)
    click.echo("Press Ctrl+C to stop.", err=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.", err=True)
    finally:
        server.server_close()

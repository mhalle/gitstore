"""gitstore CLI — copy files into/out of bare git repos."""

from ._helpers import main  # noqa: F401 — entry point

# Import command modules to register Click commands with the main group.
from . import _basic, _cp, _sync, _refs, _archive, _mirror, _serve, _web  # noqa: F401

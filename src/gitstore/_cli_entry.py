"""Thin wrapper so the console script gives a clear error when click is missing."""

import sys


def main():
    try:
        from .cli import main as cli_main
    except ImportError:
        print(
            "Error: the gitstore CLI requires the 'cli' extra.\n"
            "Install it with:  pip install gitstore[cli]",
            file=sys.stderr,
        )
        raise SystemExit(1)
    cli_main()

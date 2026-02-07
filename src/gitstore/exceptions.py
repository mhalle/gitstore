"""Exceptions for gitstore."""


class StaleSnapshotError(Exception):
    """Raised when a commit is attempted on a snapshot whose branch has advanced."""

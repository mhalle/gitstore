"""Exceptions for gitstore."""


class StaleSnapshotError(Exception):
    """Raised when a write is attempted on a snapshot whose branch has advanced.

    Re-fetch the branch via ``store.branches["name"]`` and retry, or use
    :func:`~gitstore.retry_write` for automatic retry with backoff.
    """

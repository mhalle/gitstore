"""Advisory repo lock: serializes ref mutations across threads and processes."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager

# Per-process threading locks, keyed by resolved repo path
_thread_locks: dict[tuple[int, int] | str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


def _get_thread_lock(repo_path: str) -> threading.Lock:
    real = os.path.realpath(repo_path)
    try:
        st = os.stat(real)
        key: tuple[int, int] | str = (st.st_dev, st.st_ino)
        if st.st_ino == 0:
            key = os.path.normcase(real)
    except OSError:
        key = os.path.normcase(real)
    with _thread_locks_guard:
        if key not in _thread_locks:
            _thread_locks[key] = threading.Lock()
        return _thread_locks[key]


try:
    import fcntl

    def _lock_path(repo_path: str) -> str:
        if os.path.isdir(repo_path):
            return os.path.join(repo_path, "vost.lock")
        return repo_path + ".lock"

    @contextmanager
    def repo_lock(repo_path: str):
        tlock = _get_thread_lock(repo_path)
        tlock.acquire()
        try:
            lock_path = _lock_path(repo_path)
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        finally:
            tlock.release()

except ImportError:
    import msvcrt

    def _lock_path(repo_path: str) -> str:
        if os.path.isdir(repo_path):
            return os.path.join(repo_path, "vost.lock")
        return repo_path + ".lock"

    @contextmanager
    def repo_lock(repo_path: str):
        tlock = _get_thread_lock(repo_path)
        tlock.acquire()
        try:
            lock_path = _lock_path(repo_path)
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
            os.set_inheritable(fd, False)
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                yield
            finally:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                os.close(fd)
        finally:
            tlock.release()

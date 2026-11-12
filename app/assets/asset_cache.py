"""Disposable render files: explicit idle timestamps and concurrent-reader leases."""

import os
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import ParamSpec, TypeVar

_lock = RLock()
_readers = 0
P = ParamSpec("P")
T = TypeVar("T")


@contextmanager
def cache_use() -> Generator[None]:
    global _readers
    with _lock:
        _readers += 1
    try:
        yield
    finally:
        with _lock:
            _readers -= 1


def using_cache(function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with cache_use():
            return function(*args, **kwargs)

    return wrapped


def touch(path: Path) -> None:
    # mtime is deliberately the last cache access, independent of filesystem atime policy.
    os.utime(path, None)


def expire(root: Path, idle_seconds: float, *, now: float | None = None) -> int:
    cutoff = (time.time() if now is None else now) - idle_seconds
    removed = 0
    with _lock:
        if _readers:
            return 0
        for path in root.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except FileNotFoundError:
                # Content retention may have purged this cache entry concurrently.
                continue
    return removed

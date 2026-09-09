"""Narrow cross-platform file lock for durable lot/journal writes.

Not a database. Compatible with GitHub Actions Windows and Linux.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import IO


class CrashInjected(RuntimeError):
    """Test hook: simulated process death before durable commit."""


class StaleGeneration(PermissionError):
    """CAS failure: a newer store generation already exists."""


class FileLock:
    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self._fh: IO[bytes] | None = None
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+b")
        deadline = time.time() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._fh.seek(0)
                    if self._fh.read(1) == b"":
                        self._fh.write(b"\0")
                        self._fh.flush()
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._acquired = True
                return
            except OSError:
                if time.time() >= deadline:
                    raise TimeoutError(f"lock timeout: {self.path}")
                time.sleep(0.02)

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if self._acquired:
                if os.name == "nt":
                    import msvcrt

                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._acquired = False
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

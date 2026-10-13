"""A small cross-process file lock, shared by the task list and the points ledger.

The server and the worker are separate processes that both write the same JSON files; whoever holds
the lock file for a moment is the only one writing.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable


class Busy(Exception):
    """The lock stayed taken for about ten seconds."""


@contextmanager
def locked(lock_path: Path, error: Callable[[], Exception] | None = None):
    """Hold an exclusive lock on `lock_path` (created if missing). If it can't be taken within about ten
    seconds, raise error() (default: Busy)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+")
    try:
        for _ in range(200):                     # up to ~10 s
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise (error() if error else Busy("the file is busy, try again"))
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        f.close()                                # also releases flock

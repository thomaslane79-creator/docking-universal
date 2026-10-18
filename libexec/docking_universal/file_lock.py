"""Exclusive process locks on Unix and native Windows, never a no-op fallback."""
from __future__ import annotations

import errno
import os
import time

try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None


def acquire(handle, *, blocking=True):
    if os.name == 'nt':
        if msvcrt is None:
            raise RuntimeError('Native Windows process locking is unavailable')
        # The CRT supports locking beyond EOF. Lock a stable byte at offset zero
        # without writing/truncating a competing owner's metadata beforehand.
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if not blocking:
                    raise BlockingIOError(exc.errno, 'Workspace lock is already owned') from exc
                time.sleep(.025)
    elif fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    else:
        raise RuntimeError('Exclusive process locking is unavailable on this platform')


def release(handle):
    handle.flush()
    if os.name == 'nt':
        if msvcrt is None:
            raise RuntimeError('Native Windows process locking is unavailable')
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    else:
        raise RuntimeError('Exclusive process locking is unavailable on this platform')

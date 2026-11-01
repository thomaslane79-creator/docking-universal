"""Read native macOS process-group state without spawning another process.

Darwin killpg excludes zombies and can return EPERM for a zombie-only group.
Only a complete, successful libproc inspection can establish that it is dead.
"""
from __future__ import annotations

import ctypes
import errno


class _BsdShortInfo(ctypes.Structure):
    # Public proc_bsdshortinfo from Apple's sys/proc_info.h (64 bytes).
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'pid', 'ppid', 'pgid', 'status')] + [('comm', ctypes.c_char * 16)] + [
        (name, ctypes.c_uint32) for name in (
            'flags', 'uid', 'gid', 'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]


def group_has_live_processes(group_id: int, *, library=None) -> bool:
    """Return False only for an absent or entirely zombie process group.

    Access errors, truncated snapshots and unknown process records raise;
    callers must preserve the original signalling error in those cases.
    """
    if not 1 < group_id < 2 ** 31:
        raise ValueError('A specific owned process group is required')
    if library is None:
        library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        library.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        library.proc_listpids.restype = ctypes.c_int
        library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        library.proc_pidinfo.restype = ctypes.c_int

    def checked_size(size):
        error = ctypes.get_errno()
        if size <= 0 and error in (errno.ESRCH, errno.ENOENT):
            return 0
        if size < 0 or (size == 0 and error):
            raise OSError(error or errno.EIO, 'Cannot inspect owned macOS process group')
        if size % ctypes.sizeof(ctypes.c_int):
            raise OSError(errno.EIO, 'Incomplete macOS process-group snapshot')
        return size

    ctypes.set_errno(0)
    needed = checked_size(library.proc_listpids(2, group_id, None, 0))  # PROC_PGRP_ONLY
    if not needed:
        return False
    capacity = needed // ctypes.sizeof(ctypes.c_int) + 16
    members = (ctypes.c_int * capacity)()
    ctypes.set_errno(0)
    used = checked_size(library.proc_listpids(2, group_id, members, ctypes.sizeof(members)))
    if used >= ctypes.sizeof(members):
        raise OSError(errno.EAGAIN, 'macOS process group changed during inspection')
    for pid in members[:used // ctypes.sizeof(ctypes.c_int)]:
        if pid <= 0:
            continue
        info = _BsdShortInfo()
        ctypes.set_errno(0)
        size = library.proc_pidinfo(pid, 13, 0, ctypes.byref(info), ctypes.sizeof(info))  # PROC_PIDT_SHORTBSDINFO
        error = ctypes.get_errno()
        if size == 0 and error in (errno.ESRCH, errno.ENOENT):
            continue  # Reaped between enumeration and inspection.
        if size != ctypes.sizeof(info) or info.pid != pid:
            raise OSError(error or errno.EIO, 'Cannot inspect macOS process-group member')
        if info.pgid == group_id and info.status != 5:  # SZOMB
            return True
    return False

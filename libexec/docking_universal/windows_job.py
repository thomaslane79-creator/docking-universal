"""Native Windows process-tree ownership, using kill-on-close job objects.

A small isolated Python wrapper joins the job and closes its own job handle
BEFORE executing the command. If the supervisor dies during that handshake,
the job either no longer exists or closes when the wrapper releases its handle;
no unowned scientific command may then start. No taskkill/process-name matching,
shell, private CPython handles or undocumented thread-resume API is used.

Win32 contract: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
Nested jobs (Windows 8+): inherited CI/desktop jobs are not broken away from.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IOCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kernel():
    if os.name != "nt":
        raise RuntimeError("Windows job objects require native Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    definitions = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenJobObjectW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in definitions.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


class WindowsProcessTree:
    """One private job, owned only by the supervisor after the child handshake."""

    def __init__(self):
        self.api = _kernel()
        self.name = "Local\\DockingUniversal-" + uuid4().hex
        self.handle = None
        ctypes.set_last_error(0)
        handle = self.api.CreateJobObjectW(None, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = handle
        try:
            if ctypes.get_last_error() == 183:  # Never adopt another owner's job.
                raise RuntimeError("Native process ownership name collision")
            information = _ExtendedLimits()
            information.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(handle, 9, ctypes.byref(information), ctypes.sizeof(information)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def spawn(self, command, **options):
        if self.handle is None:
            raise RuntimeError("Native process owner is closed")
        wrapper = Path(__file__).resolve()
        # -I/-S excludes foreign Python paths and sitecustomize before ownership
        # is established. The actual command receives the original environment.
        return subprocess.Popen([sys.executable, "-I", "-S", str(wrapper), "--job", self.name, "--",
                                 *(str(value) for value in command)], **options)

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(arguments) < 4 or arguments[0] != "--job" or arguments[2] != "--":
        raise SystemExit("Internal native process wrapper requires an owner and command")
    api = _kernel()
    # Only this short handshake holds a second handle. Close it before any
    # scientific subprocess starts, so the supervisor's death kills the tree.
    handle = api.OpenJobObjectW(0x0001, False, arguments[1])  # JOB_OBJECT_ASSIGN_PROCESS
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not api.AssignProcessToJobObject(handle, api.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        api.CloseHandle(handle)
    return subprocess.call(arguments[3:], shell=False, close_fds=True,
                           stdin=sys.stdin if sys.stdin is not None else subprocess.DEVNULL,
                           stdout=sys.stdout, stderr=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"Native supervised command could not start: {exc}", file=sys.stderr)
        raise SystemExit(125)

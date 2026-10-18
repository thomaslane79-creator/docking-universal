"""Real native job ownership, including children/grandchildren and owner death."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from docking_universal.processes import ProcessRequest, ProcessRunner, ProcessStatus


@unittest.skipUnless(os.name == "nt", "Requires actual Windows job objects")
class WindowsJobTests(unittest.TestCase):
    def alive(self, pid):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if not handle:
            if ctypes.get_last_error() == 87:
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)

    def wait_gone(self, pid):
        deadline = time.monotonic() + 5
        while self.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.alive(pid), f"Owned process {pid} survived shutdown")

    def fixture(self, root):
        leaf = root / "leaf.py"
        leaf.write_text("import os,sys,time\nfrom pathlib import Path\n"
                        "Path(sys.argv[1]).write_text(str(os.getpid()))\ntime.sleep(60)\n", encoding="utf-8")
        parent = root / "parent.py"
        parent.write_text("import subprocess,sys,time\nfrom pathlib import Path\n"
                          "subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]])\n"
                          "while not Path(sys.argv[2]).is_file(): time.sleep(.01)\n"
                          "print('child-ready',flush=True)\ntime.sleep(60)\n", encoding="utf-8")
        return [sys.executable, str(parent), str(leaf), str(root / "leaf.pid")]

    def test_cancellation_kills_grandchild_not_unrelated_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cancel = threading.Event()
            unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                result = ProcessRunner().run(ProcessRequest(self.fixture(root), root, "tree", check=False,
                    timeout_seconds=10), cancel_event=cancel,
                    on_output=lambda event: cancel.set() if "child-ready" in event.text else None)
                self.assertEqual(result.status, ProcessStatus.CANCELLED)
                self.wait_gone(int((root / "leaf.pid").read_text()))
                self.assertIsNone(unrelated.poll())
            finally:
                unrelated.terminate()
                unrelated.wait(timeout=5)

    def test_timeout_kills_inheriting_descendants_and_releases_pipes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = ProcessRunner().run(ProcessRequest(self.fixture(root), root, "timeout", check=False,
                                                        timeout_seconds=2))
            self.assertEqual(result.status, ProcessStatus.TIMED_OUT)
            self.wait_gone(int((root / "leaf.pid").read_text()))
            self.assertLess(result.duration_seconds, 6)

    def test_owner_crash_automatically_kills_entire_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self.fixture(root)
            # The supervisor never gets to execute a cleanup/finally block.
            program = ("import sys,time,subprocess; from docking_universal.windows_job import WindowsProcessTree; "
                       f"owner=WindowsProcessTree(); p=owner.spawn({command!r},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                       "print(p.pid,flush=True); time.sleep(60)")
            supervisor = subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, text=True)
            try:
                wrapper = int(supervisor.stdout.readline())
                deadline = time.monotonic() + 8
                while not (root / "leaf.pid").is_file() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / "leaf.pid").is_file())
                supervisor.kill()
                supervisor.wait(timeout=5)
                self.wait_gone(wrapper)
                self.wait_gone(int((root / "leaf.pid").read_text()))
            finally:
                if supervisor.poll() is None:
                    supervisor.kill(); supervisor.wait(timeout=5)
                supervisor.stdout.close()

    def test_closed_owner_cannot_launch_work(self):
        from docking_universal.windows_job import WindowsProcessTree
        owner = WindowsProcessTree()
        owner.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            owner.spawn([sys.executable, "-c", "raise SystemExit(99)"])

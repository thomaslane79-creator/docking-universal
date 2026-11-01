import ctypes
import errno
import sys
import unittest
from unittest.mock import Mock

from docking_universal.darwin_processes import _BsdShortInfo, group_has_live_processes


class FakeProc:
    def __init__(self, records, *, missing=(), denied=(), truncated=False, list_error=0):
        self.records = records
        self.missing, self.denied = set(missing), set(denied)
        self.truncated, self.list_error = truncated, list_error
        self.calls = []

    def proc_listpids(self, kind, group, buffer, size):
        self.calls.append((kind, group))
        if self.list_error:
            ctypes.set_errno(self.list_error)
            return 0
        if buffer is None:
            return len(self.records) * ctypes.sizeof(ctypes.c_int)
        for index, pid in enumerate(self.records):
            buffer[index] = pid
        return size if self.truncated else len(self.records) * ctypes.sizeof(ctypes.c_int)

    def proc_pidinfo(self, pid, flavor, arg, pointer, size):
        if pid in self.missing or pid in self.denied:
            ctypes.set_errno(errno.ESRCH if pid in self.missing else errno.EPERM)
            return 0
        info = ctypes.cast(pointer, ctypes.POINTER(_BsdShortInfo)).contents
        info.pid, info.pgid, info.status = pid, *self.records[pid]
        return size


class DarwinProcessTests(unittest.TestCase):
    def test_native_record_layout_matches_public_short_bsd_info(self):
        self.assertEqual(ctypes.sizeof(_BsdShortInfo), 64)
        self.assertEqual(_BsdShortInfo.status.offset, 12)

    def test_only_zombies_or_disappeared_members_are_dead(self):
        for records, missing in (({}, ()), ({101: (99, 5), 102: (99, 5)}, ()),
                                 ({101: (99, 2)}, (101,))):
            library = FakeProc(records, missing=missing)
            self.assertFalse(group_has_live_processes(99, library=library))
            self.assertTrue(all(call == (2, 99) for call in library.calls))

    def test_running_sleeping_or_stopped_members_keep_the_group_live(self):
        for status in (0, 1, 2, 3, 4):
            self.assertTrue(group_has_live_processes(99, library=FakeProc({101: (99, 5), 102: (99, status)})))

    def test_reused_pid_in_another_group_is_not_an_owned_live_member(self):
        self.assertFalse(group_has_live_processes(99, library=FakeProc({101: (100, 2)})))

    def test_access_errors_and_incomplete_lists_are_not_dead_group_evidence(self):
        for library in (FakeProc({101: (99, 2)}, denied=(101,)),
                        FakeProc({101: (99, 5)}, truncated=True),
                        FakeProc({}, list_error=errno.EPERM)):
            with self.assertRaises(OSError):
                group_has_live_processes(99, library=library)

    def test_unreadable_member_record_is_inconclusive(self):
        library = FakeProc({101: (99, 5)})
        library.proc_pidinfo = Mock(return_value=0)
        with self.assertRaises(OSError):
            group_has_live_processes(99, library=library)

    def test_broad_or_invalid_group_queries_are_rejected(self):
        library = Mock()
        for group in (-1, 0, 1, 2 ** 31):
            with self.assertRaises(ValueError):
                group_has_live_processes(group, library=library)
        library.proc_listpids.assert_not_called()

    @unittest.skipUnless(sys.platform == 'darwin', 'Native macOS zombie process-group inspection')
    def test_native_zombie_only_group_is_not_a_cleanup_failure(self):
        import subprocess
        import signal
        import time
        from docking_universal.processes import ProcessRunner
        child = subprocess.Popen([sys.executable, '-c', "print('done', flush=True)"],
                                 stdout=subprocess.PIPE, start_new_session=True)
        try:
            self.assertEqual(child.stdout.read(), b'done\n')
            # Do not poll/wait: keep the exited child unreaped so its owned
            # group deterministically contains a zombie, not a live worker.
            deadline = time.monotonic() + 3
            while group_has_live_processes(child.pid) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(group_has_live_processes(child.pid))
            self.assertFalse(ProcessRunner._signal_posix_group(child.pid, signal.SIGTERM))
            self.assertEqual(child.wait(timeout=3), 0)
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=3)
            child.stdout.close()

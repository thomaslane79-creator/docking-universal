"""Native process-lock contracts; runs with only the standard library."""
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from docking_universal import file_lock


class FileLockTests(unittest.TestCase):
    def test_competing_process_is_rejected_and_owner_metadata_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'workspace.lock'
            with path.open('a+') as handle:
                file_lock.acquire(handle, blocking=False)
                handle.write('owner metadata'); handle.flush()
                script = '''import sys
from docking_universal.file_lock import acquire
with open(sys.argv[1], 'a+') as handle:
    try: acquire(handle, blocking=False)
    except BlockingIOError: sys.exit(0)
    raise SystemExit('competing process incorrectly obtained lock')
'''
                env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'libexec'))
                result = subprocess.run([sys.executable, '-c', script, str(path)], env=env,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                file_lock.release(handle)
            self.assertEqual(path.read_text(), 'owner metadata')

    def test_blocking_owner_waits_then_acquires_after_release(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.lock'
            acquired = threading.Event(); errors = []
            def worker():
                try:
                    with path.open('a+') as second:
                        file_lock.acquire(second)
                        acquired.set()
                        file_lock.release(second)
                except BaseException as exc:
                    errors.append(str(exc))
            with path.open('a+') as first:
                file_lock.acquire(first)
                thread = threading.Thread(target=worker, daemon=True); thread.start()
                self.assertFalse(acquired.wait(.075))
                file_lock.release(first)
                thread.join(3)
            self.assertTrue(acquired.is_set(), errors)
            self.assertFalse(thread.is_alive())

    def test_closed_handle_releases_native_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'empty.lock'
            first = path.open('a+')
            file_lock.acquire(first)
            first.close()
            with path.open('a+') as second:
                file_lock.acquire(second, blocking=False)
                file_lock.release(second)

    def test_unavailable_backend_is_not_silently_unlocked(self):
        handle = Mock()
        with patch.object(file_lock.os, 'name', 'nt'), patch.object(file_lock, 'msvcrt', None):
            with self.assertRaisesRegex(RuntimeError, 'locking is unavailable'):
                file_lock.acquire(handle)

    def test_windows_invalid_descriptor_is_not_treated_as_contention(self):
        backend = Mock()
        backend.locking.side_effect = OSError(errno.EBADF, 'bad descriptor')
        with patch.object(file_lock.os, 'name', 'nt'), patch.object(file_lock, 'msvcrt', backend):
            with self.assertRaises(OSError) as raised:
                file_lock.acquire(Mock(), blocking=False)
            self.assertEqual(raised.exception.errno, errno.EBADF)


if __name__ == '__main__':
    unittest.main()

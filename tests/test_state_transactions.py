import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from docking_universal.state import JsonStudyStore, RevisionConflictError, StudyState


class StateTransactionTests(unittest.TestCase):
    def test_windows_reader_waits_for_writer_and_keeps_scientific_state_unchanged(self):
        ready, completed, errors = threading.Event(), threading.Event(), []
        def reader():
            ready.set()
            try:
                self.store.load('study')
                self.store.list_studies()
            except BaseException as exc:
                errors.append(exc)
            finally:
                completed.set()
        before = self.store.path_for('study').read_bytes()
        with patch('docking_universal.state.WINDOWS', True):
            with self.store._lock('study'):
                thread = threading.Thread(target=reader, daemon=True); thread.start()
                self.assertTrue(ready.wait(1))
                self.assertFalse(completed.wait(.075))
            thread.join(3)
        self.assertTrue(completed.is_set())
        self.assertFalse(errors)
        self.assertEqual(self.store.path_for('study').read_bytes(), before)

    def test_missing_windows_read_never_creates_a_study_directory(self):
        with patch('docking_universal.state.WINDOWS', True):
            with self.assertRaises(FileNotFoundError):
                self.store.load('missing')
        self.assertFalse((self.root / 'missing').exists())

    def test_update_reads_under_its_existing_lock_without_recursive_load(self):
        with patch.object(self.store, 'load', side_effect=AssertionError('recursive reader lock')):
            self.store.update('study', lambda state: state.workflow_data.update(counter=1))
        self.assertEqual(self.store.load('study').workflow_data['counter'], 1)

    def test_native_reader_and_separate_writer_publish_complete_monotonic_records(self):
        self.store.update('study', lambda state: state.workflow_data.update(counter=0, padding='x' * 32768))
        code = '''import sys,time
from docking_universal.state import JsonStudyStore
store=JsonStudyStore(sys.argv[1])
for counter in range(1,81):
    store.update('study',lambda state:state.workflow_data.update(counter=counter))
    time.sleep(.002)
'''
        process = subprocess.Popen([sys.executable, '-c', code, str(self.root)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'libexec')})
        reads, previous = 0, 0
        deadline = time.monotonic() + 15
        try:
            while process.poll() is None and time.monotonic() < deadline:
                state = self.store.load('study')
                self.assertGreaterEqual(state.workflow_data['counter'], previous)
                previous = state.workflow_data['counter']; reads += 1
                self.assertEqual(state.workflow_data['padding'], 'x' * 32768)
                self.assertEqual(len(self.store.list_studies()), 1)
                time.sleep(.001)
            process.wait(timeout=2)
            self.assertEqual(process.returncode, 0, process.stderr.read())
            self.assertGreater(reads, 0)
            self.assertEqual(self.store.load('study').workflow_data['counter'], 80)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=3)
            process.stdout.close(); process.stderr.close()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root)
        self.store.create(StudyState("study", "Study", "site_guided_protocol"))

    def tearDown(self):
        self.temporary.cleanup()

    def test_stale_loaded_state_cannot_overwrite_newer_science(self):
        first = self.store.load("study")
        stale = self.store.load("study")
        first.workflow_data["owner"] = "first"
        self.store.save(first)
        stale.workflow_data["owner"] = "stale"
        with self.assertRaisesRegex(RevisionConflictError, "changed from revision"):
            self.store.save(stale)
        self.assertEqual(self.store.load("study").workflow_data["owner"], "first")

    def test_concurrent_updates_are_serialized_without_lost_values(self):
        barrier = threading.Barrier(3)

        def worker(label):
            barrier.wait()
            self.store.update("study", lambda state: state.workflow_data.setdefault("windows", []).append(label))

        threads = [threading.Thread(target=worker, args=(label,)) for label in ("left", "right")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(2)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(set(self.store.load("study").workflow_data["windows"]), {"left", "right"})

    def test_schema_one_fixture_is_read_and_migrated_on_save(self):
        path = self.store.path_for("study")
        record = json.loads(path.read_text())
        record["schema_version"] = 1
        record.pop("revision", None)
        path.write_text(json.dumps(record))
        state = self.store.load("study")
        self.assertEqual(state.revision, 0)
        self.store.save(state)
        migrated = json.loads(path.read_text())
        self.assertEqual(migrated["schema_version"], 3)
        self.assertEqual(migrated["revision"], 1)


if __name__ == "__main__":
    unittest.main()

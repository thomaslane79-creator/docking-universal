import json
import tempfile
import threading
import unittest
from pathlib import Path

from docking_universal.state import JsonStudyStore, RevisionConflictError, StudyState


class StateTransactionTests(unittest.TestCase):
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
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["revision"], 1)


if __name__ == "__main__":
    unittest.main()

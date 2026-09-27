import tempfile
import unittest
import sys
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.gui.host_client import ApplicationHostClient, ApplicationHostError
from docking_universal.models import PocketCandidate
from docking_universal.state import JsonStudyStore


class HostClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "runs")
        controller = StudyController(self.store)
        controller.create_study("client-study", "Client study")
        controller.start_simulated_pocket_review("client-study", [
            PocketCandidate("P1", "Pocket 1", 1, "box", "Candidate"),
        ])
        script = Path(__file__).parents[1] / "libexec" / "docking-universal-application-host.py"
        self.client = ApplicationHostClient(self.root / "runs", script)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_client_starts_host_reads_snapshot_and_applies_approval(self):
        self.client.start()
        self.assertEqual(
            Path(self.client.runtime["python_executable"]), Path(sys.executable).resolve()
        )
        self.assertTrue(self.client.runtime["python_version"])
        snapshot = self.client.request("client-study", "snapshot")
        study = snapshot["result"]["study"]
        decision = study["decisions"][0]
        approved = self.client.request(
            "client-study", "resolve_decision",
            {"decision_id": decision["id"], "selections": ["P1"], "actor": "scientist"},
            expected_revision=study["revision"], request_id="approve-from-client",
        )
        self.assertEqual(approved["status"], "applied")
        self.assertEqual(self.store.load("client-study").selected_pocket_ids, ["P1"])

    def test_client_rejects_requests_before_connection(self):
        with self.assertRaisesRegex(ApplicationHostError, "not connected"):
            self.client.request("client-study", "snapshot")

    def test_client_retains_explicit_scientific_host_interpreter(self):
        client = ApplicationHostClient(
            self.root / "runs", self.client.host_script,
            python_executable=sys.executable,
        )
        self.assertEqual(client.python_executable, Path(sys.executable).resolve())
        self.assertEqual(
            client._environment()["DOCKING_UNIVERSAL_PYTHON"], str(Path(sys.executable).resolve())
        )

    def test_failed_host_can_restart_against_the_same_persisted_study(self):
        first_session = self.client.start()
        self.client.process.terminate()
        self.client.process.wait(timeout=5)
        self.assertFalse(self.client.connected)
        second_session = self.client.restart()
        self.assertNotEqual(first_session, second_session)
        snapshot = self.client.request("client-study", "snapshot")
        self.assertEqual(snapshot["result"]["study"]["study_id"], "client-study")


if __name__ == "__main__":
    unittest.main()

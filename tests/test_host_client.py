import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()

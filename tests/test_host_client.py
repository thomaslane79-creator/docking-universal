import tempfile
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch

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

    def test_library_index_read_has_its_own_longer_timeout_without_changing_other_requests(self):
        from io import StringIO
        from types import SimpleNamespace
        self.client.process = SimpleNamespace(poll=lambda: None, stdin=StringIO())
        self.client.session_id = 'timeout-test'
        try:
            for operation, timeout in (('inspect_ligand_library', 120.0), ('snapshot', None)):
                with patch.object(self.client, '_read_message', return_value={
                    'status': 'applied', 'request_id': 'timeout-probe', 'result': {},
                }) as read:
                    self.client.request('client-study', operation, request_id='timeout-probe')
                    read.assert_called_once_with(timeout_seconds=timeout)
        finally:
            self.client.process = None
        self.assertEqual(self.client.timeout_seconds, 5.0)

    def test_runtime_identity_ignores_the_launching_terminal_conda_label(self):
        with patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "wrong-terminal-environment"}):
            self.client.start()
        prefix = Path(sys.prefix)
        expected = prefix.name if (prefix / "conda-meta").is_dir() else None
        self.assertEqual(self.client.runtime["conda_environment"], expected)
        self.assertEqual(self.client.runtime["python_prefix"], sys.prefix)

    def test_client_retains_explicit_scientific_host_interpreter(self):
        client = ApplicationHostClient(
            self.root / "runs", self.client.host_script,
            python_executable=sys.executable,
        )
        self.assertEqual(client.python_executable, Path(sys.executable).resolve())
        self.assertEqual(
            client._environment()["DOCKING_UNIVERSAL_PYTHON"], str(Path(sys.executable).resolve())
        )

    def test_source_validation_cli_is_not_silently_replaced_by_installed_cli(self):
        with patch.dict(os.environ, {'DOCKING_UNIVERSAL_CLI':'/validated/source/bin/docking-universal'}):
            self.assertEqual(self.client._environment()['DOCKING_UNIVERSAL_CLI'], '/validated/source/bin/docking-universal')

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

import tempfile
import unittest
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.orchestration import ProtocolWorkflowRunner
from docking_universal.state import JsonStudyStore


class ControlGuiAuthorityTests(unittest.TestCase):
    def test_invalid_or_unapproved_bundle_never_enables_screening(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = StudyController(JsonStudyStore(root / "state"))
            controller.create_study("control", "Control")
            output = root / "control-output"
            output.mkdir()
            (output / "invalid.duprotocol").write_bytes(b"not a bundle")
            (output / "study_manifest.json").write_text("{}")
            ProtocolWorkflowRunner(controller, root / "dummy-prepare")._register_control_outputs(
                "control", output, "completed",
            )
            state = controller.get_study("control")
            self.assertEqual(state.workflow_data["latest_control_status"], "not_approved")
            self.assertFalse(any(artifact.kind == "protocol_bundle" for artifact in state.artifacts))

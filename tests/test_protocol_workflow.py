import os
import tempfile
import time
import unittest
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher
from docking_universal.models import JobStatus
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.messages import Command


class ProtocolWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "runs")
        self.controller = StudyController(self.store)
        self.controller.create_study("workflow", "Workflow")
        self.input = self.root / "Target.pdb"
        self.input.write_text("ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\n")

    def tearDown(self):
        self.temporary.cleanup()

    def executable(self, *, slow=False):
        path = self.root / ("slow-prepare.sh" if slow else "prepare.sh")
        sleep = "sleep 10\n" if slow else ""
        path.write_text(
            "#!/usr/bin/env bash\nset -eu\n"
            + sleep
            + "name=$(basename \"$1\" .pdb)\n"
            + "root=\"$PWD/${name}_receptor_prep\"\n"
            + "mkdir -p \"$root/receptor\" \"$root/cavity/frozen_pockets\"\n"
            + "cp \"$1\" \"$root/receptor/${name}.pdb\"\n"
            + "printf 'RECEPTOR\\n' > \"$root/receptor/${name}.pdbqt\"\n"
            + "printf 'complete\\n' > \"$root/run.log\"\n"
            + "printf 'unchanged preliminary report\\n' > \"$root/preliminary-pocket-review.pdf\"\n"
            + "printf 'center_x = 1\\ncenter_y = 2\\ncenter_z = 3\\nsize_x = 20\\nsize_y = 20\\nsize_z = 20\\n' > \"$root/cavity/${name}_pocket1.conf\"\n"
            + "printf 'ATOM      1  C   STP Z   1       1.000   2.000   3.000  1.00  1.00           C\\n' > \"$root/cavity/frozen_pockets/pocket1_atm.pdb\"\n"
            + "printf '# review\\n' > \"$root/cavity/${name}_all_retained_pockets_review.pml\"\n"
        )
        path.chmod(0o755)
        return path

    def start_command(self, dispatcher, request_id="prepare"):
        state = self.store.load("workflow")
        return Command(
            "workflow", "session", request_id, "start_receptor_preparation",
            {
                "input_pdb": str(self.input), "working_directory": str(self.root / "work"),
                "site_mode": "pockets", "feedback_level": "guided",
                "cavity_mode": 1, "max_pockets": 3,
                "center_mode": "deepest", "centroid_mode": 1,
            },
            state.revision,
        )

    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.store.load("workflow")
            if predicate(state):
                return state
            time.sleep(0.02)
        self.fail("Timed out waiting for asynchronous workflow state")

    def test_preparation_discovers_artifacts_and_pauses_for_pocket_review(self):
        dispatcher = CommandDispatcher(self.controller, "session", self.executable())
        response = dispatcher.dispatch(self.start_command(dispatcher))
        self.assertEqual(response.status, "applied")
        state = self.wait_for(lambda item: bool(item.pending_decisions))
        self.assertEqual(state.pending_decisions[0].kind, "select_pockets")
        self.assertEqual([option.value for option in state.pending_decisions[0].options], ["P1"])
        kinds = {artifact.kind for artifact in state.artifacts}
        self.assertTrue({
            "prepared_receptor_structure", "prepared_receptor", "preliminary_report",
            "pocket_coordinates", "docking_box",
        } <= kinds)
        preliminary = next(artifact for artifact in state.artifacts if artifact.kind == "preliminary_report")
        self.assertEqual(Path(preliminary.path).read_text(), "unchanged preliminary report\n")
        self.assertEqual(state.jobs[0].status, JobStatus.COMPLETED)
        self.assertIsNotNone(state.jobs[0].process_id)
        duplicate_stage = dispatcher.dispatch(self.start_command(dispatcher, "second-preparation"))
        self.assertEqual(duplicate_stage.status, "rejected")
        self.assertIn("already complete", duplicate_stage.error)

    def test_host_can_cancel_running_preparation(self):
        dispatcher = CommandDispatcher(self.controller, "session", self.executable(slow=True))
        started = dispatcher.dispatch(self.start_command(dispatcher, "slow"))
        self.assertEqual(started.status, "applied")
        snapshot = dispatcher.dispatch(Command("workflow", "session", "snapshot", "snapshot"))
        cancelled = dispatcher.dispatch(Command(
            "workflow", "session", "cancel", "cancel_active_job", {}, snapshot.revision,
        ))
        self.assertEqual(cancelled.status, "applied")
        state = self.wait_for(lambda item: bool(item.jobs) and item.jobs[0].status is JobStatus.CANCELLED)
        self.assertEqual(state.pending_decisions, [])

    def test_host_shutdown_cancels_and_reaps_running_preparation(self):
        dispatcher = CommandDispatcher(self.controller, "session", self.executable(slow=True))
        started = dispatcher.dispatch(self.start_command(dispatcher, "shutdown"))
        self.assertEqual(started.status, "applied")
        dispatcher.shutdown()
        state = self.store.load("workflow")
        self.assertEqual(state.jobs[0].status, JobStatus.CANCELLED)
        self.assertIsNone(state.active_job)


if __name__ == "__main__":
    unittest.main()

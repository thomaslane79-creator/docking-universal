import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher, reconcile_interrupted_jobs, serve_json_lines
from docking_universal.models import CompletionStatus, Job, JobStatus
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.messages import Command


def command(session, request, operation, revision=None, payload=None):
    return Command(
        study_id="host-study", session_id=session, request_id=request,
        operation=operation, expected_revision=revision, payload=payload or {},
    )


class ApplicationHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = JsonStudyStore(Path(self.temporary.name))
        self.controller = StudyController(self.store)
        self.controller.create_study("host-study", "Host study")
        self.dispatcher = CommandDispatcher(self.controller, "session-1")
        self.candidates = [{
            "id": "P1", "label": "Pocket 1", "rank": 1,
            "box_artifact_id": "box-1", "summary": "Geometric hypothesis", "evidence": {},
        }]

    def tearDown(self):
        self.temporary.cleanup()

    def test_stale_session_and_revision_are_rejected(self):
        wrong = command("old-session", "one", "snapshot")
        self.assertEqual(self.dispatcher.dispatch(wrong).status, "rejected")
        stale = command("session-1", "two", "start_pocket_review", 0, {"candidates": self.candidates})
        response = self.dispatcher.dispatch(stale)
        self.assertEqual(response.status, "rejected")
        self.assertIn("changed from revision", response.error)

    def test_concurrent_launch_attempts_create_one_stage(self):
        revision = self.store.load("host-study").revision
        commands = [
            command("session-1", f"start-{index}", "start_pocket_review", revision, {"candidates": self.candidates})
            for index in range(2)
        ]
        responses = []
        threads = [threading.Thread(target=lambda item=item: responses.append(self.dispatcher.dispatch(item))) for item in commands]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertEqual([item.status for item in responses].count("applied"), 1)
        self.assertEqual(len(self.store.load("host-study").jobs), 1)

    def test_duplicate_approval_request_creates_one_approval_after_restart(self):
        initial = self.store.load("host-study").revision
        started = self.dispatcher.dispatch(command(
            "session-1", "start", "start_pocket_review", initial, {"candidates": self.candidates},
        ))
        decision_id = started.result["decision"]["id"]
        approve = command(
            "session-1", "approve-once", "resolve_decision", started.revision,
            {"decision_id": decision_id, "selections": ["P1"], "actor": "scientist"},
        )
        first = self.dispatcher.dispatch(approve)
        self.assertEqual(first.status, "applied")
        replayed = CommandDispatcher(StudyController(self.store), "session-1").dispatch(approve)
        self.assertEqual(replayed.status, "applied")
        self.assertEqual(len(self.store.load("host-study").approvals), 1)

    def test_reconcile_never_calls_abandoned_process_successful(self):
        state = self.store.load("host-study")
        state.jobs.append(Job("job-1", "docking", JobStatus.RUNNING))
        state.completion_status = CompletionStatus.RUNNING
        state.current_stage = "docking"
        self.store.save(state)
        self.assertEqual(reconcile_interrupted_jobs(self.store), 1)
        recovered = self.store.load("host-study")
        self.assertEqual(recovered.jobs[0].status, JobStatus.INTERRUPTED)
        self.assertEqual(recovered.completion_status, CompletionStatus.INTERRUPTED)

    def test_json_lines_returns_framed_response_and_rejects_unknown_fields(self):
        request = command("session-1", "snapshot", "snapshot").to_dict()
        source = io.StringIO(json.dumps(request) + "\n" + json.dumps({**request, "python": "bad"}) + "\n")
        target = io.StringIO()
        serve_json_lines(self.dispatcher, source, target)
        responses = [json.loads(line) for line in target.getvalue().splitlines()]
        self.assertEqual(responses[0]["status"], "applied")
        self.assertEqual(responses[1]["status"], "error")

    def test_host_process_owns_workspace_and_uses_only_framed_stdout(self):
        script = Path(__file__).parents[1] / "libexec" / "docking-universal-application-host.py"
        root = Path(self.temporary.name) / "process-host"
        process = subprocess.Popen(
            [sys.executable, str(script), "--state-root", str(root), "--session-id", "process-session"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "libexec")},
        )
        try:
            ready = json.loads(process.stdout.readline())
            self.assertEqual(ready["type"], "ready")
            second = subprocess.run(
                [sys.executable, str(script), "--state-root", str(root)],
                text=True, capture_output=True, timeout=3,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "libexec")},
            )
            self.assertEqual(second.returncode, 2)
            self.assertEqual(json.loads(second.stderr)["type"], "fatal")
            create = Command(
                "new-study", "process-session", "create", "create_study", {"name": "New study"},
            )
            process.stdin.write(json.dumps(create.to_dict()) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertEqual(response["status"], "applied")
            self.assertEqual(response["result"]["study"]["name"], "New study")
        finally:
            process.stdin.close()
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()

    def test_create_request_is_idempotent_after_host_restart(self):
        new_store = JsonStudyStore(Path(self.temporary.name) / "create-replay")
        request = Command("created", "session-1", "create-once", "create_study", {"name": "Created"})
        first = CommandDispatcher(StudyController(new_store), "session-1").dispatch(request)
        second = CommandDispatcher(StudyController(new_store), "session-1").dispatch(request)
        self.assertEqual(first.status, "applied")
        self.assertEqual(second.status, "applied")
        self.assertEqual(new_store.load("created").revision, 1)

    def test_remove_study_hides_it_without_deleting_retained_state(self):
        retained_path = self.store.path_for("host-study")
        response = self.dispatcher.dispatch(command(
            "session-1", "remove", "remove_study",
        ))
        self.assertEqual(response.status, "applied")
        self.assertTrue(response.result["external_outputs_preserved"])
        self.assertTrue(retained_path.is_file())
        self.assertEqual(self.store.list_studies(), [])
        self.assertIn(
            "removed_from_library_at",
            self.store.load("host-study").workflow_data,
        )


if __name__ == "__main__":
    unittest.main()

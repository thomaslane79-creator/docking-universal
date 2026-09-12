import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from docking_universal.application import ActiveStageError, StudyController
from docking_universal.jobs import JobService
from docking_universal.models import CompletionStatus, JobStatus
from docking_universal.processes import ProcessRequest, ProcessStatus
from docking_universal.state import JsonStudyStore


class JobServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.controller = StudyController(JsonStudyStore(self.root / "runs"))
        self.controller.create_study("job-study", "Job study")

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, code, name="stage"):
        return ProcessRequest(
            command=(sys.executable, "-u", "-c", code),
            log_directory=self.root / "logs",
            log_name=name,
            check=False,
        )

    def test_completed_stage_persists_job_state_logs_and_events(self):
        result = JobService(self.controller).run(
            "job-study", "fpocket", self.request("print('candidate summary', flush=True)")
        )
        state = self.controller.get_study("job-study")
        self.assertEqual(result.status, ProcessStatus.COMPLETED)
        self.assertEqual(state.jobs[0].status, JobStatus.COMPLETED)
        self.assertEqual(state.completion_status, CompletionStatus.COMPLETED)
        self.assertIsNone(state.active_job)
        self.assertEqual(Path(result.stdout_log).read_text(), "candidate summary\n")
        self.assertEqual({artifact.kind for artifact in state.artifacts}, {"job_stdout_log", "job_stderr_log"})
        self.assertTrue(any(event.message == "fpocket completed" for event in state.events))

    def test_failed_stage_is_retained_as_failure_with_diagnostic_log(self):
        result = JobService(self.controller).run(
            "job-study", "receptor_preparation",
            self.request("import sys; print('bad input', file=sys.stderr); raise SystemExit(3)", "failed"),
        )
        state = self.controller.get_study("job-study")
        self.assertEqual(result.status, ProcessStatus.FAILED)
        self.assertEqual(state.jobs[0].status, JobStatus.FAILED)
        self.assertEqual(state.completion_status, CompletionStatus.FAILED)
        self.assertIn("bad input", state.jobs[0].error)
        self.assertTrue(any(event.type.value == "stage_failed" and event.mandatory for event in state.events))

    def test_cancelled_stage_is_not_reported_as_success(self):
        cancel = threading.Event()
        timer = threading.Timer(0.1, cancel.set)
        timer.start()
        try:
            result = JobService(self.controller).run(
                "job-study", "docking", self.request("import time; print('started', flush=True); time.sleep(10)", "cancelled"),
                cancel_event=cancel,
            )
        finally:
            timer.cancel()
        state = self.controller.get_study("job-study")
        self.assertEqual(result.status, ProcessStatus.CANCELLED)
        self.assertEqual(state.jobs[0].status, JobStatus.CANCELLED)
        self.assertEqual(state.completion_status, CompletionStatus.CANCELLED)

    def test_second_window_cannot_start_while_first_stage_runs(self):
        second = StudyController(JsonStudyStore(self.root / "runs"))
        cancel = threading.Event()
        service = JobService(self.controller)
        request = self.request("import time; time.sleep(10)", "long")
        worker = threading.Thread(target=service.run, args=("job-study", "long_stage", request), kwargs={"cancel_event": cancel})
        worker.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and second.get_study("job-study").active_job is None:
            time.sleep(0.02)
        with self.assertRaises(ActiveStageError):
            JobService(second).run("job-study", "other_stage", self.request("print('should not run')", "other"))
        cancel.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()

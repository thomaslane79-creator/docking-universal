import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from docking_universal.application import ActiveStageError, StudyController
from docking_universal.jobs import JobService
from docking_universal.models import CompletionStatus, JobStatus
from docking_universal.processes import ProcessExecutionError, ProcessRequest, ProcessStatus
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
        self.assertEqual(state.completion_status, CompletionStatus.RUNNING)
        self.assertEqual(state.workflow_data["next_stage"], "pocket_review")
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

    def test_complete_logs_are_registered_while_stage_is_running(self):
        cancel = threading.Event()
        worker = threading.Thread(
            target=JobService(self.controller).run,
            args=(
                "job-study", "visible_stage",
                self.request("import time; print('live detail', flush=True); time.sleep(10)", "live"),
            ),
            kwargs={"cancel_event": cancel},
        )
        worker.start()
        try:
            deadline = time.monotonic() + 2
            state = self.controller.get_study("job-study")
            while time.monotonic() < deadline:
                state = self.controller.get_study("job-study")
                logs = [artifact for artifact in state.artifacts if "log" in artifact.kind]
                if state.active_job and logs and any(
                    "live detail" in Path(artifact.path).read_text(errors="replace")
                    for artifact in logs if Path(artifact.path).is_file()
                ):
                    break
                time.sleep(0.02)
            self.assertIsNotNone(state.active_job)
            self.assertEqual({artifact.kind for artifact in logs}, {"job_stdout_log", "job_stderr_log"})
            self.assertTrue(any("live detail" in Path(artifact.path).read_text() for artifact in logs))
        finally:
            cancel.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())

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

    def test_one_scientific_slot_is_shared_across_studies(self):
        self.controller.create_study("other-study", "Other study")
        cancel = threading.Event()
        worker = threading.Thread(
            target=JobService(self.controller).run,
            args=("job-study", "long_stage", self.request("import time; time.sleep(10)", "global")),
            kwargs={"cancel_event": cancel},
        )
        worker.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and self.controller.get_study("job-study").active_job is None:
            time.sleep(0.02)
        with self.assertRaises(ActiveStageError):
            JobService(self.controller).run(
                "other-study", "other", self.request("print('must not run')", "global-other")
            )
        cancel.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.controller.get_study("other-study").jobs, [])

    def test_zero_exit_without_required_artifact_is_a_failure(self):
        missing = self.root / "expected-output.json"
        result = JobService(self.controller).run(
            "job-study", "analysis", self.request("print('done')", "missing-output"),
            required_outputs=(missing,),
        )
        state = self.controller.get_study("job-study")
        self.assertEqual(result.status, ProcessStatus.FAILED)
        self.assertEqual(state.jobs[0].status, JobStatus.FAILED)
        self.assertIn("Required stage output", state.jobs[0].error)

    def test_checked_process_exception_still_persists_terminal_failure(self):
        request = ProcessRequest(
            command=(sys.executable, "-c", "raise SystemExit(4)"),
            log_directory=self.root / "logs", log_name="checked", check=True,
        )
        with self.assertRaises(ProcessExecutionError):
            JobService(self.controller).run("job-study", "checked_stage", request)
        state = self.controller.get_study("job-study")
        self.assertEqual(state.jobs[0].status, JobStatus.FAILED)
        self.assertIsNone(state.active_job)

    def test_unexpected_process_tracking_failure_is_persisted(self):
        class BrokenRunner:
            def run(self, _request, **_options):
                raise RuntimeError("process identity could not be retained")

        with self.assertRaisesRegex(RuntimeError, "identity could not be retained"):
            JobService(self.controller, runner=BrokenRunner()).run(
                "job-study", "tracked_stage", self.request("print('never')", "tracking-failure"),
            )
        state = self.controller.get_study("job-study")
        self.assertEqual(state.jobs[0].status, JobStatus.FAILED)
        self.assertIsNone(state.active_job)
        self.assertIn("identity could not be retained", state.jobs[0].error)


if __name__ == "__main__":
    unittest.main()

import sys
import tempfile
import threading
import unittest
from pathlib import Path

from docking_universal.processes import (
    ProcessExecutionError,
    ProcessRequest,
    ProcessRunner,
    ProcessStatus,
)


class ProcessAdapterTests(unittest.TestCase):
    def test_captures_streams_and_retains_complete_separate_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            seen = []
            result = ProcessRunner().run(
                ProcessRequest(
                    command=(
                        sys.executable,
                        "-c",
                        "import sys; print('out-line'); print('err-line', file=sys.stderr)",
                    ),
                    log_directory=directory,
                    log_name="stage",
                ),
                on_output=lambda event: seen.append((event.stream, event.text.strip())),
            )
            self.assertEqual(result.status, ProcessStatus.COMPLETED)
            self.assertEqual(Path(result.stdout_log).read_text(), "out-line\n")
            self.assertEqual(Path(result.stderr_log).read_text(), "err-line\n")
            self.assertCountEqual(seen, [("stdout", "out-line"), ("stderr", "err-line")])

    def test_nonzero_exit_is_classified_and_exposes_retained_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProcessExecutionError) as caught:
                ProcessRunner().run(ProcessRequest(
                    command=(sys.executable, "-c", "import sys; print('diagnosis', file=sys.stderr); raise SystemExit(7)"),
                    log_directory=directory,
                    log_name="failed-stage",
                ))
            self.assertEqual(caught.exception.result.status, ProcessStatus.FAILED)
            self.assertEqual(caught.exception.result.returncode, 7)
            self.assertIn("diagnosis", Path(caught.exception.result.stderr_log).read_text())

    def test_cancellation_terminates_process_and_retains_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            cancel = threading.Event()
            timer = threading.Timer(0.15, cancel.set)
            timer.start()
            try:
                result = ProcessRunner().run(
                    ProcessRequest(
                        command=(
                            sys.executable,
                            "-u",
                            "-c",
                            "import time; print('started', flush=True); time.sleep(10)",
                        ),
                        log_directory=directory,
                        log_name="cancelled-stage",
                        termination_grace_seconds=0.1,
                        check=False,
                    ),
                    cancel_event=cancel,
                )
            finally:
                timer.cancel()
            self.assertEqual(result.status, ProcessStatus.CANCELLED)
            self.assertIn("started", Path(result.stdout_log).read_text())
            self.assertLess(result.duration_seconds, 3.0)

    def test_timeout_is_distinct_from_user_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = ProcessRunner().run(ProcessRequest(
                command=(sys.executable, "-c", "import time; time.sleep(10)"),
                log_directory=directory,
                log_name="timed-out-stage",
                timeout_seconds=0.1,
                termination_grace_seconds=0.1,
                check=False,
            ))
            self.assertEqual(result.status, ProcessStatus.TIMED_OUT)


if __name__ == "__main__":
    unittest.main()

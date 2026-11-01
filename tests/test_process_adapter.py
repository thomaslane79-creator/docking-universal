import sys
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import docking_universal.processes as process_module

from docking_universal.processes import (
    ProcessExecutionError,
    ProcessRequest,
    ProcessRunner,
    ProcessStatus,
)


class ProcessAdapterTests(unittest.TestCase):
    def test_darwin_cleanup_accepts_permission_error_only_for_confirmed_dead_groups(self):
        from docking_universal import darwin_processes
        process = Mock(pid=12345)
        process.poll.return_value = 0
        for live in (False, True, OSError('inspection unavailable')):
            with self.subTest(live=live), patch.object(process_module.os, 'name', 'posix'), \
                    patch.object(process_module.sys, 'platform', 'darwin'), \
                    patch.object(process_module.signal, 'SIGKILL', 9, create=True), \
                    patch.object(process_module.os, 'killpg', create=True,
                                 side_effect=[None, PermissionError('group denied')]) as kill_group, \
                    patch.object(darwin_processes, 'group_has_live_processes') as inspect:
                if isinstance(live, Exception):
                    inspect.side_effect = live
                else:
                    inspect.return_value = live
                if live is False:
                    ProcessRunner._terminate(process, 0)
                else:
                    with self.assertRaisesRegex(PermissionError, 'group denied'):
                        ProcessRunner._terminate(process, 0)
                self.assertEqual(kill_group.call_count, 2)
                inspect.assert_called_once_with(process.pid)

    def test_cancelled_process_is_not_terminated_again_during_reader_cleanup(self):
        for fail_final_tick in (False, True):
            with self.subTest(fail_final_tick=fail_final_tick), tempfile.TemporaryDirectory() as directory:
                cancel = threading.Event()
                with patch.object(ProcessRunner, '_terminate', wraps=ProcessRunner._terminate) as terminate:
                    def tick():
                        if fail_final_tick and terminate.called:
                            raise RuntimeError('final feedback failed')
                    def run():
                        return ProcessRunner()._run(
                            ProcessRequest((sys.executable, '-u', '-c',
                                            "import time; print('ready',flush=True); time.sleep(10)"),
                                           directory, 'single-stop', termination_grace_seconds=.1, check=False),
                            tree=None, cancel_event=cancel, on_started=None, on_tick=tick,
                            on_output=lambda event: cancel.set() if 'ready' in event.text else None,
                        )
                    if fail_final_tick:
                        with self.assertRaisesRegex(RuntimeError, 'final feedback failed'):
                            run()
                    else:
                        self.assertEqual(run().status, ProcessStatus.CANCELLED)
                self.assertEqual(terminate.call_count, 1)

    def test_exited_posix_wrapper_does_not_hide_its_live_process_group(self):
        process = Mock(pid=12345)
        process.poll.return_value = 0
        with patch.object(process_module.os, 'name', 'posix'), \
             patch.object(process_module.os, 'killpg', create=True) as kill_group, \
             patch.object(process_module.signal, 'SIGKILL', 9, create=True):
            ProcessRunner._terminate(process, 0)
            self.assertEqual(kill_group.call_args_list, [
                call(process.pid, process_module.signal.SIGTERM), call(process.pid, 9),
            ])

    @unittest.skipIf(os.name == 'nt', 'POSIX process groups; Windows uses an owned Job Object')
    def test_completed_or_cancelled_wrapper_reaps_signal_ignoring_pipe_holder(self):
        import signal
        for cancel_running in (False, True):
            with self.subTest(cancel_running=cancel_running), tempfile.TemporaryDirectory() as directory:
                marker = str(Path(directory) / 'ready')
                child = (
                    "import pathlib,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                    "print('child-ready',flush=True); pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(30)"
                )
                parent = (
                    "import pathlib,subprocess,sys,time\n"
                    f"subprocess.Popen([sys.executable,'-u','-c',{child!r},{marker!r}])\n"
                    + ("time.sleep(30)\n" if cancel_running else
                       f"while not pathlib.Path({marker!r}).is_file(): time.sleep(.01)\n")
                )
                owned_group = []
                cancel = threading.Event()
                def cleanup():
                    if owned_group:
                        try:
                            os.killpg(owned_group[0], signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                watchdog = threading.Timer(4, cleanup)
                watchdog.start()
                finished = False
                try:
                    result = ProcessRunner().run(
                        ProcessRequest((sys.executable, '-u', '-c', parent), directory, 'descendant',
                                       termination_grace_seconds=.1, check=False),
                        cancel_event=cancel,
                        on_started=owned_group.append,
                        on_output=lambda event: cancel.set() if cancel_running and 'child-ready' in event.text else None,
                    )
                    finished = True
                finally:
                    watchdog.cancel()
                    if not finished:
                        cleanup()
                self.assertEqual(result.status, ProcessStatus.CANCELLED if cancel_running else ProcessStatus.COMPLETED)
                self.assertIn('child-ready', Path(result.stdout_log).read_text())
                self.assertLess(result.duration_seconds, 3)

    def test_scientific_child_cannot_inherit_an_open_host_command_pipe(self):
        with tempfile.TemporaryDirectory() as directory:
            code = (
                "import sys; from docking_universal.processes import ProcessRunner,ProcessRequest; "
                "r=ProcessRunner().run(ProcessRequest((sys.executable,'-c',"
                "\"import sys; assert sys.stdin.read()==''; print('eof')\"),"
                f"{directory!r},'stdin',timeout_seconds=2,check=False)); "
                "print(r.status.value,flush=True)"
            )
            # Keep the supervisor's command pipe OPEN throughout the wait.
            # Closing it with communicate() would hide the old inheritance bug.
            process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'libexec')})
            try:
                process.wait(timeout=12)
                self.assertEqual(process.returncode, 0, process.stderr.read())
                self.assertEqual(process.stdout.read().strip(), 'completed')
            finally:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()

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
            timer = threading.Timer(5, cancel.set)
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
                    on_output=lambda event: cancel.set() if "started" in event.text else None,
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

    def test_process_is_stopped_if_its_identity_cannot_be_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "identity persistence failed"):
                ProcessRunner().run(
                    ProcessRequest(
                        command=(sys.executable, "-c", "import time; time.sleep(10)"),
                        log_directory=directory,
                        log_name="untracked-stage",
                        termination_grace_seconds=0.1,
                        check=False,
                    ),
                    on_started=lambda _pid: (_ for _ in ()).throw(
                        RuntimeError("identity persistence failed")
                    ),
                )
            self.assertLess(time.monotonic() - started, 3.0)


if __name__ == "__main__":
    unittest.main()

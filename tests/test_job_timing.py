import unittest
from datetime import datetime, timezone
from docking_universal.job_timing import elapsed_seconds, duration_text
from docking_universal.models import Job, JobStatus


class JobTimingTests(unittest.TestCase):
    def test_terminal_duration_is_from_retained_timestamps_not_current_time(self):
        job = Job('screen', 'screening', JobStatus.COMPLETED,
                  started_at='2026-10-14T23:35:48.274031Z',
                  finished_at='2026-10-14T23:47:57.349705Z')
        self.assertEqual(elapsed_seconds(job), 729)
        self.assertEqual(duration_text(elapsed_seconds(job)), '12:09')
        job.status = JobStatus.FAILED
        self.assertEqual(elapsed_seconds(job), 729)

    def test_running_and_missing_or_invalid_timestamps_are_not_fabricated(self):
        job = Job('screen', 'screening', JobStatus.RUNNING, started_at='2026-10-15T10:00:00+00:00')
        self.assertEqual(elapsed_seconds(job, datetime(2026, 10, 15, 10, 2, 3, tzinfo=timezone.utc)), 123)
        self.assertEqual(duration_text(3661), '1:01:01')
        job.status = JobStatus.COMPLETED
        self.assertIsNone(elapsed_seconds(job))
        job.finished_at = '2026-10-15T09:00:00Z'
        self.assertIsNone(elapsed_seconds(job))
        job.started_at = 'invalid'
        self.assertIsNone(elapsed_seconds(job))

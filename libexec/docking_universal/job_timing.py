"""Read-only wall-clock durations from persisted supervised job timestamps."""
from datetime import datetime, timezone


def elapsed_seconds(job, now=None):
    try:
        start = datetime.fromisoformat(job.started_at.replace('Z', '+00:00'))
        if job.finished_at:
            end = datetime.fromisoformat(job.finished_at.replace('Z', '+00:00'))
        elif job.status.value == 'running':
            end = now or datetime.now(timezone.utc)
        else:
            return None
        seconds = (end - start).total_seconds()
        return int(seconds) if seconds >= 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def duration_text(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'

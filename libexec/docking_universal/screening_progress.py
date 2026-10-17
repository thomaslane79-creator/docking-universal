"""Advisory worker milestones, separate from scientific/terminal authority."""
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

PROGRESS_FILE = 'screening_progress.json'


def write_screening_progress(root, phase, message, **context):
    """Atomically publish a small phase record; feedback failure must not stop work."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=root, prefix='.screening-progress-',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(dict(context, schema_version=1, phase=phase, message=message,
                           updated_at=datetime.now(timezone.utc).isoformat()), stream)
        os.replace(temporary, Path(root) / PROGRESS_FILE)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def read_screening_progress(root):
    try:
        with (Path(root) / PROGRESS_FILE).open() as stream:
            record = json.loads(stream.read(65537))
        if (isinstance(record, dict) and record.get('schema_version') == 1
                and isinstance(record.get('phase'), str)
                and isinstance(record.get('message'), str)):
            return record
    except (OSError, ValueError):
        pass
    return {}

"""Runtime facts and a consistent, non-approval reproducibility disclosure."""
from __future__ import annotations

import os
import sys

DOCKING_REPRODUCIBILITY_NOTICE = (
    'Docking scores and poses may differ across operating systems, hardware, '
    'engine builds and API/CLI backends, even with the same seed. '
    'Match prepared inputs, backend/build, CPU settings and seeds when comparing runs; '
    'cross-platform equivalence must be validated.'
)
RUNTIME_KEYS = ('operating_system', 'operating_system_release', 'architecture', 'execution_backend', 'cpu')


def runtime_facts():
    """Capture the local execution host, without hostnames or unique identifiers."""
    # Avoid platform.uname's Windows command-shell fallback on Python 3.9.
    # Provenance collection must never spawn a command or change engine dispatch.
    if sys.platform == 'win32':
        version = sys.getwindowsversion()
        return dict(operating_system='Windows',
                    operating_system_release=f'{version.major}.{version.minor}.{version.build}',
                    architecture=os.environ.get('PROCESSOR_ARCHITEW6432') or
                                 os.environ.get('PROCESSOR_ARCHITECTURE') or 'not recorded')
    if hasattr(os, 'uname'):
        info = os.uname()
        return dict(operating_system=info.sysname, operating_system_release=info.release,
                    architecture=info.machine)
    return dict(operating_system=sys.platform, operating_system_release='not recorded',
                architecture='not recorded')


def recorded_runtime_fields(record):
    return {key: record[key] for key in RUNTIME_KEYS if record.get(key) not in (None, '')}


def retained_runtime_context(*records):
    """Prefer execution receipts; never infer an old run's OS from the report host."""
    result = {}
    for key in RUNTIME_KEYS:
        result[key] = next((str(record[key]) for record in records if isinstance(record, dict)
                            and record.get(key) not in (None, '', 'unknown', 'not recorded', 'NA')),
                           'not recorded')
    return result


def format_runtime_context(record):
    record = retained_runtime_context(record)
    system = {'Darwin': 'macOS'}.get(record['operating_system'], record['operating_system'])
    release = record['operating_system_release']
    if release != 'not recorded':
        system += ' (kernel release ' + release + ')'
    backend = {'cli': 'CLI', 'vina_python_batch': 'Vina persistent Python API',
               'ad4_gpu_opencl': 'AutoDock-GPU OpenCL'}.get(record['execution_backend'], record['execution_backend'])
    return (f"Recorded execution environment: operating system: {system}; host architecture: {record['architecture']}; "
            f"execution backend: {backend}; CPU setting: {record['cpu']}.")

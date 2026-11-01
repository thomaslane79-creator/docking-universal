#!/usr/bin/env python3
"""Check backend startup with no structure input; retain compatibility failures."""
import argparse
import json
from pathlib import Path
import subprocess


def probe(executable, timeout=10):
    try:
        result = subprocess.run([str(executable), '-h'], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=timeout)
        detail = (result.stdout + '\n' + result.stderr).strip()
        return {'available': result.returncode == 0, 'returncode': result.returncode,
                'command': [str(executable), '-h'], 'detail': detail[-6000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'available': False, 'command': [str(executable), '-h'], 'detail': str(exc)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('executable', type=Path)
    p.add_argument('audit', type=Path)
    args = p.parse_args()
    record = probe(args.executable)
    args.audit.write_text(json.dumps(record, indent=2) + '\n')
    print(record['detail'])
    return 0 if record['available'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

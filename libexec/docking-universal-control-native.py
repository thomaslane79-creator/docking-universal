#!/usr/bin/env python3
"""Internal strict native control stage; requires reviewed inputs and native acceptance."""
import os
from pathlib import Path
import sys
from docking_universal.native_control import parse_args, run_reviewed_control


def main():
    if os.name != 'nt':
        raise ValueError('This internal control entry point requires native Windows')
    # Direct invocation must not bypass the installation capability gate.
    import json
    app = Path(__file__).resolve().parent
    config = json.loads((app / 'native-preview.json').read_text(encoding='utf-8'))
    if not config.get('native_control_supported'):
        raise ValueError('Native control is awaiting installed acceptance; no job was started')
    from docking_universal.windows_desktop import installed_host
    if installed_host(app) is None:
        raise ValueError('Native control requires the exact owned scientific interpreter and receipt')
    run_reviewed_control(parse_args(), libexec=app)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

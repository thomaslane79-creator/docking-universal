#!/usr/bin/env python3
"""Engine-environment entry point; the scientific host need not import Vina."""
from docking_universal.vina_batch import main

if __name__ == '__main__':
    raise SystemExit(main())

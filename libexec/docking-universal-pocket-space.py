#!/usr/bin/env python3
"""Generate isolated, unfilled alpha pocket grids using local receptor coordinates."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
from docking_universal.services.pocket_space import validate_output

child = None


def stop(signum, frame):
    if child is not None and child.poll() is None:
        if os.name == 'nt':
            child.terminate()
        else:
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                child.kill()
            else:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    raise SystemExit(1)


def main():
    global child
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--prank', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.request.read_text())
    version_command = [str(args.prank), '-v']
    if os.name == 'nt':
        version_command = ['cmd', '/c'] + version_command
    if 'P2Rank 2.6-alpha' not in subprocess.check_output(version_command, text=True):
        raise ValueError('The visualization requires the pinned P2Rank 2.6-alpha')
    # BioJava's default provider can request unknown component definitions.
    # Disable that network path explicitly; exact prediction parity is still
    # mandatory, so changed handling of a modified residue fails closed.
    offline = Path(record['cache']) / 'offline.groovy'
    offline.write_text('import org.biojava.nbio.structure.chem.ChemCompGroupFactory\n'
                       'import org.biojava.nbio.structure.chem.ReducedChemCompProvider\n'
                       'ChemCompGroupFactory.setChemCompProvider(new ReducedChemCompProvider())\n')
    command = [str(args.prank), 'predict', '-f', record['receptor'], '-c', str(offline), '-visualizations', '1',
               '-vis_renderers', 'pymol', '-export_pocket_grid', '1', '-vis_pocket_grid', '1',
               '-pocket_grid_fill', 'none', '-pocket_grid_point_descriptors', '',
               '-o', str(Path(record['cache']) / 'alpha')]
    if os.name == 'nt':
        command = ['cmd', '/c'] + command
    child = subprocess.Popen(command, start_new_session=os.name != 'nt')
    if child.wait():
        raise RuntimeError('Alpha pocket-space generation failed; retained predictions are unchanged')
    validate_output(record)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    main()

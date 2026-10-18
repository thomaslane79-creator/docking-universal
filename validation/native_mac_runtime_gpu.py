"""Functional fresh-install AD4 check with a synthetic nonbiological fixture.

Two same-seed adapter runs against a methanol fragment are an installation check,
not a target/score calibration, performance benchmark or superiority claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.runtime.resolve()))
    from docking_universal.ad4_gpu import runtime_descriptor
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from meeko import MoleculePreparation, PDBQTWriterLegacy
    record = {'status': 'running', 'python': sys.executable, 'fixture': 'butane and a methanol receptor fragment',
              'scope': 'Native installation functional check only; no biological study data', 'runs': []}
    try:
        configured = runtime_descriptor()
        if not Path(configured['executable']).is_relative_to(Path(sys.prefix)):
            raise ValueError('Engine escaped the fresh prefix')
        if not Path(configured['autogrid_executable']).is_relative_to(Path(sys.prefix)):
            raise ValueError('AutoGrid escaped the fresh prefix')
        record['runtime'] = configured
        molecule = Chem.AddHs(Chem.MolFromSmiles('CCCC'))
        if AllChem.EmbedMolecule(molecule, randomSeed=42):
            raise ValueError('Synthetic fixture embedding failed')
        setup = MoleculePreparation().prepare(molecule)[0]
        text, success, error = PDBQTWriterLegacy.write_string(setup)
        if not success:
            raise ValueError(error)
        ligands = args.out / 'ligands'; ligands.mkdir()
        (ligands / 'butane.pdbqt').write_text(text)
        receptor = args.out / 'receptor.pdbqt'
        # A nonbiological fragment with actual Meeko charges and polar hydrogen.
        # AutoGrid's receptor path requires more than a dummy zero-charge atom;
        # this remains execution testing, not a physical receptor/control.
        fragment = Chem.AddHs(Chem.MolFromSmiles('CO'))
        if AllChem.EmbedMolecule(fragment, randomSeed=42):
            raise ValueError('Synthetic receptor fragment embedding failed')
        receptor_text, success, error = PDBQTWriterLegacy.write_string(MoleculePreparation().prepare(fragment)[0])
        if not success:
            raise ValueError(error)
        receptor.write_text('\n'.join(line for line in receptor_text.splitlines()
                                     if line.startswith(('ATOM  ', 'HETATM'))) + '\n')
        box = args.out / 'box.conf'
        box.write_text('center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 10\nsize_y = 10\nsize_z = 10\n')
        results = []
        for repeat in range(2):
            target = args.out / f'repeat-{repeat}'
            command = [str(Path(sys.prefix) / 'bin/docking-universal'), 'dock', '--engine', 'adgpu',
                '--receptor', str(receptor), '--ligands', str(ligands), '--config', str(box),
                '--out', str(target), '--seed', '41001']
            env = dict(os.environ, DOCKING_UNIVERSAL_PYTHON=sys.executable)
            with (args.out / f'repeat-{repeat}.log').open('w') as stream:
                subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
            pose = target / 'butane_adgpu.pdbqt'
            metadata = json.loads(pose.with_suffix('.pdbqt.json').read_text())
            result = {'repeat': repeat, 'output_sha256': hashlib.sha256(pose.read_bytes()).hexdigest(),
                      'pose_count': len(metadata['poses']), 'energy_units': metadata['energy_units'],
                      'scoring_function': metadata['scoring_function']}
            if result['pose_count'] != 20 or result['scoring_function'] != 'AD4':
                raise ValueError('Unexpected result inventory or score labeling')
            record['runs'].append(result); results.append(pose.read_bytes())
        record['same_seed_normalized_outputs_identical'] = results[0] == results[1]
        if results[0] != results[1]:
            raise ValueError('Same-seed synthetic installation outcomes differ')
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
    (args.out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))
    return 0 if record['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

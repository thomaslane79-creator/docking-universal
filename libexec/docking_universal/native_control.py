"""Shell-free reviewed-site control orchestration; no new docking method.

This is deliberately narrower than the historical Bash control command. A
sealed, explicitly approved receptor/site contract is required. Chemistry and
unbiased redocking/evaluation use the same existing Python helpers and tiers;
no experimental coordinates become a starting docking pose.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .services.control_review import read_reviewed_control_inputs
from .tool_commands import script_command


def selected_ligand_lines(source, ligand_id):
    parts = ligand_id.split(':')
    if len(parts) != 3 or not all(parts):
        raise ValueError('Control requires one exact RESNAME:CHAIN:RESNUM ligand')
    lines = []
    for line in Path(source).read_text(encoding='utf-8').splitlines():
        if not line.startswith('HETATM'):
            continue
        if (line[17:20].strip(), line[21:22].strip() or '_', line[22:26].strip()) != tuple(parts):
            continue
        if line[26:27].strip() or line[16:17].strip():
            raise ValueError('Insertion/alternate-location control ligands require separate exact-instance acceptance')
        lines.append(line)
    if not lines:
        raise ValueError('The exact reviewed experimental ligand is missing')
    return lines


def calibration_command(args, *, libexec, receptor, receptor_pdbqt, box, reference, crystal, output):
    command = [sys.executable, str(libexec / 'docking-universal-calibrate.py'),
        '--reference-sdf', str(reference), '--crystal-ligand', str(crystal),
        '--receptor-pdb', str(receptor), '--receptor-pdbqt', str(receptor_pdbqt),
        '--box', str(box), '--out', str(output), '--engine', args.engine,
        '--tier', args.control_tier, '--base-seed', str(args.base_seed),
        '--approval-min-seeds', str(args.approval_min_seeds),
        '--rmsd-threshold', str(args.rmsd_threshold), '--ph', str(args.ph),
        '--forcefield', args.forcefield, '--rmsd-prune', str(args.rmsd_prune),
        '--charge-model', args.charge_model, '--mk-export', args.mk_export,
        '--non-interactive']
    if args.conformers_override is not None:
        command.extend(['--conformers-override', str(args.conformers_override)])
    if args.skip_tautomers:
        command.append('--skip-tautomers')
    if not args.no_visuals:
        command.extend(['--render-visuals', '--pymol', args.pymol, '--plip-command', args.plip_command])
    return command


def parse_args(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complex', required=True, type=Path)
    parser.add_argument('--ligand-id', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--reviewed-inputs', required=True, type=Path)
    parser.add_argument('--reviewed-inputs-sha256', required=True)
    parser.add_argument('--engine', choices=('vina', 'qvinaw'), default='vina')
    parser.add_argument('--control-tier', choices=('quick', 'repeatability', 'broader', 'conformers', 'robust'), default='quick')
    parser.add_argument('--non-interactive', action='store_true', required=True)
    parser.add_argument('--approval-min-seeds', type=int, default=5)
    parser.add_argument('--base-seed', type=int, default=20260808)
    parser.add_argument('--ph', type=float, default=7.4)
    parser.add_argument('--conformers-override', type=int)
    parser.add_argument('--forcefield', choices=('mmff94', 'mmff94s', 'uff'), default='mmff94')
    parser.add_argument('--rmsd-prune', type=float, default=.75)
    parser.add_argument('--skip-tautomers', action='store_true')
    parser.add_argument('--charge-model', default='gasteiger')
    parser.add_argument('--rmsd-threshold', type=float, default=2.)
    parser.add_argument('--no-visuals', action='store_true')
    parser.add_argument('--plip-command', default=os.environ.get('DOCKING_UNIVERSAL_PLIP', 'plip'))
    parser.add_argument('--pymol', default=os.environ.get('DOCKING_UNIVERSAL_PYMOL', 'pymol'))
    parser.add_argument('--mk-export', default=os.environ.get('DOCKING_UNIVERSAL_MK_EXPORT', 'mk_export.py'))
    return parser.parse_args(arguments)


def run_reviewed_control(args, *, libexec=None, runner=None):
    # All sealed identities are rechecked before any directory or child process.
    record = read_reviewed_control_inputs(args.reviewed_inputs, complex_path=args.complex,
        ligand_id=args.ligand_id, engine=args.engine, expected_sha256=args.reviewed_inputs_sha256)
    source = Path(record['assets']['source_pdb']['path'])
    selected = selected_ligand_lines(source, args.ligand_id)
    root = args.out.resolve()
    if root.exists():
        raise FileExistsError('Native control requires a fresh output directory; partial/completed work is retained')
    libexec = Path(libexec or Path(__file__).resolve().parents[1])
    cli = Path(os.environ['DOCKING_UNIVERSAL_CLI'])
    receptor = Path(record['assets']['receptor_pdb']['path'])
    receptor_pdbqt = Path(record['assets']['receptor_pdbqt']['path'])
    box = Path(record['assets']['box']['path'])
    inputs, experimental, redocking = [root / name for name in ('00_inputs', '02_experimental_pose', '04_redocking')]
    for directory in (inputs, experimental, redocking):
        directory.mkdir(parents=True)
    shutil.copyfile(args.reviewed_inputs, inputs / 'reviewed_control_inputs.json')
    complex_copy = inputs / source.name
    shutil.copyfile(source, complex_copy)
    ligand = experimental / 'crystal_ligand.pdb'
    ligand.write_text('\n'.join(selected) + '\nEND\n', encoding='utf-8')
    reference = inputs / (args.ligand_id.split(':')[0] + '_experimental.sdf')
    manifest = {
        'workflow': 'bound_ligand_redocking_control', 'date': datetime.now(timezone.utc).isoformat(),
        'complex': str(complex_copy), 'ligand_id': args.ligand_id, 'ligand_selection': 'reviewed_exact_instance',
        'identity_verification': 'strict', 'provisional_pdb_chemistry_inference': 'no',
        'chemistry_identity': 'RCSB_CCD_SMILES', 'engine': args.engine,
        'preparation_source': 'user_reviewed_retained_preparation',
        'rmsd_threshold_angstrom': args.rmsd_threshold, 'generated_ligand_sdf': str(reference),
        'native_control_profile': 'reviewed-site-strict-python-v1',
    }
    (root / 'run_manifest.tsv').write_text(''.join(f'{key}\t{value}\n' for key, value in manifest.items()), encoding='utf-8')
    with (root / 'run.log').open('w', encoding='utf-8') as log:
        log.write('Reusing the reviewed receptor and box; no preparation repeated.\n'
                  'Strict coordinate-free CCD chemistry; independent embedded conformers; crystal pose withheld for evaluation.\n')
    if runner is None:
        def runner(command):
            normalized = script_command(command[0], *command[1:])
            with (root / 'run.log').open('a', encoding='utf-8') as log:
                log.write('+ ' + ' '.join(normalized) + '\n'); log.flush()
                return subprocess.run(normalized, stdin=subprocess.DEVNULL, stdout=log,
                                      stderr=subprocess.STDOUT, check=True)
    runner([sys.executable, libexec / 'docking-universal-bound-sdf.py', '--ligand-pdb', ligand,
            '--ligand-id', args.ligand_id, '--out', reference])
    complex_path = experimental / 'experimental_complex.pdb'
    protein = [line for line in receptor.read_text(encoding='utf-8').splitlines()
               if line.startswith(('ATOM  ', 'HETATM', 'TER'))]
    complex_path.write_text('\n'.join(protein + selected) + '\nEND\n', encoding='utf-8')
    if not args.no_visuals:
        runner([cli, 'depict2d', reference, '--out-dir', experimental / 'ligand_2d'])
        resname, chain, position = args.ligand_id.split(':')
        contacts = experimental / 'interactions'
        runner([cli, 'interactions', complex_path, '--out-dir', contacts,
                '--plip-command', args.plip_command, '--skip-native-visuals', '--typed-ligand-sdf', reference,
                '--ligand-resname', resname, '--ligand-chain', '' if chain == '_' else chain, '--ligand-position', position])
        runner([cli, 'render3d', contacts / 'experimental_complex_plip_all_in_one.pml',
                '--out', experimental / 'experimental_interactions.png',
                '--session-out', experimental / 'experimental_interactions.pse',
                '--contact-residue-labels', '--pymol', args.pymol])
    runner(calibration_command(args, libexec=libexec, receptor=receptor, receptor_pdbqt=receptor_pdbqt,
        box=box, reference=reference, crystal=ligand, output=redocking / args.engine))
    return root

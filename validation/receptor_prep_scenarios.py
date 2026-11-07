"""Sequential real-structure receptor-preparation probes, with retained receipts.

Run with the scientific environment's Python. ``fetch`` retrieves public native
mmCIFs; ``run`` exercises the shared engine without interactive model changes.
Raw structures/logs belong under ignored validation/runs, never in Git. Exit
codes are observations: a diagnosed safe stop is distinct from a software bug.
This checks preparation mechanics, not biological or charge-model accuracy.
"""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

import gemmi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))
from docking_universal.services.preparation_atom_inventory import audit_adfr_receptor_output

CASES = {
    '1UBQ': 'Small standard protein; ordinary strict preparation',
    '2R8N': 'Unbound protease with supporting glycerol',
    '1HVR': 'Bound inhibitor plus oxidized cysteine (CSO)',
    '1LYZ': 'Disulfide-rich lysozyme',
    '1CA2': 'Zinc-containing carbonic anhydrase; common metal coverage',
    '1D3Z': 'Ten-model NMR ubiquitin; multiple-model input handling',
    '1AKI': 'Independent modern lysozyme disulfide control',
    '2AYH': 'Independent historical missing-sidechain/PDBFixer repair candidate',
    '7ZAO': 'Historical missing-atom/PDBFixer repair candidate',
    '5NBX': 'Historical histidine-ambiguity candidate; current source may differ',
    '1ASF': 'Covalently linked PLP cofactor; independent exporter candidate',
    '1N6O': 'Linked BME plus nucleotide and magnesium',
    '2C1D': 'Nonstandard polymer chemistry; review/safe-stop candidate',
    '5IKR': 'Cobalt cofactors and linked glycans; preserve all linked components',
    '1UBQ_missing_sidechain': 'Controlled 1UBQ derivative: delete only LYS A27 NZ',
    '1UBQ_missing_backbone': 'Controlled 1UBQ derivative: delete only LYS A27 CA',
    '1UBQ_ph74': 'Unchanged 1UBQ; explicit PDB2PQR/PROPKA pH 7.4 assessment',
    '1UBQ_histidine_unresolved': 'Unchanged 1UBQ without external hydrogen placement; probe for histidine ambiguity',
    '1UBQ_histidine_HIE': 'Unchanged 1UBQ; isolated explicit A68=HIE template choice',
    '1ASF_no_adfr': 'Unchanged linked-PLP source; legacy fallback explicitly disabled',
    '1AKI_ph74': 'Disulfide-containing lysozyme; explicit pH-aware assessment',
    '1CA2_ph74': 'Zinc receptor; explicit protonation must not discard the metal',
    '1HVR_ph74': 'Oxidized cysteine; protonation must not silently replace or omit CSO',
}
VARIANTS = {
    '1UBQ_missing_sidechain': {'delete_atom': 'NZ'},
    '1UBQ_missing_backbone': {'delete_atom': 'CA'},
    '1UBQ_ph74': {'env': {'DOCKING_UNIVERSAL_REDUCE2': 'off',
                        'DOCKING_UNIVERSAL_PROTONATION': 'required'}},
    '1UBQ_histidine_unresolved': {'env': {'DOCKING_UNIVERSAL_REDUCE2': 'off',
        'DOCKING_UNIVERSAL_PROTONATION': 'off', 'DOCKING_UNIVERSAL_PDBFIXER': 'off'}},
    '1UBQ_histidine_HIE': {'env': {'DOCKING_UNIVERSAL_REDUCE2': 'off',
        'DOCKING_UNIVERSAL_PROTONATION': 'off', 'DOCKING_UNIVERSAL_PDBFIXER': 'off',
        'MEEKO_SET_TEMPLATE': 'A:68=HIE'}},
    '1ASF_no_adfr': {'env': {'DOCKING_UNIVERSAL_ADFR_FALLBACK': '0'}},
    '1AKI_ph74': {'env': {'DOCKING_UNIVERSAL_REDUCE2': 'off',
                         'DOCKING_UNIVERSAL_PROTONATION': 'required'}},
    '1CA2_ph74': {'env': {'DOCKING_UNIVERSAL_REDUCE2': 'off',
                         'DOCKING_UNIVERSAL_PROTONATION': 'required'}},
    '1HVR_ph74': {'env': {'DOCKING_UNIVERSAL_REDUCE2': 'off',
                         'DOCKING_UNIVERSAL_PROTONATION': 'required'}},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def source_features(path):
    block = gemmi.cif.read_file(str(path)).sole_block()
    category = block.get_mmcif_category('_atom_site.')
    groups = category['group_PDB']
    components = category['label_comp_id']
    elements = Counter(category['type_symbol'])
    alt = Counter(str(x) for x in category.get('label_alt_id', []) if x)
    links = block.get_mmcif_category('_struct_conn.')
    return {
        'title': block.find_value('_struct.title'),
        'revision_dates': list(block.find_values('_pdbx_audit_revision_history.revision_date')),
        'coordinate_rows': len(groups), 'elements': dict(elements),
        'alternate_location_rows': dict(alt),
        'polymer_components': sorted({c for g, c in zip(groups, components) if g == 'ATOM'}),
        'hetero_components': sorted({c for g, c in zip(groups, components) if g == 'HETATM'}),
        'connection_types': dict(Counter(links.get('conn_type_id', []))),
        'unobserved_atom_rows': len(block.get_mmcif_category('_pdbx_unobs_or_zero_occ_atoms.').get('id', [])),
        'unobserved_residue_rows': len(block.get_mmcif_category('_pdbx_unobs_or_zero_occ_residues.').get('id', [])),
    }


def fetch(out, ids):
    inputs = out / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    records = json.loads((out / 'sources.json').read_text()) if (out / 'sources.json').exists() else {}
    for pdb_id in ids:
        target = inputs / (pdb_id + '.cif')
        receipt = inputs / (pdb_id + '.source.json')
        if not target.exists():
            base_id = pdb_id.split('_', 1)[0]
            url = 'https://files.rcsb.org/download/' + base_id + '.cif'
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
                headers = dict(response.headers)
            original_sha = hashlib.sha256(data).hexdigest()
            target.write_bytes(data)
            variant = VARIANTS.get(pdb_id, {})
            deletion = variant.get('delete_atom')
            if deletion:
                original = inputs / (pdb_id + '.original.cif')
                original.write_bytes(data)
                document = gemmi.cif.read_file(str(target))
                block = document.sole_block()
                atoms = block.get_mmcif_category('_atom_site.')
                removed = [i for i in range(len(atoms['id']))
                           if atoms['auth_asym_id'][i] == 'A'
                           and atoms['auth_seq_id'][i] == '27'
                           and atoms['auth_comp_id'][i] == 'LYS'
                           and atoms['auth_atom_id'][i] == deletion]
                if len(removed) != 1:
                    raise RuntimeError('Controlled fixture must remove exactly one named atom')
                block.set_mmcif_category('_atom_site.', {
                    k: [v for i, v in enumerate(values) if i not in removed]
                    for k, values in atoms.items()})
                document.write_file(str(target))
            save(receipt, {'url': url, 'retrieved_utc': now(), 'headers': headers,
                           'original_source_sha256': original_sha,
                           'controlled_variant': variant or None,
                           'sha256': sha(target), 'bytes': target.stat().st_size})
        record = json.loads(receipt.read_text())
        if record['sha256'] != sha(target):
            raise RuntimeError('Downloaded source changed: ' + str(target))
        record.update(pdb_id=pdb_id, scenario=CASES[pdb_id], features=source_features(target))
        records[pdb_id] = record
        print(json.dumps({'pdb_id': pdb_id, **record['features']}), flush=True)
    save(out / 'sources.json', records)


def collect(case, pdb_id):
    receptor = case / (pdb_id + '_receptor_prep') / 'receptor'
    result = {'audits': {}, 'artifact_hashes': {}}
    for path in sorted(receptor.glob('*.json')):
        try:
            result['audits'][path.name] = json.loads(path.read_text())
        except (ValueError, OSError) as error:
            result['audits'][path.name] = {'read_error': str(error)}
    for path in sorted(receptor.iterdir() if receptor.exists() else []):
        if path.is_file():
            result['artifact_hashes'][str(path.relative_to(case))] = sha(path)
    adopted = receptor / (pdb_id + '.pdb')
    output = receptor / (pdb_id + '.pdbqt')
    if adopted.exists() and output.exists():
        # Same mechanical inventory checks as the legacy exporter guard; the
        # neutral name makes clear this receipt does not select an ADFR route.
        neutral_log = case / 'inventory-check.log'
        neutral_log.write_text('Independent mechanical inventory check.\n')
        inventory = audit_adfr_receptor_output(adopted, output, neutral_log,
                                              case / 'output-inventory.json')
        inventory['backend'] = 'independent_validation'
        save(case / 'output-inventory.json', inventory)
        result['output_inventory'] = inventory
    for path in sorted(receptor.glob('*.txt')):
        if path.stat().st_size < 100000:
            result.setdefault('text_audits', {})[path.name] = path.read_text(errors='replace')
    return result


def model_change_inventory(case, pdb_id):
    """Keep model construction distinct from exporter naming/coordinate changes."""
    receptor = case / (pdb_id + '_receptor_prep/receptor')
    def atoms(path):
        if not path.exists():
            return {}
        structure = gemmi.read_structure(str(path))
        return {':'.join((chain.name, str(res.seqid), res.name, atom.name,
                         atom.altloc.strip('\x00 '))):
                {'element': atom.element.name, 'xyz': [atom.pos.x, atom.pos.y, atom.pos.z]}
                for chain in structure[0] for res in chain for atom in res
                if atom.element.name not in ('H', 'D')}
    before = atoms(receptor / (pdb_id + '_filtered.pdb'))
    after = atoms(receptor / (pdb_id + '.pdb'))
    result = {'filtered_heavy_atom_count': len(before), 'adopted_heavy_atom_count': len(after),
              'removed_atom_identities': sorted(before.keys() - after.keys()),
              'added_atom_identities': sorted(after.keys() - before.keys()),
              'shared_identities_with_coordinate_changes': [
                  {'atom': k, 'before': before[k]['xyz'], 'after': after[k]['xyz']}
                  for k in sorted(before.keys() & after.keys())
                  if any(abs(a-b) > 0.0005 for a,b in zip(before[k]['xyz'], after[k]['xyz']))]}
    inventory_path = case / 'output-inventory.json'
    if inventory_path.exists():
        inventory = json.loads(inventory_path.read_text())
        # Meeko/RDKit can exchange terminal O/OXT labels. Retain the strict
        # identity audit, and separately check whether each changed coordinate
        # is an existing same-element position within that very same residue.
        # This is a naming observation, not proof of chemical equivalence.
        positions = {}
        for key, value in after.items():
            chain, seq, resname, atom_name, alt = key.split(':')
            positions.setdefault((chain, seq, resname, value['element']), []).append((atom_name, value['xyz']))
        permutations, displaced = [], []
        for change in inventory['coordinate_mismatches']:
            key = (change['chain'], change['number'] + change['insertion_code'], change['resname'])
            atom_elements = {value['element'] for atom_key, value in after.items()
                             if tuple(atom_key.split(':')[:4]) == key + (change['atom_name'],)}
            match = [name for group, values in positions.items()
                     if group[:3] == key and group[3] in atom_elements
                     for name, xyz in values if all(abs(a-b) < 0.0005 for a,b in zip(xyz, change['output']))]
            row = dict(change, output_position_matches_input_atom_names=match)
            (permutations if match else displaced).append(row)
        result['export_coordinate_label_permutations'] = permutations
        result['export_coordinates_without_an_input_position_match'] = displaced
    save(case / 'model-changes.json', result)
    return result


def run(out, ids, prefix, timeout, protect, overrides, service=False):
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'campaign.json').exists():
        raise FileExistsError('Use a new campaign folder; existing receipts must not be overwritten')
    protected = {str(p): sha(p) for p in protect}
    code_files = [ROOT / 'libexec/docking-universal-prepare',
                  ROOT / 'libexec/docking-universal-prepare-support.sh']
    code_files += sorted((ROOT / 'libexec/docking-universal-prepare.d').glob('*.sh'))
    code_files += sorted((ROOT / 'libexec').glob('docking-universal-*.py'))
    code_files += sorted((ROOT / 'libexec/docking_universal/services').glob('*.py'))
    installed = prefix / 'libexec/docking-universal'
    code = {str(p.relative_to(ROOT)): {'source_sha256': sha(p),
            'installed_sha256': sha(installed / p.relative_to(ROOT / 'libexec'))
            if (installed / p.relative_to(ROOT / 'libexec')).is_file() else None}
            for p in code_files}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('DOCKING_UNIVERSAL_', 'MEEKO_', 'PDB2PQR_'))}
    settings = {
        'DOCKING_UNIVERSAL_PYTHON': str(prefix / 'bin/python'),
        'DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY': '1',
        'DOCKING_UNIVERSAL_PREP_BACKEND': 'auto',
        'DOCKING_UNIVERSAL_SITE_MODE': 'pockets',
        'DOCKING_UNIVERSAL_REMOVAL_PROMPT': '0',
        'DOCKING_UNIVERSAL_LOG_MODE': 'file',
        'FEEDBACK_LEVEL': 'concise',
        'CONDA_PREFIX': str(prefix),
        'PATH': str(prefix / 'bin') + ':' + str(prefix / 'lib/jvm/bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
        'OPENMM_CPU_THREADS': '2', 'OMP_NUM_THREADS': '2',
    }
    settings.update(overrides)
    env.update(settings)
    campaign = {'started_utc': now(), 'commit': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'python': sys.version, 'runner_sha256': sha(__file__),
        'settings': settings, 'timeout_seconds': timeout,
        'entrypoint': 'gui_preparation_service' if service else 'preparation_engine',
        'protected_before': protected, 'code_hashes': code, 'cases': []}
    save(out / 'campaign.json', campaign)
    controller = None
    if service:
        from docking_universal.application import StudyController
        from docking_universal.state import JsonStudyStore
        from docking_universal.services.preparation import (
            ReceptorPreparationOptions, ReceptorPreparationService, build_receptor_preparation_plan)
        controller = StudyController(JsonStudyStore(out / 'isolated-study-state'))
    for pdb_id in ids:
        case = out / pdb_id
        case.mkdir(exist_ok=False)
        source = out / 'inputs' / (pdb_id + '.cif')
        source_hash = sha(source)
        command = [str(ROOT / 'libexec/docking-universal-prepare'), str(source)]
        case_settings = VARIANTS.get(pdb_id, {}).get('env', {})
        row = {'pdb_id': pdb_id, 'scenario': CASES[pdb_id], 'command': command,
               'source_sha256': source_hash, 'started_utc': now(), 'timed_out': False,
               'case_environment_overrides': case_settings}
        print('START ' + pdb_id, flush=True)
        started = time.monotonic()
        if service:
            controller.create_study(pdb_id, 'Isolated receptor validation ' + pdb_id)
            options = ReceptorPreparationOptions(source, case, 'pockets', feedback_level='concise',
                reduce2=case_settings.get('DOCKING_UNIVERSAL_REDUCE2', 'auto'),
                protonation=case_settings.get('DOCKING_UNIVERSAL_PROTONATION', 'auto'))
            plan = build_receptor_preparation_plan(command[0], options,
                                                   base_environment=dict(env, **case_settings))
            plan = replace(plan, request=replace(plan.request, timeout_seconds=timeout))
            result = ReceptorPreparationService(controller).run(pdb_id, plan)
            state = controller.get_study(pdb_id)
            row.update(command=list(result.command), returncode=result.returncode,
                       timed_out=result.status.value == 'timed_out', process_status=result.status.value,
                       persisted_job_status=state.jobs[-1].status.value,
                       active_job_after=state.active_job.id if state.active_job else None,
                       registered_artifact_kinds=[a.kind for a in state.artifacts],
                       registered_prepared_receptor=any(a.kind == 'prepared_receptor' for a in state.artifacts))
        else:
            row.update(run_process(command, case, dict(env, **case_settings), timeout))
        row.update(duration_seconds=round(time.monotonic() - started, 2), finished_utc=now())
        row.update(collect(case, pdb_id))
        row['model_changes'] = model_change_inventory(case, pdb_id)
        row['source_unchanged'] = sha(source) == source_hash
        save(case / 'receipt.json', row)
        campaign['cases'].append(row)
        save(out / 'campaign.json', campaign)
        print(json.dumps({k: row[k] for k in ('pdb_id', 'returncode', 'duration_seconds', 'timed_out')}), flush=True)
        if not row['source_unchanged'] or any(sha(p) != digest for p, digest in protected.items()):
            raise RuntimeError('An input/protected file changed; campaign stopped')
    campaign.update(finished_utc=now(), protected_after={p: sha(p) for p in protected})
    save(out / 'campaign.json', campaign)


def run_process(command, case, environment, timeout):
    row = {'timed_out': False}
    with (case / 'console.log').open('w') as log:
        process = subprocess.Popen(command, cwd=case, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            row['returncode'] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            row['timed_out'] = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            row['returncode'] = process.returncode
    return row


def review(out):
    """Reinspect retained outputs without running or modifying the preparation."""
    campaign = json.loads((out / 'campaign.json').read_text())
    results = []
    for row in campaign['cases']:
        case = out / row['pdb_id']
        results.append(dict(row, **collect(case, row['pdb_id']),
                            model_changes=model_change_inventory(case, row['pdb_id'])))
    save(out / 'review.json', {'reviewed_utc': now(), 'cases': results})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('fetch', 'run', 'service', 'review'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ids', nargs='+', choices=list(CASES), default=list(CASES))
    parser.add_argument('--prefix', type=Path, default=Path(sys.prefix))
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--protect', type=Path, action='append', default=[])
    parser.add_argument('--env', action='append', default=[], metavar='NAME=VALUE')
    args = parser.parse_args()
    if args.phase == 'fetch':
        fetch(args.out.resolve(), args.ids)
    elif args.phase == 'review':
        review(args.out.resolve())
    else:
        run(args.out.resolve(), args.ids, args.prefix.resolve(), args.timeout,
            args.protect, dict(item.split('=', 1) for item in args.env), service=args.phase == 'service')


if __name__ == '__main__':
    main()

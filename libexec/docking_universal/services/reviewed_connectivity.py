"""Opted-in, exact inferred-edge override; no atom/coordinate/valence waiver."""
from __future__ import annotations
import contextlib
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

SCHEMA = 'docking-universal-reviewed-connectivity'
READER_SHA256 = '53ff7d958b275368e464c6b89326b0a3ed2690801e1c4f55044c99236c366497'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_review(path, model_sha256):
    from .receptor_model_review import inspect_source_data, identity, label
    from .sidechain_candidate import SIDECHAINS, _hash
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('A regular local connectivity review is required')
    data = path.read_bytes(); review = json.loads(data)
    keys = {'schema_name', 'schema_version', 'model_sha256', 'backend_input', 'retained_stage_files',
            'edges', 'authority_sha256', 'meeko_reader_sha256'}
    optional = {'inter_residue_edges', 'interresidue_reader_sha256'}
    if (not isinstance(review, dict) or not keys <= set(review) or set(review) - keys - optional
            or (('inter_residue_edges' in review) != ('interresidue_reader_sha256' in review))
            or review['schema_name'] != SCHEMA
            or review['schema_version'] != 1 or review['model_sha256'] != model_sha256
            or review['meeko_reader_sha256'] != READER_SHA256 or not _hash(review['authority_sha256'])):
        raise ValueError('Review must bind the exact model, authority and supported reader')
    files = review['retained_stage_files']
    if not isinstance(files, dict) or not files:
        raise ValueError('Saved coordinate-stage files and checksums required')
    for name, row in files.items():
        if (Path(name).name != name or not isinstance(row, dict) or set(row) != {'path', 'sha256'}
                or not _hash(row['sha256']) or not isinstance(row['path'], str)
                or Path(row['path']).is_symlink() or sha(row['path']) != row['sha256']):
            raise ValueError('Saved coordinate-stage file changed or has invalid identity')
    backend = review['backend_input']
    if (not isinstance(backend, str) or backend not in files or not backend.endswith('_reduce2H.pdb')
            or set(files) != {backend, backend.replace('_reduce2H.pdb', '.pdb'),
                              backend.replace('_reduce2H.pdb', '_filtered.pdb'), 'reduce2_audit.json', 'reduce2.log'}):
        raise ValueError('Only the exact saved Reduce2 stage may be reused')
    audit = json.loads(Path(files['reduce2_audit.json']['path']).read_text())
    if audit.get('status') != 'compatible' or (audit.get('coordinate_frame') or {}).get('status') != 'preserved':
        raise ValueError('Saved hydrogen stage has no accepted preserved-frame audit')
    _, input_lines, atoms, _ = inspect_source_data(Path(files[backend]['path']).read_bytes())
    edges = review['edges']; seen = set(); descriptions = []
    if not isinstance(edges, list) or not edges:
        raise ValueError('Exact reviewed edge inventory required')
    for row in edges:
        if not isinstance(row, dict) or set(row) != {'resname', 'chain', 'number', 'insertion_code', 'atom_names'}:
            raise ValueError('Exact residue and atom identities required')
        key = identity({k: row[k] for k in ('resname', 'chain', 'number', 'insertion_code')}); names = row['atom_names']
        if (key[0] not in SIDECHAINS or not isinstance(names, list) or len(names) != 2
                or any(not isinstance(n, str) for n in names) or len(set(names)) != 2
                or any(n not in SIDECHAINS[key[0]].split() for n in names)):
            raise ValueError('Only two named standard side-chain heavy atoms may define an edge')
        token = (key, tuple(sorted(names)))
        if token in seen:
            raise ValueError('Each reviewed edge must appear only once')
        seen.add(token); lines = atoms.get(key, [])
        if any(l[16:17].strip() for l in lines) or any(sum(l[12:16].strip() == n for l in lines) != 1 for n in names):
            raise ValueError('Reviewed atoms are absent or ambiguous in saved coordinates')
        import gemmi
        library = Path(__file__).parents[1] / 'data/geostd' / key[0][0].lower() / ('data_' + key[0] + '.cif')
        canonical = {frozenset((r[0].strip("'\""), r[1].strip("'\""))) for b in gemmi.cif.read_file(str(library))
                     for r in b.find(['_chem_comp_bond.atom_id_1', '_chem_comp_bond.atom_id_2'])}
        if not canonical or frozenset(names) in canonical:
            raise ValueError('Cannot reject a declared standard-residue bond or use an unknown restraint table')
        descriptions.append(label(key) + ' ' + '–'.join(names))
    inter = review.get('inter_residue_edges', [])
    inter_tokens = set(); inter_descriptions = []
    if not isinstance(inter, list) or ('inter_residue_edges' in review and not inter):
        raise ValueError('Exact nonempty inter-residue edge list required when opted in')
    for edge in inter:
        if not isinstance(edge, dict) or set(edge) != {'first', 'second'}:
            raise ValueError('Two exact inter-residue endpoints required')
        tokens = []
        for endpoint in (edge['first'], edge['second']):
            if not isinstance(endpoint, dict) or set(endpoint) != {'resname', 'chain', 'number', 'insertion_code', 'atom_name'}:
                raise ValueError('Exact inter-residue atom identity required')
            key = identity({k: endpoint[k] for k in ('resname', 'chain', 'number', 'insertion_code')}); name = endpoint['atom_name']
            if key[0] not in SIDECHAINS or not isinstance(name, str) or not name:
                raise ValueError('Inter-residue review is limited to named standard amino acids')
            found = [l for l in atoms.get(key, []) if l[12:16].strip() == name]
            if len(found) != 1 or found[0][16:17].strip():
                raise ValueError('Inter-residue endpoint absent or ambiguous')
            if name not in SIDECHAINS[key[0]].split() and found[0][76:78].strip().upper() != 'H':
                raise ValueError('Backbone/nonstandard inter-residue overrides are unsupported')
            tokens.append((*key, name))
        if tokens[0][:4] == tokens[1][:4]:
            raise ValueError('Inter-residue endpoints must belong to different residues')
        token = tuple(sorted(tokens))
        if token in inter_tokens or all(t[0] == 'CYS' and t[4] == 'SG' for t in token):
            raise ValueError('Duplicate edge or possible disulfide cannot be overridden here')
        inter_tokens.add(token)
        serials = {int(l[6:11]): (*key, l[12:16].strip()) for key, lines in atoms.items() for l in lines}
        for line in input_lines:
            if line.startswith('CONECT'):
                numbers = [int(line[i:i+5]) for i in range(6, len(line.rstrip()), 5) if line[i:i+5].strip()]
                if numbers and any(tuple(sorted((serials.get(numbers[0], ()), serials.get(n, ())))) == token for n in numbers[1:]):
                    raise ValueError('A declared CONECT bond cannot be rejected as distance-only')
            if line.startswith('LINK  '):
                linked = [(line[17+o:20+o].strip(), line[21+o:22+o].strip(), line[22+o:26+o].strip(),
                           line[26+o:27+o].strip(), line[12+o:16+o].strip()) for o in (0, 30)]
                if tuple(sorted(linked)) == token:
                    raise ValueError('A declared LINK bond cannot be rejected as distance-only')
        inter_descriptions.append(label(tokens[0][:4]) + ' ' + tokens[0][4] + '–' + label(tokens[1][:4]) + ' ' + tokens[1][4])
    if inter and not _hash(review['interresidue_reader_sha256']):
        raise ValueError('Inter-residue reader source hash required')
    change = {'kind': 'standard_residue_connectivity_override',
        'description': 'Explicit connectivity override: rejected only inferred edges ' + ', '.join(descriptions)
                       + '. Atoms/coordinates retained; strict valence checks remain. Geometry is not validated.',
        'rejected_inferred_edges': edges, 'coordinate_changes': 0, 'atoms_removed': 0,
        'backend_input_sha256': files[backend]['sha256'], 'source_model_sha256': model_sha256,
        'review_sha256': hashlib.sha256(data).hexdigest(), 'authority_sha256': review['authority_sha256'],
        'saved_coordinate_stage_hashes': {n: r['sha256'] for n, r in files.items()},
        'strict_valence_checks_retained': True, 'coordinate_stage_reused': True}
    if inter:
        change['description'] = (f'Explicit connectivity override: {len(edges)} internal and {len(inter)} inter-residue inferred edges rejected. '
                                 'Close contacts remain; geometry unvalidated. All atoms/coordinates retained; strict checks remain. Exact edges: '
                                 + '; '.join(descriptions + inter_descriptions) + '.')
        change['rejected_inferred_interresidue_edges'] = inter
        change['interresidue_reader_sha256'] = review['interresidue_reader_sha256']
    return review, change


def remove_exact_edges(mol, names, pairs):
    from rdkit import Chem
    by_name = {}
    for index, name in names.items():
        if name in by_name:
            raise ValueError('Ambiguous atom name in reviewed residue')
        by_name[name] = index
    before = tuple(tuple(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms()))
    result = Chem.RWMol(mol)
    for pair in pairs:
        if len(set(pair)) != 2 or any(n not in by_name for n in pair):
            raise ValueError('Reviewed edge endpoints absent or identical')
        a, b = (by_name[n] for n in pair); bond = result.GetBondBetweenAtoms(a, b)
        if (bond is None or bond.GetBondType() != Chem.BondType.SINGLE
                or result.GetAtomWithIdx(a).GetAtomicNum() <= 1 or result.GetAtomWithIdx(b).GetAtomicNum() <= 1):
            raise ValueError('Expected inferred single heavy-atom edge is absent or changed')
        result.RemoveBond(a, b)
    if before != tuple(tuple(result.GetConformer().GetAtomPosition(i)) for i in range(result.GetNumAtoms())):
        raise ValueError('Override changed atoms or coordinates')
    # Identical nitrogen handling and strict sanitizer to Meeko's pinned reader.
    for atom in result.GetAtoms():
        if atom.GetAtomicNum() == 7 and len(atom.GetNeighbors()) == 4:
            atom.SetFormalCharge(1)
    Chem.SanitizeMol(result)
    return result.GetMol()


def reader_adapter(original, edges, applied, name_maps=None):
    from meeko.utils.rdkitutils import build_one_rdkit_mol_per_altloc
    from rdkit.Chem import rdDetermineBonds
    grouped = {}
    for row in edges:
        key = (row['resname'], row['chain'], row['number'], row['insertion_code'])
        grouped.setdefault(key, []).append(row['atom_names'])
    def read(fields, requested_altloc, default_altloc):
        keys = {(f.resname, f.chain, str(f.resnum), f.icode) for f in fields}
        if len(keys) != 1 or next(iter(keys)) not in grouped:
            result = original(fields, requested_altloc, default_altloc)
            if name_maps is not None and result[0] is not None and len(keys) == 1:
                first = fields[0]
                name_maps[f'{first.chain}:{first.resnum}{first.icode}'] = {i: fields[j].atomname for j, i in result[1].items()}
            return result
        key = next(iter(keys))
        if requested_altloc is not None or default_altloc is not None or any(f.altloc for f in fields):
            raise ValueError('No alternate-location authority granted by connectivity review')
        mols = build_one_rdkit_mol_per_altloc(fields)
        if set(mols) != {None}:
            raise ValueError('Reviewed residue requires unambiguous coordinates')
        mol, mapping = mols[None]; rdDetermineBonds.DetermineConnectivity(mol)
        names = {i: fields[j].atomname for j, i in mapping.items()}
        if name_maps is not None:
            first = fields[0]; name_maps[f'{first.chain}:{first.resnum}{first.icode}'] = names
        result = remove_exact_edges(mol, names, grouped[key])
        for pair in grouped[key]:
            applied.add((key, tuple(sorted(pair))))
        return result, mapping, False, False
    return read


def interresidue_adapter(original, edges, name_maps, applied):
    def read(mols):
        bonds = original(mols)
        for edge in edges:
            first, second = edge['first'], edge['second']
            a = f"{first['chain']}:{first['number']}{first['insertion_code']}"
            b = f"{second['chain']}:{second['number']}{second['insertion_code']}"
            pair = (a, b) if (a, b) in bonds else (b, a)
            if pair not in bonds or a not in name_maps or b not in name_maps:
                raise ValueError('Exact reviewed inter-residue edge absent')
            if mols[a][1] != first['resname'] or mols[b][1] != second['resname']:
                raise ValueError('Inter-residue endpoint component changed')
            expected = (first['atom_name'], second['atom_name']) if pair == (a, b) else (second['atom_name'], first['atom_name'])
            matches = [indices for indices in bonds[pair] if
                       (name_maps[pair[0]][indices[0]], name_maps[pair[1]][indices[1]]) == expected]
            if len(matches) != 1:
                raise ValueError('Reviewed inter-residue edge absent or ambiguous')
            retained = [indices for indices in bonds[pair] if indices != matches[0]]
            if retained:
                bonds[pair] = retained
            else:
                del bonds[pair]
            applied.add(tuple(sorted(tuple(e[k] for k in ('resname', 'chain', 'number', 'insertion_code', 'atom_name')) for e in (first, second))))
        return bonds
    return read


def invoke_strict_main(main):
    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    if code not in (None, 0):
        raise RuntimeError('Strict Meeko returned nonzero status: ' + str(code))


def execute_record(record_path, expected_record_sha256, output_root):
    data = Path(record_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_record_sha256:
        raise ValueError('Receptor-change approval record changed')
    record = json.loads(data); execution = record['connectivity_execution']
    if not record.get('actor') or not record.get('rationale') or sha(record['model_path']) != record['model_input_sha256']:
        raise ValueError('Explicit current model approval required')
    if sha(execution['path']) != execution['sha256']:
        raise ValueError('Connectivity recipe changed')
    review, change = validate_review(execution['path'], record['model_input_sha256'])
    if change['review_sha256'] != execution['sha256']:
        raise ValueError('Connectivity review changed during validation')
    output_root = Path(output_root); output_root.mkdir(parents=True, exist_ok=False)
    receptor = output_root / 'receptor'; receptor.mkdir()
    for name, row in review['retained_stage_files'].items():
        shutil.copyfile(row['path'], receptor / name)
        if sha(receptor / name) != row['sha256']:
            raise ValueError('Saved coordinate-stage snapshot changed before parameterization')
    stem = review['backend_input'].removesuffix('_reduce2H.pdb')
    (output_root / 'run.log').write_text('Reusing exact audited coordinate/hydrogen stage; no repeated modeling, Reduce2 or pockets.\nStrict Meeko with explicit reviewed connectivity only.\n')
    from meeko.polymer import Polymer
    from meeko.cli.mk_prepare_receptor import main as meeko_main
    namespace = Polymer._pdb_to_residue_mols.__globals__; original = namespace['_aux_altloc_mol_build']
    if hashlib.sha256(inspect.getsource(original).encode()).hexdigest() != review['meeko_reader_sha256']:
        raise ValueError('Installed Meeko reader differs from reviewed adapter contract')
    original_inter = namespace['find_inter_mols_bonds']
    if review.get('inter_residue_edges') and hashlib.sha256(inspect.getsource(original_inter).encode()).hexdigest() != review['interresidue_reader_sha256']:
        raise ValueError('Inter-residue reader differs from reviewed source')
    applied = set(); applied_inter = set(); name_maps = {}; prior_argv = sys.argv
    audit = {'status': 'running', 'source_coordinate_stage_reused': True, 'coordinate_changes': 0,
             'atoms_removed': 0, 'strict_valence_checks_retained': True,
             'review_sha256': execution['sha256'], 'approval_record_sha256': expected_record_sha256,
             'input_sha256': review['retained_stage_files'][review['backend_input']]['sha256']}
    try:
        namespace['_aux_altloc_mol_build'] = reader_adapter(original, review['edges'], applied, name_maps)
        if review.get('inter_residue_edges'):
            namespace['find_inter_mols_bonds'] = interresidue_adapter(original_inter, review['inter_residue_edges'], name_maps, applied_inter)
        sys.argv = ['mk_prepare_receptor.py', '--read_pdb', str(receptor / review['backend_input']),
                    '-o', str(receptor / stem), '-p', str(receptor / (stem + '.pdbqt'))]
        with (receptor / 'receptor_backend.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                invoke_strict_main(meeko_main)
            except BaseException:
                traceback.print_exc(); raise
        expected = {((r['resname'], r['chain'], r['number'], r['insertion_code']), tuple(sorted(r['atom_names']))) for r in review['edges']}
        pdbqt = receptor / (stem + '.pdbqt')
        expected_inter = {tuple(sorted(tuple(e[k] for k in ('resname', 'chain', 'number', 'insertion_code', 'atom_name'))
                                      for e in (edge['first'], edge['second']))) for edge in review.get('inter_residue_edges', [])}
        if applied != expected or applied_inter != expected_inter or not pdbqt.is_file() or not pdbqt.stat().st_size:
            raise ValueError('Not every exact edge applied or no prepared receptor created')
        if any(sha(receptor / n) != row['sha256'] or sha(row['path']) != row['sha256'] for n, row in review['retained_stage_files'].items()):
            raise ValueError('Retained or copied coordinate stage changed')
        helper = Path(__file__).parents[2] / 'docking-universal-ccd-audit.py'
        subprocess.run([sys.executable, str(helper), record['model_path'], str(pdbqt), str(receptor / 'receptor_backend.log'),
                        'strict_meeko', str(receptor / 'ccd_modification_audit.json'), str(receptor / 'ccd_modification_audit.tsv')], check=True)
        audit['status'] = 'passed_strict_reviewed_connectivity'
        with (output_root / 'run.log').open('a') as log:
            log.write('Prepared receptor PDBQT written; reviewed connectivity override retained.\n')
    except BaseException as exc:
        audit.update(status='failed', reason=str(exc)); raise
    finally:
        namespace['_aux_altloc_mol_build'] = original; namespace['find_inter_mols_bonds'] = original_inter; sys.argv = prior_argv
        audit['applied_edges'] = [{'resname': k[0], 'chain': k[1], 'number': k[2], 'insertion_code': k[3], 'atom_names': list(pair)} for k, pair in sorted(applied)]
        audit['applied_interresidue_edges'] = [list(map(list, edge)) for edge in sorted(applied_inter)]
        (receptor / 'connectivity_override_audit.json').write_text(json.dumps(audit, indent=2) + '\n')
        (receptor / 'coordinate_stage_reuse.json').write_text(json.dumps(review, indent=2) + '\n')

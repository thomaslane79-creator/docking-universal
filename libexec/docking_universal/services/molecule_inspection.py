"""Local inspection entries, independent of scientific input selections."""

import base64
import hashlib
import re
from functools import lru_cache
from pathlib import Path

from .coordinate_evidence import COMMON_CRYSTALLIZATION_ADDITIVES


# Inspection defaults only. These codes never exclude atoms from preparation,
# establish biological activity, or prevent explicit reference selection.
DISPLAY_ADDITIVES = COMMON_CRYSTALLIZATION_ADDITIVES | {'NH4', 'BOG', 'BNG', 'DTT', 'BME', 'EOH', 'IPA', 'PG4'}
DISPLAY_SUGARS = {'NAG', 'MAN', 'BMA', 'GLC', 'BGC', 'FUC', 'GAL', 'SIA'}
DISPLAY_COFACTORS = {'HEM', 'COH', 'HEC', 'HEO', 'FAD', 'FMN', 'NAD', 'NAP', 'NDP', 'FES', 'SF4'}
DISPLAY_METALS = {'CA', 'MG', 'ZN', 'FE', 'MN', 'CU', 'CO', 'NI'}


@lru_cache(maxsize=2048)
def _fragment_metadata(path, mtime, size):
    """Read local depositor metadata; screening context alone assigns no ligand role."""
    title, publication, names = [], [], {}
    for line in Path(path).read_text(errors='replace').splitlines():
        if line.startswith('TITLE '):
            title.append(line[10:80].strip())
        elif line.startswith('JRNL        TITL'):
            publication.append(line[19:80].strip())
        elif line.startswith('HETNAM'):
            names.setdefault(line[11:14].strip(), []).append(line[15:80].strip())
        elif line.startswith(('ATOM  ', 'HETATM')):
            break
    def joined(parts):
        result = ''
        for part in parts:
            result += ('' if result.endswith('-') else ' ') + part
        return result.strip()
    return joined(title), joined(publication), {code: joined(parts) for code, parts in names.items()}


def ligand_display_role(observation):
    """Conservatively recognize a named fragment using its own source metadata.

    Unknown stays unknown: a study's fragment-screening context alone does
    not establish that every compound in the structure is a fragment.
    """
    if is_supporting_component_observation(observation):
        return 'supporting_component'
    if observation.get('source') == 'input_structure':
        return 'unknown'
    identity = str(observation.get('source_ligand_id') or '').split('/')
    aligned = Path(str(observation.get('aligned_ligand_pdb') or ''))
    if len(identity) != 4 or aligned.parent.name != 'aligned_ligands':
        return 'unknown'
    source = aligned.parent.parent / 'structural_ensemble' / 'source_structures' / (identity[0].upper() + '.pdb')
    try:
        stat = source.stat()
        title, publication, names = _fragment_metadata(str(source), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return 'unknown'
    if 'FRAGMENT' not in (title + ' ' + publication).upper():
        return 'unknown'
    def normalized(value):
        return re.sub(r'[^A-Z0-9]', '', value.upper())
    name = normalized(names.get(identity[1].upper(), ''))
    if name and len(name) >= 6 and name in normalized(title):
        return 'fragment_screening'
    return 'unknown'


def is_supporting_component_observation(observation):
    """Identify known supporting components without asserting an unknown role.

    This is an evidence-display classification; it never removes an atom or
    establishes whether an unknown component is an inhibitor or agonist.
    """
    code = str(observation.get('ligand') or '').strip().split(' ', 1)[0].upper()
    if not code:
        identity = str(observation.get('source_ligand_id') or '').split('/')
        code = identity[1].upper() if len(identity) >= 4 else ''
    return bool(code and code in (DISPLAY_ADDITIVES | DISPLAY_SUGARS | DISPLAY_COFACTORS | DISPLAY_METALS))


def split_component_observations(observations):
    """Separate possible ligands from known supporting components, retaining both."""
    possible, supporting = [], []
    for observation in observations:
        (supporting if is_supporting_component_observation(observation) else possible).append(observation)
    return possible, supporting


def split_ligand_site_groups(groups):
    """Project report groups while retaining excluded components separately.

    Original records and box geometry stay untouched. If a mixed group's
    pocket match came only from a supporting component, do not transfer that
    match to a different ligand.
    """
    import copy
    possible_groups, supporting_groups = [], []
    for group in groups:
        members = group.get('members') or []
        if not members:
            representative = group.get('representative_ligand') or {}
            (supporting_groups if is_supporting_component_observation(representative) else possible_groups).append(copy.deepcopy(group))
            continue
        possible, supporting = split_component_observations(members)
        if supporting:
            support = copy.deepcopy(group)
            support['members'] = copy.deepcopy(supporting)
            supporting_groups.append(support)
        if not possible:
            continue
        projected = copy.deepcopy(group)
        if supporting:
            projected['members'] = copy.deepcopy(possible)
            projected['supporting_component_count'] = len(supporting)
            representative = projected.get('representative_ligand') or {}
            if is_supporting_component_observation(representative):
                projected['representative_ligand'] = copy.deepcopy(possible[0])
            counts = {}
            for member in possible:
                key = member.get('evidence_class') or 'unclassified'
                counts[key] = counts.get(key, 0) + 1
            projected['evidence_class_counts'] = counts
            for key in ('pocket_recovery', 'fpocket_recovery'):
                recovery = projected.get(key)
                if not isinstance(recovery, dict) or not recovery.get('best_matching_pocket'):
                    continue
                best = str(recovery['best_matching_pocket'])
                if not any(str(member.get('matched_cavity')) == best for member in possible):
                    projected[key] = {**recovery, 'status': 'not_recovered',
                                      'best_matching_pocket': None, 'supporting_pose_fraction': 0.0}
                    identity = projected.get('site_identity')
                    if isinstance(identity, dict):
                        identity['is_separate_from_predicted_pocket'] = True
                        identity['is_separate_from_fpocket'] = True
        possible_groups.append(projected)
    return possible_groups, supporting_groups


def possible_ligand_conformation(record):
    """Project older conformation records without treating cofactors as ligands."""
    observations = record.get('observations') or []
    if not observations or any('ligands' not in row for row in observations):
        return record  # Legacy records without identities remain explicitly unknown.
    retained = []
    for row in observations:
        ligands, _ = split_component_observations(row.get('ligands') or [])
        if ligands:
            retained.append({**row, 'ligands': ligands})
    obstructed = [row for row in retained if any(
        item.get('consistent_with_side_chain_occlusion') for item in row['ligands'])]
    residues = []
    for row in obstructed:
        residue = row.get('residue')
        if residue and residue not in residues:
            residues.append(residue)
    return {**record, 'observations': retained, 'observation_count': len(retained),
            'occluding_residues': residues,
            'status': ('conformationally_incompatible' if obstructed else
                       'reviewed_no_geometric_incompatibility' if retained else 'not_evaluated'),
            'box_decision_warning': record.get('box_decision_warning') if obstructed else None}


def _display_classification(code, chain, resi, segment, component_type, features):
    """Filter known supporting components, preserving declared interest/unknowns.

    The Boolean controls inspection visibility only. No inhibitor/agonist role
    is inferred from a component code, atom count or binding coordinates.
    """
    def value(key, i):
        values = features.get(key, [])
        return str(values[i]) if i < len(values) and values[i] not in (None, False, '.', '?') else ''

    annotations = []
    for i in range(len(features.get('feature_type', []))):
        if (value('auth_comp_id', i) or value('comp_id', i)) != code:
            continue
        if value('auth_asym_id', i) and value('auth_asym_id', i) != chain:
            continue
        if value('asym_id', i) and value('asym_id', i) != segment:
            continue
        if value('auth_seq_num', i) and value('auth_seq_num', i) != resi:
            continue
        annotations.append(value('feature_type', i).upper())
    if 'SUBJECT OF INVESTIGATION' in annotations:
        return False, 'Depositor marked this instance SUBJECT OF INVESTIGATION; activity is not specified.'
    if 'NO FUNCTIONAL ROLE' in annotations:
        return True, 'Depositor marked this instance NO FUNCTIONAL ROLE.'
    if code in DISPLAY_ADDITIVES:
        return True, 'Common crystallographic additive or detergent; hidden by the display filter.'
    if code in DISPLAY_SUGARS or 'saccharide' in str(component_type or '').lower():
        return True, 'Saccharide component; hidden by the display filter. Its biological role is unassigned.'
    if code in DISPLAY_COFACTORS:
        return True, 'Common cofactor component; available under All components.'
    if code in DISPLAY_METALS:
        return True, 'Metal ion; available under All components. This does not imply it is biologically irrelevant.'
    return False, 'Bound molecule; its biological activity is not assigned by the coordinate file.'


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_molecules(path):
    import gemmi
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {'.pdb', '.cif', '.mmcif'}:
        return []
    digest = _digest(source)
    structure = gemmi.read_structure(str(source))
    modified_residues = {
        (item.chain_name, item.res_id.name, str(item.res_id.seqid))
        for item in structure.mod_residues
    }
    names = {}
    component_types = {}
    features = {}
    if source.suffix.lower() == '.pdb':
        stat = source.stat()
        _, _, names = _fragment_metadata(str(source), stat.st_mtime_ns, stat.st_size)
    else:
        block = gemmi.cif.read_file(str(source)).sole_block()
        category = block.get_mmcif_category('_chem_comp.')
        nonpoly = block.get_mmcif_category('_pdbx_entity_nonpoly.')
        names = {code: name for code, name in zip(nonpoly.get('comp_id', []), nonpoly.get('name', []))
                 if code and name}
        names.update({code: name for code, name in zip(category.get('id', []), category.get('name', []))
                      if code and name})
        component_types = dict(zip(category.get('id', []), category.get('type', [])))
        features = block.get_mmcif_category('_pdbx_entity_instance_feature.')
    common = {'origin': 'input', 'path': str(source), 'sha256': digest}
    entries = [{**common, 'kind': 'whole', 'label': f'Loaded receptor / whole structure — {source.name}'}]
    if not len(structure):
        return entries
    for chain in structure[0]:
        for residue in chain:
            if residue.het_flag != 'H' or residue.is_water():
                continue
            code = residue.name
            label = f'{code} — chain {chain.name or "_"}, residue {residue.seqid}'
            if names.get(code):
                label += ' — ' + names[code]
            supporting, reason = _display_classification(
                code, chain.name, str(residue.seqid), residue.subchain,
                component_types.get(code, ''), features,
            )
            modified_polymer = (chain.name, code, str(residue.seqid)) in modified_residues
            if modified_polymer:
                supporting = True
                reason = 'Deposited modified polymer residue; part of the receptor, available under All components.'
            entries.append({**common, 'kind': 'component', 'label': label,
                            'resname': code, 'compound_name': names.get(code), 'chain': chain.name, 'resi': str(residue.seqid),
                            'residue_number': str(residue.seqid.num),
                            'insertion_code': str(residue.seqid.icode).strip(),
                            'segment': residue.subchain,
                            'supporting_component': supporting, 'modified_polymer': modified_polymer,
                            'display_reason': reason,
                            'observed_heavy_atoms': len({atom.name for atom in residue if atom.element.atomic_number > 1})})
    return entries


def library_molecules(library):
    if not library:
        return []
    return [{'origin': 'library', 'kind': 'compound', 'label': 'Screening compound — ' + row['name'],
             'source': library['source'], 'fingerprint': library['fingerprint'],
             'column_mapping': library.get('column_mapping'), 'record_id': row['record_id']}
            for row in library['records'] if row.get('valid')]


def verify_input(entry):
    source = Path(entry['path'])
    if not source.is_file() or _digest(source) != entry['sha256']:
        raise ValueError('The input structure changed. Close the inspector and load it again.')
    return source


def _component_molecule(entry):
    import gemmi
    from rdkit import Chem
    source = verify_input(entry)
    if source.suffix.lower() == '.pdb':
        raise ValueError('This PDB has no component chemical definition for a verified 2D drawing. Its 3D coordinates remain available.')
    block = gemmi.cif.read_file(str(source)).sole_block()
    atoms = block.get_mmcif_category('_chem_comp_atom.')
    bonds = block.get_mmcif_category('_chem_comp_bond.')
    code = entry['resname']
    rows = [i for i, value in enumerate(atoms.get('comp_id', [])) if value == code]
    if not rows:
        raise ValueError('No local component atom/bond definition is available for this molecule. Use its 3D view or open an SDF/MOL file.')
    molecule = Chem.RWMol()
    identifiers = {}
    stereo = {}
    for i in rows:
        atom = Chem.Atom(str(atoms['type_symbol'][i]).capitalize())
        atom.SetProp('_du_component_atom_id', str(atoms['atom_id'][i]))
        # Chemical-component tables contain explicit hydrogens. Never invent
        # protonation/charge to make an incomplete definition sanitize.
        atom.SetNoImplicit(True)
        charge = (atoms.get('charge') or ['?'] * len(atoms['comp_id']))[i]
        if charge not in ('?', '.', None, False):
            atom.SetFormalCharge(int(charge))
        index = molecule.AddAtom(atom)
        identifiers[atoms['atom_id'][i]] = index
        value = (atoms.get('pdbx_stereo_config') or ['N'] * len(atoms['comp_id']))[i]
        if value in {'R', 'S'}:
            stereo[index] = value
            molecule.GetAtomWithIdx(index).SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CCW)
    types = {'SING': Chem.BondType.SINGLE, 'DOUB': Chem.BondType.DOUBLE,
             'TRIP': Chem.BondType.TRIPLE, 'AROM': Chem.BondType.AROMATIC}
    double_stereo = []
    for i, component in enumerate(bonds.get('comp_id', [])):
        if component != code:
            continue
        order = str(bonds['value_order'][i]).upper()
        if order not in types:
            raise ValueError('This component uses a bond type that cannot be drawn reliably from the local definition.')
        bond_stereo = (bonds.get('pdbx_stereo_config') or ['N'] * len(bonds['comp_id']))[i]
        first = identifiers[bonds['atom_id_1'][i]]
        second = identifiers[bonds['atom_id_2'][i]]
        molecule.AddBond(first, second, types[order])
        if bond_stereo in {'E', 'Z'}:
            if order != 'DOUB':
                raise ValueError('Double-bond stereochemistry is attached to a non-double bond.')
            double_stereo.append((first, second, bond_stereo))
    result = molecule.GetMol()
    try:
        Chem.SanitizeMol(result)
        if any(atom.GetNumRadicalElectrons() for atom in result.GetAtoms()):
            raise ValueError('Incomplete or unsupported component valence')
        Chem.AssignStereochemistry(result, cleanIt=True, force=True, flagPossibleStereoCenters=True)
        # mmCIF E/Z uses CIP priorities, so select the highest-ranked explicit
        # substituent on each end before transferring the declared stereo.
        for first, second, expected in double_stereo:
            selected = []
            for atom_index, other in ((first, second), (second, first)):
                neighbors = [a for a in result.GetAtomWithIdx(atom_index).GetNeighbors() if a.GetIdx() != other]
                if not neighbors or any(not a.HasProp('_CIPRank') for a in neighbors):
                    raise ValueError('Double-bond substituent priority is unavailable')
                ranks = sorted(((int(a.GetProp('_CIPRank')), a.GetIdx()) for a in neighbors), reverse=True)
                if len(ranks) > 1 and ranks[0][0] == ranks[1][0]:
                    raise ValueError('Double-bond substituent priority is ambiguous')
                selected.append(ranks[0][1])
            bond = result.GetBondBetweenAtoms(first, second)
            bond.SetStereoAtoms(*selected)
            bond.SetStereo(Chem.BondStereo.STEREOE if expected == 'E' else Chem.BondStereo.STEREOZ)
        if double_stereo:
            Chem.SetDoubleBondNeighborDirections(result)
            Chem.AssignStereochemistry(result, cleanIt=False, force=True)
        for index, expected in stereo.items():
            atom = result.GetAtomWithIdx(index)
            if not atom.HasProp('_CIPCode'):
                raise ValueError('Missing stereochemical assignment')
            if atom.GetProp('_CIPCode') != expected:
                atom.InvertChirality()
        Chem.AssignStereochemistry(result, cleanIt=True, force=True)
        if any(not result.GetAtomWithIdx(i).HasProp('_CIPCode') or result.GetAtomWithIdx(i).GetProp('_CIPCode') != expected
               for i, expected in stereo.items()):
            raise ValueError('Ambiguous stereochemistry')
    except Exception as exc:
        raise ValueError('The local component definition cannot be drawn reliably without additional chemistry information. Its 3D view remains available.') from exc
    return result


def molecule_for_entry(entry):
    from rdkit import Chem
    if entry['origin'] == 'input':
        if entry['kind'] == 'whole':
            raise ValueError('Select an individual component for a 2D chemical drawing; use 3D for the whole receptor.')
        try:
            return _component_molecule(entry)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('The local component chemistry could not be drawn reliably. Its 3D coordinates remain available.') from exc
    if entry['origin'] == 'smiles':
        molecule = Chem.MolFromSmiles(entry['smiles'])
        if molecule is None or not molecule.GetNumAtoms():
            raise ValueError('The SMILES string could not be read.')
        return molecule
    from .ligand_library import selected_library_records
    selection = {'fingerprint': entry['fingerprint'], 'record_ids': [entry['record_id']]}
    if entry.get('column_mapping') is not None:
        selection['column_mapping'] = entry['column_mapping']
    _, records = selected_library_records(entry['source'], selection)
    return records[0][1]


def drawing_for_entry(entry):
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    molecule = molecule_for_entry(entry)
    drawer = rdMolDraw2D.MolDraw2DCairo(1000, 700)
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, Chem.RemoveHs(molecule))
    drawer.FinishDrawing()
    basis = '2D from the selected local compound.'
    if entry['origin'] == 'input':
        basis = (f"2D: component definition from the loaded mmCIF. "
                 f"Heavy atoms observed/defined: {entry['observed_heavy_atoms']}/{molecule.GetNumHeavyAtoms()}.")
    return drawer.GetDrawingText(), basis


def compound_3d_block(entry):
    from rdkit import Chem
    molecule = molecule_for_entry(entry)
    if not molecule.GetNumConformers() or not molecule.GetConformer().Is3D():
        raise ValueError('This compound has no supplied 3D coordinates. Its 2D drawing is available; no new geometry is generated automatically.')
    return Chem.MolToMolBlock(molecule)


def generated_compound_preview(entry, protocol):
    """Use the screening ensemble program and locked protocol for one preview."""
    from rdkit import Chem
    import subprocess, sys, tempfile
    from pathlib import Path
    if not protocol:
        raise ValueError('Finalize or select a docking protocol to generate a representative using its preparation settings.')
    parameters = protocol.get('parameters') or {}
    seeds = parameters.get('seeds') or []
    if not seeds or 'ph' not in parameters or 'conformers_per_state' not in parameters:
        raise ValueError('The selected protocol does not contain the ligand preparation settings needed for this preview.')
    script = Path(__file__).resolve().parents[2] / 'docking-universal-ensemble.py'
    with tempfile.TemporaryDirectory(prefix='du-ligand-preview-') as directory:
        root = Path(directory)
        source, output = root / 'ligand.sdf', root / 'ensemble.sdf'
        writer = Chem.SDWriter(str(source))
        try:
            writer.write(molecule_for_entry(entry))
        finally:
            writer.close()
        command = [sys.executable, str(script), str(source), '--out', str(output),
                   '--ph', str(parameters['ph']), '--conformers', str(parameters['conformers_per_state']),
                   '--seed', str(parameters.get('ensemble_seed', seeds[0])),
                   '--forcefield', str(parameters.get('forcefield', 'mmff94')),
                   '--rmsd-prune', str(parameters.get('rmsd_prune_angstrom', .75))]
        if parameters.get('tautomers_enumerated', True) is False:
            command.append('--skip-tautomers')
        process = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if process.returncode or not output.is_file():
            raise ValueError('Docking ligand preparation could not generate the preview: ' + (process.stderr.strip() or process.stdout.strip())[-600:])
        import json
        manifest = json.loads(output.with_suffix('.manifest.json').read_text())
        records = manifest.get('records') or []
        if not records or not records[0].get('optimization_converged'):
            raise ValueError('The representative ligand did not converge during minimization.')
        molecules = Chem.SDMolSupplier(str(output), removeHs=False)
        representative = next((m for m in molecules if m is not None), None)
        if representative is None or not representative.GetNumConformers() or not representative.GetConformer().Is3D():
            raise ValueError('Docking ligand preparation produced no readable 3D representative.')
        return {'mol_block': Chem.MolToMolBlock(representative), 'generated': True,
                'basis': 'Representative starting conformation generated and minimized with the selected docking protocol. This is not a docked pose.'}


def inspection_preview(entry, mode='drawing', protocol=None):
    """Return read-only molecule inspection data across the host boundary."""
    if not isinstance(entry, dict) or entry.get('origin') not in {'input', 'library', 'smiles'}:
        raise ValueError('A loaded input component or local compound is required for inspection.')
    if mode == 'drawing':
        png, basis = drawing_for_entry(entry)
        return {'png_base64': base64.b64encode(png).decode('ascii'), 'basis': basis}
    if mode == 'coordinates':
        return {'mol_block': compound_3d_block(entry)}
    if mode == 'generated_coordinates':
        if entry.get('origin') == 'input':
            raise ValueError('Generated coordinates cannot replace deposited input structures.')
        return generated_compound_preview(entry, protocol)
    if mode == 'validate':
        molecule_for_entry(entry)
        return {'valid': True}
    raise ValueError('Unknown molecule inspection mode')

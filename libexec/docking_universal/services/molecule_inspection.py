"""Local inspection entries, independent of scientific input selections."""

import base64
import hashlib
from pathlib import Path

from .coordinate_evidence import COMMON_CRYSTALLIZATION_ADDITIVES


# Inspection defaults only. These codes never exclude atoms from preparation,
# establish biological activity, or prevent explicit reference selection.
DISPLAY_ADDITIVES = COMMON_CRYSTALLIZATION_ADDITIVES | {'NH4', 'BOG', 'BNG', 'DTT', 'BME'}
DISPLAY_SUGARS = {'NAG', 'MAN', 'BMA', 'GLC', 'BGC', 'FUC', 'GAL', 'SIA'}
DISPLAY_COFACTORS = {'HEM', 'COH'}
DISPLAY_METALS = {'CA', 'MG', 'ZN', 'FE', 'MN', 'CU', 'CO', 'NI'}


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
        return True, 'Common porphyrin cofactor component; available under All components.'
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
    names = {}
    component_types = {}
    features = {}
    if source.suffix.lower() != '.pdb':
        block = gemmi.cif.read_file(str(source)).sole_block()
        category = block.get_mmcif_category('_chem_comp.')
        names = dict(zip(category.get('id', []), category.get('name', [])))
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
            entries.append({**common, 'kind': 'component', 'label': label,
                            'resname': code, 'chain': chain.name, 'resi': str(residue.seqid),
                            'residue_number': str(residue.seqid.num),
                            'insertion_code': str(residue.seqid.icode).strip(),
                            'segment': residue.subchain,
                            'supporting_component': supporting, 'display_reason': reason,
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
    for i, component in enumerate(bonds.get('comp_id', [])):
        if component != code:
            continue
        order = str(bonds['value_order'][i]).upper()
        if order not in types:
            raise ValueError('This component uses a bond type that cannot be drawn reliably from the local definition.')
        bond_stereo = (bonds.get('pdbx_stereo_config') or ['N'] * len(bonds['comp_id']))[i]
        if bond_stereo in {'E', 'Z'}:
            raise ValueError('The local component requires double-bond stereochemistry not supported by this inspector. Its 3D view remains available.')
        molecule.AddBond(identifiers[bonds['atom_id_1'][i]], identifiers[bonds['atom_id_2'][i]], types[order])
    result = molecule.GetMol()
    try:
        Chem.SanitizeMol(result)
        if any(atom.GetNumRadicalElectrons() for atom in result.GetAtoms()):
            raise ValueError('Incomplete or unsupported component valence')
        Chem.AssignStereochemistry(result, cleanIt=True, force=True)
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


def inspection_preview(entry, mode='drawing'):
    """Return read-only molecule inspection data across the host boundary."""
    if not isinstance(entry, dict) or entry.get('origin') not in {'input', 'library', 'smiles'}:
        raise ValueError('A loaded input component or local compound is required for inspection.')
    if mode == 'drawing':
        png, basis = drawing_for_entry(entry)
        return {'png_base64': base64.b64encode(png).decode('ascii'), 'basis': basis}
    if mode == 'coordinates':
        return {'mol_block': compound_3d_block(entry)}
    if mode == 'validate':
        molecule_for_entry(entry)
        return {'valid': True}
    raise ValueError('Unknown molecule inspection mode')

"""Inventory receptor atoms and verify exported models without constructing atoms.

Legacy preparers can exit successfully while dropping nonstandard components or
leaving an unparameterized atom in their output. Their success therefore needs
an independent atom/parameter audit before the artifact becomes authoritative.
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re


# Vina 1.2.7 atom_constants.h: AD4 names, Se equivalence and non-AD metals.
# This table establishes parser/type coverage, not a metal-specific force field
# or APBS radii. Dummy water/closure sites are not physical receptor atoms.
_VINA_ELEMENT = {
    'C': 'C', 'A': 'C', 'N': 'N', 'NA': 'N', 'O': 'O', 'OA': 'O',
    'P': 'P', 'S': 'S', 'SA': 'S', 'H': 'H', 'HD': 'H',
    'F': 'F', 'I': 'I', 'Mg': 'Mg', 'Mn': 'Mn', 'Zn': 'Zn',
    'Ca': 'Ca', 'Fe': 'Fe', 'Cl': 'Cl', 'Br': 'Br', 'Si': 'Si',
    'At': 'At', 'Se': 'Se', 'Cu': 'Cu', 'Na': 'Na', 'K': 'K',
    'Hg': 'Hg', 'Co': 'Co', 'U': 'U', 'Cd': 'Cd', 'Ni': 'Ni',
    'CG0': 'C', 'CG1': 'C', 'CG2': 'C', 'CG3': 'C',
}
_ELEMENTS = set(('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti '
                 'V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo '
                 'Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm '
                 'Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb '
                 'Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No '
                 'Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og').split())
_MISSING_GASTEIGER = re.compile(
    r'(?:there\s+are\s+)?no\s+Gasteiger\s+parameters\s+available\s+for\s+atom',
    re.IGNORECASE)


def _pdb_element(line):
    """Use explicit element columns, falling back to PDB atom-name alignment."""
    value = line[76:78].strip().capitalize()
    if not value:
        name = line[12:16]
        if name[:1].isspace() or name[:1].isdigit():
            value = next((c.upper() for c in name if c.isalpha()), '')
        else:
            value = name[:2].strip().capitalize()
            if value not in _ELEMENTS:
                value = name[:1].upper()
    return value if value in _ELEMENTS else None


def _atom_identity(line):
    return (line[21:22].strip(), line[22:26].strip(), line[26:27].strip(),
            line[17:20].strip(), line[12:16].strip())


def _identity_record(key):
    return dict(zip(('chain', 'number', 'insertion_code', 'resname', 'atom_name'), key))


def _export_atom_inventory(data, *, pdbqt):
    atoms, invalid = defaultdict(list), []
    count = 0
    charges = []
    for number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        count += 1
        key = _atom_identity(line)
        problems = []
        if not key[1] or not key[3] or not key[4]:
            problems.append('incomplete atom identity')
        try:
            xyz = [float(line[start:start + 8]) for start in (30, 38, 46)]
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError('nonfinite coordinates')
        except ValueError:
            xyz = None
            problems.append('missing, malformed or nonfinite coordinates')
        atom_type = line[77:].strip() if pdbqt else None
        element = _VINA_ELEMENT.get(atom_type) if pdbqt else _pdb_element(line)
        if not element:
            problems.append('unknown or missing Vina atom type' if pdbqt else
                            'unknown or missing source element')
        if pdbqt:
            try:
                charge = float(line[70:76])
                if not math.isfinite(charge):
                    raise ValueError('nonfinite charge')
                charges.append(charge)
            except ValueError:
                problems.append('missing, malformed or nonfinite partial charge')
        row = {'line': number, 'element': element, 'coordinates': xyz}
        if pdbqt:
            row['atom_type'] = atom_type
        if problems:
            invalid.append({**_identity_record(key), 'line': number,
                            'problems': problems})
        # An unrecognized element cannot be silently omitted as hydrogen.
        if element != 'H':
            atoms[key].append(row)
    return atoms, invalid, count, charges


def audit_adfr_receptor_output(source_pdb, output_pdbqt, backend_log, audit_path=None):
    """Return/write an accepted or rejected legacy export audit.

    Heavy-atom identities, elements and deposited coordinates must survive the
    exporter exactly at PDB precision. Hydrogen addition/merging is allowed;
    every output atom still needs finite coordinates/charge and a known Vina
    atom type. Missing Gasteiger parameters are fatal even if ADFR exits zero.
    An ``accepted`` result establishes these mechanical checks only, without
    claiming target-specific scoring, charge accuracy or APBS compatibility.

    Missing/malformed inputs produce a rejected audit rather than bypassing it.
    Audit-file write errors propagate so callers cannot accept an unaudited file.
    """
    paths = {'source': Path(source_pdb), 'output': Path(output_pdbqt),
             'backend_log': Path(backend_log)}
    captured, unreadable = {}, []
    report = {'schema_version': 1, 'backend': 'adfr', 'status': 'rejected',
              'scope': 'atom_retention_and_parameter_completeness_not_accuracy',
              'reasons': []}
    for label, path in paths.items():
        report[label + '_path'] = str(path)
        try:
            captured[label] = path.read_bytes()
            report[label + '_sha256'] = hashlib.sha256(captured[label]).hexdigest()
        except OSError as error:
            captured[label] = b''
            report[label + '_sha256'] = None
            unreadable.append({'file': label, 'error': str(error)})
    source, bad_source, source_count, _ = _export_atom_inventory(captured['source'], pdbqt=False)
    output, bad_output, output_count, charges = _export_atom_inventory(captured['output'], pdbqt=True)
    missing, extra, changed_element, moved = [], [], [], []
    duplicates_source, duplicates_output = [], []
    for atoms, duplicates in ((source, duplicates_source), (output, duplicates_output)):
        for key, rows in sorted(atoms.items()):
            if len(rows) > 1:
                duplicates.append({**_identity_record(key), 'lines': [r['line'] for r in rows]})
    for key in sorted(source.keys() - output.keys()):
        missing.append(_identity_record(key))
    for key in sorted(output.keys() - source.keys()):
        extra.append(_identity_record(key))
    for key in sorted(source.keys() & output.keys()):
        if len(source[key]) != 1 or len(output[key]) != 1:
            continue  # Duplicates are independently fatal, never arbitrarily paired.
        before, after = source[key][0], output[key][0]
        if before['element'] != after['element']:
            changed_element.append({**_identity_record(key), 'source': before['element'],
                                    'output': after['element']})
        if before['coordinates'] is not None and after['coordinates'] is not None:
            # Both file formats carry three decimal places; this only allows
            # floating-point representation error, not a one-unit PDB movement.
            if any(abs(a - b) > 0.0005 for a, b in zip(before['coordinates'], after['coordinates'])):
                moved.append({**_identity_record(key), 'source': before['coordinates'],
                              'output': after['coordinates']})
    charge_failures = [line.strip() for line in captured['backend_log'].decode(
        'utf-8', errors='replace').splitlines() if _MISSING_GASTEIGER.search(line)]
    report.update(unreadable_files=unreadable, source_atom_count=source_count,
        output_atom_count=output_count, source_heavy_atom_count=sum(map(len, source.values())),
        output_heavy_atom_count=sum(map(len, output.values())),
        missing_heavy_atoms=missing, extra_heavy_atoms=extra,
        duplicate_source_heavy_atoms=duplicates_source, duplicate_output_heavy_atoms=duplicates_output,
        element_mismatches=changed_element, coordinate_mismatches=moved,
        invalid_source_records=bad_source, invalid_output_records=bad_output,
        missing_charge_parameters=charge_failures)
    total_charge = sum(charges) if len(charges) == output_count else None
    total_charge_invalid = total_charge is not None and not math.isfinite(total_charge)
    checks = ((unreadable, 'One or more preparation audit inputs could not be read'),
              (not source, 'Source contains no heavy atoms'),
              (not output, 'Output contains no heavy atoms'),
              (bad_source, 'Source contains invalid atom records'),
              (bad_output, 'Output contains invalid coordinates, charges, identities or Vina atom types'),
              (duplicates_source, 'Source contains duplicate heavy-atom identities'),
              (duplicates_output, 'Output contains duplicate heavy-atom identities'),
              (missing, 'Output dropped %d source heavy atom(s)' % len(missing)),
              (extra, 'Output added %d heavy atom(s)' % len(extra)),
              (changed_element, 'Output changed heavy-atom elements'),
              (moved, 'Output changed source heavy-atom coordinates'),
              (total_charge_invalid, 'Output has a nonfinite total charge'),
              (charge_failures, 'ADFR reported missing Gasteiger parameters'))
    report['reasons'] = [message for failed, message in checks if failed]
    report['status'] = 'rejected' if report['reasons'] else 'accepted'
    report['output_total_charge'] = None if total_charge_invalid else total_charge
    if audit_path is not None:
        target = Path(audit_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return report


def missing_atom_inventory(missing_atoms):
    rows = []
    for residue, atoms in missing_atoms.items():
        names = sorted(atom.name for atom in atoms)
        rows.append({'chain': residue.chain.id, 'residue': residue.name,
                     'number': residue.id, 'insertion_code': getattr(residue, 'insertionCode', ''),
                     'missing_atom_names': names,
                     'missing_backbone_atom_names': sorted(set(names) & {'N', 'CA', 'C', 'O'}),
                     'missing_other_atom_names': sorted(set(names) - {'N', 'CA', 'C', 'O'})})
    return rows

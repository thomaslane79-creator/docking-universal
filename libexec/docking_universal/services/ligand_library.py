"""Read-only ligand inspection and hash-bound, explicit record selection."""

import base64
import hashlib
import json
import io
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path

from .ligand_input import ligand_input_files
from .ligand_table import TABLE_SUFFIXES, read_table, table_molecules, MAX_BYTES


# Host-local snapshots only. Binary molecules avoid retaining thousands of live
# RDKit objects; disk sources are still fully hashed before workload/launch.
_REVIEW_CACHE = OrderedDict()
_MAX_REVIEW_SNAPSHOTS = 2
_MAX_PREVIEW_IMAGES = 32


def _source_signature(source):
    values = []
    for path in ligand_input_files(source):
        stat = path.stat()
        values.append((str(path), stat.st_dev, stat.st_ino, stat.st_size,
                       stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(values)


def _fingerprint(files, column_mapping=None):
    value = files if column_mapping is None else {'files': files, 'column_mapping': column_mapping}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _current_fingerprint(source, column_mapping=None):
    files = []
    for path in ligand_input_files(source):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        files.append({'path': str(path), 'sha256': digest.hexdigest()})
    return _fingerprint(files, column_mapping)


def _remember(source, library, molecules, signature):
    from rdkit import Chem
    key = (str(Path(source).expanduser().resolve()), library['fingerprint'])
    snapshot = {'library': library, 'signature': signature, 'previews': OrderedDict(),
                'molecules': {identifier: molecule.ToBinary(Chem.PropertyPickleOptions.AllProps)
                              for identifier, molecule in molecules.items()}}
    _REVIEW_CACHE[key] = snapshot
    _REVIEW_CACHE.move_to_end(key)
    while len(_REVIEW_CACHE) > _MAX_REVIEW_SNAPSHOTS:
        _REVIEW_CACHE.popitem(last=False)
    return snapshot


def _review_snapshot(source, fingerprint, *, full_hash=False, column_mapping=None):
    if not isinstance(fingerprint, str):
        raise ValueError('A reviewed ligand-library fingerprint is required')
    key = (str(Path(source).expanduser().resolve()), fingerprint)
    snapshot = _REVIEW_CACHE.get(key)
    if Path(source).suffix.lower() in TABLE_SUFFIXES and column_mapping is None:
        raise ValueError('Approve the table columns before reviewing/selecting compounds')
    if snapshot is not None and snapshot['library'].get('column_mapping') != column_mapping:
        raise ValueError('Column mapping changed after review; approve and select again')
    before = _source_signature(source)
    if snapshot is None:
        library, molecules = _scan(source, column_mapping) if column_mapping is not None else _scan(source)
        if library['fingerprint'] != fingerprint or before != _source_signature(source):
            raise ValueError('Ligand library changed after review; read and select the compounds again')
        snapshot = _remember(source, library, molecules, before)
    elif full_hash or snapshot['signature'] != before:
        current = (_current_fingerprint(source, column_mapping) if column_mapping is not None
                   else _current_fingerprint(source))
        if current != fingerprint or before != _source_signature(source):
            raise ValueError('Ligand library changed after review; read and select the compounds again')
        snapshot['signature'] = before
    _REVIEW_CACHE.move_to_end(key)
    return snapshot


def _scan(source, column_mapping=None, sheet=None):
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
    rows, molecules, files = [], {}, []
    table = None
    for path in ligand_input_files(source):
        if path.suffix.lower() in TABLE_SUFFIXES and path.stat().st_size > MAX_BYTES:
            raise ValueError('Table exceeds the 128 MB import limit')
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"Ligand source could not be read: {path}: {exc}") from None
        digest = hashlib.sha256(content).hexdigest()
        files.append({"path": str(path), "sha256": digest})
        if path.suffix.lower() in TABLE_SUFFIXES:
            if column_mapping is not None and not isinstance(column_mapping, dict):
                raise ValueError('Invalid column mapping')
            chosen_sheet = column_mapping.get('sheet') if column_mapping is not None else sheet
            table, values = read_table(path, content, chosen_sheet)
            if column_mapping is None:
                continue  # headers/suggestions only, never implicit approval
            for index, (number, name, smiles, error, molecule) in enumerate(table_molecules(table, values, column_mapping), 1):
                mapping_text = json.dumps(column_mapping, sort_keys=True)
                identifier = hashlib.sha256(f'{path}\n{digest}\n{mapping_text}\n{number}'.encode()).hexdigest()
                row = {'record_id': identifier, 'source': str(path), 'source_sha256': digest,
                       'source_record': index, 'source_record_count': len(values),
                       'source_row': number, 'source_sheet': table['sheet'], 'source_smiles': smiles,
                       'name': name or f'Compound {index}', 'valid': molecule is not None,
                       'error': error, 'formula': '', 'formal_charge': ''}
                if molecule is not None:
                    row.update(formula=rdMolDescriptors.CalcMolFormula(molecule),
                               formal_charge=Chem.GetFormalCharge(molecule), heavy_atoms=molecule.GetNumHeavyAtoms())
                    molecules[identifier] = molecule
                rows.append(row)
            continue
        if column_mapping is not None:
            raise ValueError('Column mapping applies only to a single CSV, TSV or XLSX file')
        try:
            records = list(Chem.ForwardSDMolSupplier(io.BytesIO(content), removeHs=False))
        except (OSError, ValueError, RuntimeError):
            records = [None]
        invalid_mol = path.suffix.lower() == ".mol" and len(records) != 1
        for index, molecule in enumerate(records or [None], 1):
            identifier = hashlib.sha256(f"{path}\n{digest}\n{index}".encode()).hexdigest()
            row = {"record_id": identifier, "source": str(path), "source_sha256": digest,
                   "source_record": index, "source_record_count": len(records),
                   "name": f"{path.stem} / record {index}", "valid": False,
                   "error": "Unreadable or unsupported chemistry", "formula": "", "formal_charge": ""}
            if invalid_mol:
                row["error"] = "MOL must contain one molecule; use SDF for libraries"
            elif molecule is not None:
                from .compound_identity import compound_display_name
                row.update(name=compound_display_name(molecule, path, len(rows) + 1), valid=True, error="",
                           formula=rdMolDescriptors.CalcMolFormula(molecule),
                           formal_charge=Chem.GetFormalCharge(molecule), heavy_atoms=molecule.GetNumHeavyAtoms())
                molecules[identifier] = molecule
            rows.append(row)
    library = {"source": str(Path(source).expanduser().resolve()),
               "fingerprint": _fingerprint(files, column_mapping), "files": files, "records": rows}
    if table is not None:
        library.update(table=table, mapping_approved=column_mapping is not None)
        if column_mapping is not None:
            library['column_mapping'] = deepcopy(column_mapping)
    return library, molecules


def inspect_ligand_library(source, column_mapping=None, sheet=None):
    before = _source_signature(source)
    library, molecules = (_scan(source, column_mapping, sheet) if column_mapping is not None or sheet is not None
                          else _scan(source))
    if before != _source_signature(source):
        raise ValueError('Ligand library changed while being read; reload it')
    _remember(source, library, molecules, before)
    return deepcopy(library)


def selected_library_records(source, selection):
    if (not isinstance(selection, dict) or set(selection) not in
            ({"fingerprint", "record_ids"}, {"fingerprint", "record_ids", "column_mapping"})):
        raise ValueError("Ligand selection requires a library fingerprint and explicit record IDs")
    identifiers = selection["record_ids"]
    if (not isinstance(identifiers, list) or not identifiers
            or any(not isinstance(identifier, str) for identifier in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        raise ValueError("Select at least one compound, without duplicate record IDs")
    snapshot = _review_snapshot(source, selection['fingerprint'], full_hash=True,
                                column_mapping=selection.get('column_mapping'))
    if any(identifier not in snapshot['molecules'] for identifier in identifiers):
        raise ValueError("Selection contains an unknown or invalid compound record")
    from rdkit import Chem
    library = deepcopy(snapshot['library'])
    chosen = set(identifiers)
    return library, [(row, Chem.Mol(snapshot['molecules'][row['record_id']])) for row in library["records"]
                     if row["record_id"] in chosen]


def ligand_record_preview(source, fingerprint, identifier, column_mapping=None):
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    snapshot = _review_snapshot(source, fingerprint, column_mapping=column_mapping)
    if identifier not in snapshot['molecules']:
        raise ValueError("This compound has no valid molecular structure to display")
    previews = snapshot['previews']
    if identifier in previews:
        previews.move_to_end(identifier)
        return {'record_id': identifier, 'png_base64': previews[identifier]}
    molecule = Chem.RemoveHs(Chem.Mol(snapshot['molecules'][identifier]))
    drawer = rdMolDraw2D.MolDraw2DCairo(600, 420)
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, molecule)
    drawer.FinishDrawing()
    previews[identifier] = base64.b64encode(drawer.GetDrawingText()).decode('ascii')
    while len(previews) > _MAX_PREVIEW_IMAGES:
        previews.popitem(last=False)
    return {'record_id': identifier, 'png_base64': previews[identifier]}

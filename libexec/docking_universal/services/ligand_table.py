"""Literal, bounded SMILES-table reading; suggestions never authorize import.

Excel is read without Office, macros, formula evaluation or external lookups.
Only individual CSV/TSV/XLSX files are supported, not mixed table folders.
"""

import csv
import hashlib
import io
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


TABLE_SUFFIXES = {'.csv', '.tsv', '.xlsx'}
MAX_BYTES = 128 * 1024 * 1024
MAX_ROWS = 100000
MAX_COLUMNS = 4096
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _xml(archive, name):
    content = archive.read(name)
    if b'\x00' in content or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('Excel XML declarations/entities are not supported')
    return ET.fromstring(content)


def _xlsx(content, sheet):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if (sum(item.file_size for item in infos) > MAX_BYTES or len(infos) > 10000
                    or len({item.filename for item in infos}) != len(infos)):
                raise ValueError('Excel workbook is too large or has duplicate ZIP entries')
            workbook = _xml(archive, 'xl/workbook.xml')
            relations = _xml(archive, 'xl/_rels/workbook.xml.rels')
            targets = {r.get('Id'): r.get('Target') for r in relations
                       if r.get('TargetMode') != 'External'
                       and r.get('Type', '').endswith('/worksheet')}
            sheets = []
            paths = {}
            for entry in workbook.findall(NS + 'sheets/' + NS + 'sheet'):
                if not entry.get('name'):
                    raise ValueError('Excel worksheet is missing its name')
                target = targets.get(entry.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'))
                if not target:
                    continue
                path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
                if not path.startswith('xl/') or '..' in path.split('/'):
                    raise ValueError('Unsupported Excel worksheet path')
                if entry.get('name') in paths:
                    raise ValueError('Excel worksheet names must be unique')
                sheets.append(entry.get('name'))
                paths[entry.get('name')] = path
            if not sheets:
                raise ValueError('Excel workbook contains no readable worksheets')
            if sheet is None:
                sheet = sheets[0]
            if sheet not in paths:
                raise ValueError('Choose a worksheet present in this workbook')
            strings = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                # Read text runs, not XML markup or metadata values.
                strings = [''.join(t.text or '' for t in si.iter(NS + 't'))
                           for si in _xml(archive, 'xl/sharedStrings.xml')]
            rows = []
            previous_number = 0
            for row in _xml(archive, paths[sheet]).findall(NS + 'sheetData/' + NS + 'row'):
                number = int(row.get('r', len(rows) + 1))
                if not previous_number < number <= 1048576:
                    raise ValueError('Excel row addresses must be unique and in ascending order')
                previous_number = number
                values = {}
                for cell in row.findall(NS + 'c'):
                    match = re.fullmatch(r'([A-Z]+)[1-9][0-9]*', cell.get('r', ''))
                    if not match or int(re.search(r'[0-9]+$', cell.get('r')).group()) != number:
                        raise ValueError('Excel cell has an unsupported address')
                    column = 0
                    for letter in match.group(1):
                        column = column * 26 + ord(letter) - 64
                    if column > MAX_COLUMNS:
                        raise ValueError('Table exceeds 4096 columns')
                    if column - 1 in values:
                        raise ValueError('Excel row contains a duplicate cell address')
                    kind = cell.get('t', 'n')
                    value = cell.findtext(NS + 'v', '')
                    error = ''
                    if cell.find(NS + 'f') is not None:
                        value, error = '', 'Formula cells are not imported; supply literal SMILES text'
                    elif kind == 's':
                        index = int(value)
                        if not 0 <= index < len(strings):
                            raise ValueError('Excel cell has an invalid shared-string reference')
                        value = strings[index]
                    elif kind == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.iter(NS + 't'))
                    elif kind not in ('str',) and value:
                        error = 'SMILES must be literal text, not a number, date, boolean or error'
                    values[column - 1] = (value, error)
                rows.append((number, values))
                if len(rows) > MAX_ROWS + 1:
                    raise ValueError('Table exceeds 100000 data rows')
            return sheet, sheets, rows
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError, TypeError, RuntimeError) as exc:
        raise ValueError(f'Unable to read XLSX workbook: {exc}') from None


def read_table(path, content, sheet=None):
    if len(content) > MAX_BYTES:
        raise ValueError('Table exceeds the 128 MB import limit')
    if Path(path).suffix.lower() == '.xlsx':
        sheet, sheets, rows = _xlsx(content, sheet)
    else:
        if sheet is not None:
            raise ValueError('Worksheet selection applies only to XLSX files')
        try:
            encoding = 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            text = content.decode(encoding)
            reader = csv.reader(io.StringIO(text, newline=''), delimiter='\t' if Path(path).suffix.lower() == '.tsv' else ',', strict=True)
            rows = []
            previous_line = 0
            for values in reader:
                if len(values) > MAX_COLUMNS or len(rows) > MAX_ROWS:
                    raise ValueError('Table exceeds 100000 data rows or 4096 columns')
                rows.append((previous_line + 1, {i: (value, '') for i, value in enumerate(values)}))
                previous_line = reader.line_num
        except (UnicodeError, csv.Error) as exc:
            raise ValueError(f'Unable to read UTF-8/UTF-16 table: {exc}') from None
        sheets = []
    # First nonempty row is the header. Retain blank header columns by position.
    first = next((i for i, (_n, row) in enumerate(rows) if any(v[0] or v[1] for v in row.values())), None)
    if first is None:
        raise ValueError('Table is empty; a header row and SMILES rows are required')
    header_row, header = rows[first]
    width = max(header, default=-1) + 1
    columns = [{'index': i, 'label': header.get(i, ('', ''))[0].strip() or f'(unnamed column {i + 1})'}
               for i in range(width)]
    normalized = [re.sub(r'[^a-z0-9]', '', column['label'].lower()) for column in columns]
    def suggest(candidates):
        return next((normalized.index(key) for key in candidates if key in normalized), None)
    metadata = {'columns': columns, 'sheet': sheet, 'sheets': sheets,
                'source_sha256': hashlib.sha256(content).hexdigest(), 'header_row': header_row,
                'suggested_smiles_column': suggest(('smiles', 'isomericsmiles', 'canonicalsmiles', 'smilesstring')),
                'suggested_name_column': suggest(('compoundname', 'name', 'compoundid', 'id', 'title'))}
    data = [(number, row) for number, row in rows[first + 1:] if any(v[0] or v[1] for v in row.values())]
    return metadata, data


def validate_mapping(metadata, mapping):
    expected = {'source_sha256', 'sheet', 'smiles_column', 'name_column'}
    if not isinstance(mapping, dict) or set(mapping) != expected:
        raise ValueError('Approve the SMILES/name columns using Use these columns before importing compounds')
    if mapping['source_sha256'] != metadata['source_sha256'] or mapping['sheet'] != metadata['sheet']:
        raise ValueError('Ligand library changed after review; read and approve its columns again')
    for key in ('smiles_column', 'name_column'):
        index = mapping[key]
        if key == 'name_column' and index is None:
            continue
        if type(index) is not int or not 0 <= index < len(metadata['columns']):
            raise ValueError('Choose a SMILES column and an optional name/ID column from the table headers')
    if mapping['name_column'] == mapping['smiles_column']:
        raise ValueError('The name/ID column must differ from the SMILES column; choose None if unnecessary')


def table_molecules(metadata, rows, mapping):
    """No embedding, pH adjustment, minimization or silent filtering at import."""
    from rdkit import Chem
    validate_mapping(metadata, mapping)
    parameters = Chem.SmilesParserParams()
    parameters.parseName = False
    parameters.removeHs = False
    for number, values in rows:
        smiles, error = values.get(mapping['smiles_column'], ('', ''))
        smiles = smiles.strip()
        if not smiles and not error:
            error = 'Missing SMILES text'
        if any(index >= len(metadata['columns']) for index in values):
            error = 'Row contains more fields than the header; check delimiters/header'
        molecule = None
        if not error:
            try:
                molecule = Chem.MolFromSmiles(smiles, parameters)
            except (ValueError, RuntimeError):
                pass
            if molecule is None or molecule.GetNumAtoms() == 0:
                molecule, error = None, 'Invalid or unsupported SMILES'
        name, name_error = values.get(mapping['name_column'], ('', ''))
        # Numeric IDs are useful labels, although numbers are never SMILES.
        # Formula values are deliberately blanked by the Excel reader.
        name = name.strip()
        if molecule is not None:
            if name:
                molecule.SetProp('_Name', name)
                molecule.SetProp('DockingUniversal_CompoundName', name)
            for column in metadata['columns']:
                value, cell_error = values.get(column['index'], ('', ''))
                if not cell_error:
                    molecule.SetProp(f"InputColumn{column['index'] + 1}:{column['label']}", value)
        yield number, name, smiles, error, molecule

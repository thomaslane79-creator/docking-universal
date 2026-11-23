"""Selected-run reports built from retained artifacts without changing runs."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .compound_identity import retained_compound_name

PDF_QUALITIES = (('Compressed', 'compressed'), ('High resolution', 'high-resolution'))


def _read(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream)


def _stage_reference(source, target):
    try:
        target.symlink_to(source, target_is_directory=source.is_dir())
    except OSError:
        # Windows may not permit symlinks for ordinary users.
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def selected_report(root, fallback=None):
    root = Path(root).resolve()
    try:
        receipt = _read(root / 'report' / 'compound_display_names.json')
        name = str(receipt.get('corrected_report') or '')
        if name and Path(name).name == name and name.lower().endswith('.pdf'):
            path = root / 'report' / name
            if path.is_file():
                return path
    except (OSError, ValueError, AttributeError):
        pass
    path = Path(fallback).resolve() if fallback else None
    if path and path.is_file() and path.parent == root / 'report':
        return path
    raise ValueError(f'No retained report is available for {root.name}.')


def available_run_reports(state):
    """Discover one report per retained run; corrected display copies win."""
    roots = {}
    for artifact in state.artifacts:
        if artifact.kind != 'screening_report':
            continue
        path = Path(artifact.path).resolve()
        if not path.is_file():
            continue
        root = path.parent.parent
        try:
            report = selected_report(root, path)
            inventory = _read(root / 'inputs' / 'compound_library_inventory.json')
            names = [retained_compound_name(root, item.get('compound_id'))
                     for item in inventory.get('compounds', []) if item.get('compound_id')]
        except (OSError, ValueError, TypeError, AttributeError):
            report, names = path, []
        roots[str(root)] = {'root': root, 'report': report, 'names': names}
    return list(roots.values())


def method_signature(root):
    """Fail closed when recorded methods or the original protocol are missing."""
    root = Path(root).resolve()
    try:
        manifest = _read(root / 'study_manifest.json')
        required = ('configured_engine', 'configured_engine_version', 'configured_docking_parameters',
                    'configured_locked_inputs', 'scientific_software', 'analysis',
                    'representatives', 'cluster_rmsd_angstrom', 'protocol_type')
        if any(manifest.get(key) in (None, '', {}) for key in required):
            raise ValueError('required method details are missing')
        protocol = root / 'inputs' / 'locked_protocol' / 'protocol.json'
        protocol_bytes = protocol.read_bytes()
        record = {key: manifest[key] for key in required}
        record['protocol_sha256'] = hashlib.sha256(protocol_bytes).hexdigest()
        return json.dumps(record, sort_keys=True, separators=(',', ':'))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f'Cannot verify the methods for {root.name}: {exc}') from exc


def require_matching_methods(roots):
    roots = [Path(root).resolve() for root in roots]
    if not roots:
        raise ValueError('Select at least one run.')
    signatures = [method_signature(root) for root in roots]
    if len(set(signatures)) != 1:
        raise ValueError('The selected runs do not have exactly matching recorded methods. Use separate run sections or individual reports.')
    return hashlib.sha256(signatures[0].encode()).hexdigest()


def _validate_output(output, sources):
    output = Path(output).expanduser().resolve()
    if output.suffix.lower() != '.pdf':
        raise ValueError('Choose a PDF filename.')
    if output in {Path(source).resolve() for source in sources}:
        raise ValueError('Choose a new file; original run reports cannot be overwritten.')
    if not output.parent.is_dir():
        raise ValueError('The output folder does not exist.')
    return output


def export_report(source, output, python_executable, report_script, quality):
    """Create a PDF copy from the figures retained with a completed report."""
    source = Path(source).resolve()
    output = _validate_output(output, [source])
    if quality not in dict(PDF_QUALITIES).values():
        raise ValueError('Choose a supported PDF quality.')
    root = source.parent.parent
    if not (root / 'report' / 'study_summary.json').is_file():
        raise ValueError(f'{source.name} has no retained report data for a new export.')
    with tempfile.TemporaryDirectory(prefix='.du-report-', dir=output.parent) as directory:
        assets = Path(directory)
        staged = assets / 'report.pdf'
        result = subprocess.run([
            str(python_executable), str(report_script), str(root), '--reuse-figures',
            '--pdf-quality', quality, '--report-assets-output', str(assets), '--out', str(staged),
        ], capture_output=True, text=True)
        if result.returncode or not staged.is_file():
            detail = result.stderr.strip() or result.stdout.strip() or 'no report produced'
            raise ValueError(f'{source.name} could not be exported: {detail[-1800:]}')
        os.replace(staged, output)
    return output


def combine_run_sections(reports, output, *, exported_reports=None):
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from xml.sax.saxutils import escape
    sources = [Path(path).resolve() for path in reports]
    if not sources:
        raise ValueError('Select at least one run.')
    output = _validate_output(output, sources)
    writer = PdfWriter()
    copies = sources if exported_reports is None else exported_reports
    for index, (source, copy) in enumerate(zip(sources, copies), 1):
        reader = PdfReader(copy)
        if reader.is_encrypted:
            raise ValueError(f'The report {source.name} is encrypted.')
        heading = BytesIO()
        styles = getSampleStyleSheet()
        SimpleDocTemplate(heading).build([
            Paragraph(escape(f'Run {index}: {source.parent.parent.name}'), styles['Title']),
            Spacer(1, 15),
            Paragraph(escape(str(source.parent.parent)), styles['BodyText']),
            Spacer(1, 10),
            Paragraph('The following pages are this run’s retained report. Its methods and provenance apply to this section.', styles['BodyText']),
        ])
        heading.seek(0)
        writer.append(PdfReader(heading))
        writer.append(reader, outline_item=source.parent.parent.name)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.pdf', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer.write(stream)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, output)
    return output


def export_run_sections(reports, output, python_executable, report_script, quality):
    output = _validate_output(output, reports)
    with tempfile.TemporaryDirectory(prefix='du-run-sections-') as directory:
        copies = [export_report(source, Path(directory) / f'run-{index}.pdf',
                                python_executable, report_script, quality)
                  for index, source in enumerate(reports, 1)]
        return combine_run_sections(reports, output, exported_reports=copies)


def build_merged_report(roots, reports, output, python_executable, report_script, *, quality='compressed'):
    """Regenerate one report with all compounds and explicit per-run provenance."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from xml.sax.saxutils import escape

    roots = [Path(root).resolve() for root in roots]
    reports = [Path(report).resolve() for report in reports]
    if len(roots) != len(reports):
        raise ValueError('Every selected run must have its retained report.')
    fingerprint = require_matching_methods(roots)
    output = _validate_output(output, reports)
    with tempfile.TemporaryDirectory(prefix='du-merged-report-') as directory:
        stage = Path(directory)
        (stage / 'report').mkdir()
        (stage / 'inputs').mkdir()
        (stage / 'compounds').mkdir()
        first = roots[0]
        for item in first.iterdir():
            if item.name not in {'report', 'inputs', 'compounds'}:
                _stage_reference(item, stage / item.name)
        for item in (first / 'inputs').iterdir():
            if item.name != 'compound_library_inventory.json':
                _stage_reference(item, stage / 'inputs' / item.name)
        summary = _read(first / 'report' / 'study_summary.json')
        summary['compounds'] = []
        inventory = {'compounds': []}
        for number, root in enumerate(roots, 1):
            run_summary = _read(root / 'report' / 'study_summary.json')
            source_inventory = _read(root / 'inputs' / 'compound_library_inventory.json')
            by_id = {str(item.get('compound_id')): item for item in source_inventory.get('compounds', [])}
            compounds = run_summary.get('compounds') or []
            if not compounds:
                raise ValueError(f'{root.name} has no retained compound results.')
            for compound in compounds:
                old = str(compound.get('compound_id') or '')
                if not old or old not in by_id or not (root / 'compounds' / old).is_dir():
                    raise ValueError(f'{root.name} has incomplete compound records.')
                new = f'run{number:03d}_{old}'
                label = f'{retained_compound_name(root, old)} (run {number}: {root.name})'
                _stage_reference(root / 'compounds' / old, stage / 'compounds' / new)
                summary['compounds'].append({**compound, 'compound_id': new, 'compound_name': label, 'user_display_name': label})
                inventory['compounds'].append({**by_id[old], 'compound_id': new, 'compound_name': label, 'user_display_name': label})
                for asset in (root / 'report').glob(old + '_*'):
                    if asset.is_file():
                        shutil.copy2(asset, stage / 'report' / (new + asset.name[len(old):]))
        old_ids = {str(row.get('compound_id') or '') for row in _read(first / 'inputs' / 'compound_library_inventory.json').get('compounds', [])}
        for asset in (first / 'report').iterdir():
            if asset.is_file() and asset.name not in {'study_summary.json', 'compound_display_names.json'} and not any(asset.name.startswith(key + '_') for key in old_ids if key):
                shutil.copy2(asset, stage / 'report' / asset.name)
        # Keep each run's results independent, while grouping identically named
        # compounds together in the combined report.
        summary['compounds'].sort(key=lambda row: (row['compound_name'].casefold(), row['compound_id']))
        inventory['compounds'].sort(key=lambda row: (row['compound_name'].casefold(), row['compound_id']))
        summary['compound_count'] = len(summary['compounds'])
        (stage / 'report' / 'study_summary.json').write_text(json.dumps(summary))
        (stage / 'inputs' / 'compound_library_inventory.json').write_text(json.dumps(inventory))
        merged = stage / 'merged.pdf'
        result = subprocess.run([str(python_executable), str(report_script), str(stage), '--reuse-figures', '--pdf-quality', quality, '--out', str(merged)], capture_output=True, text=True)
        if result.returncode or not merged.is_file():
            raise ValueError('Merged report generation failed: ' + (result.stderr.strip() or result.stdout.strip() or 'no report produced')[-1800:])
        cover = stage / 'sources.pdf'
        styles = getSampleStyleSheet()
        parts = [Paragraph('Combined screening report: source runs', styles['Title']), Spacer(1, 14),
                 Paragraph('These runs have identical recorded methods. Compounds are listed alphabetically and each result identifies its source run. Poses and clusters remain separate by run; they have not been pooled or reclustered.', styles['BodyText']), Spacer(1, 10)]
        for number, root in enumerate(roots, 1):
            parts += [Paragraph(escape(f'Run {number}: {root.name}'), styles['Heading2']),
                      Paragraph(escape(str(root)), styles['BodyText']), Spacer(1, 6)]
        parts += [Spacer(1, 10), Paragraph('Matching-method record: ' + fingerprint, styles['BodyText'])]
        SimpleDocTemplate(str(cover)).build(parts)
        writer = PdfWriter()
        writer.append(PdfReader(cover), outline_item='Source runs and matching methods')
        writer.append(PdfReader(merged), outline_item='Combined screening results')
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.pdf', delete=False) as stream:
            temporary = Path(stream.name)
            try:
                writer.write(stream)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        os.replace(temporary, output)
    return output

"""Verified, explicit reuse of a portable protocol in an otherwise fresh study."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

from docking_universal_bundle import protocol_can_screen, protocol_type, reconcile_protocol_engine
from ..events import EventType
from ..models import ArtifactRecord, CompletionStatus, ScientificAuthority
from ..state import RevisionConflictError


def _digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _member(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Invalid path in protocol bundle')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or ':' in value or str(path) != value:
        raise ValueError('Unsafe path in protocol bundle: ' + value)
    return value


def inspect_protocol_bundle(source):
    """Verify archive and locked input hashes without extracting or executing it."""
    source = Path(source).expanduser().resolve()
    if source.suffix.lower() != '.duprotocol' or not source.is_file():
        raise ValueError('Choose an existing .duprotocol bundle')
    before = _digest(source)
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > 20000 or sum(item.file_size for item in members) > 2 * 1024**3:
                raise ValueError('Protocol bundle exceeds the local import size limit')
            paths = {}
            for item in members:
                if item.is_dir():
                    _member(item.filename.rstrip('/'))
                    continue
                name = _member(item.filename)
                if name in paths or stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('Duplicate or symbolic-link entry in protocol bundle: ' + name)
                paths[name] = item
            if paths.get('bundle_manifest.json') is None or paths['bundle_manifest.json'].file_size > 8 * 1024**2:
                raise ValueError('Missing or oversized protocol bundle manifest')
            manifest = json.loads(archive.read('bundle_manifest.json'))
            if manifest.get('schema_name') != 'docking-universal-protocol-bundle' or manifest.get('schema_version') != 1:
                raise ValueError('Unsupported protocol bundle schema')
            inventory = {}
            for item in manifest.get('files', []):
                name = _member(item['path'])
                if name in inventory or name not in paths:
                    raise ValueError('Invalid protocol bundle inventory: ' + name)
                value = hashlib.sha256()
                with archive.open(name) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                        value.update(chunk)
                if value.hexdigest() != item.get('sha256'):
                    raise ValueError('Protocol bundle file failed verification: ' + name)
                inventory[name] = value.hexdigest()
            if set(inventory) != set(paths) - {'bundle_manifest.json'}:
                raise ValueError('Protocol bundle contains files without a verified inventory entry')
            protocol_name = _member(manifest['protocol'])
            if protocol_name not in inventory or paths[protocol_name].file_size > 16 * 1024**2:
                raise ValueError('Missing or oversized protocol record')
            record = json.loads(archive.read(protocol_name))
            if record.get('schema_name') != 'docking-universal-protocol' or record.get('schema_version') != 1:
                raise ValueError('Unsupported protocol record schema')
            if not protocol_can_screen(record):
                raise ValueError('Protocol is not authorized for screening')
            engine = reconcile_protocol_engine(record)
            base = PurePosixPath(protocol_name).parent

            def verify_locked(value, expected, label):
                name = str(base / _member(value))
                if not expected or inventory.get(name) != expected:
                    raise ValueError('Locked ' + label + ' failed bundle hash verification')

            locked = record.get('locked_inputs') or {}
            verify_locked(locked.get('receptor'), locked.get('receptor_sha256'), 'receptor')
            verify_locked(locked.get('box'), locked.get('box_sha256'), 'box')
            if locked.get('receptor_pdb'):
                verify_locked(locked['receptor_pdb'], locked.get('receptor_pdb_sha256'), 'receptor coordinates')
            for variant in ((record.get('receptor_state_sensitivity') or {}).get('variants') or {}).values():
                for key in ('receptor_pdb', 'receptor_pdbqt'):
                    if variant.get(key):
                        verify_locked(variant[key], variant.get(key + '_sha256'), 'receptor-state variant')
            regions = record.get('docking_regions') or locked.get('boxes') or []
            for region in [*(locked.get('boxes') or []), *regions]:
                if not isinstance(region, dict):
                    raise ValueError('Protocol regions require explicit locked box hashes')
                verify_locked(region.get('box'), region.get('box_sha256'), 'region')
            if regions and locked.get('boxes') and regions != locked['boxes']:
                raise ValueError('Protocol contains inconsistent locked region inventories')
    except (OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError('Invalid protocol bundle: ' + str(exc)) from None
    if _digest(source) != before:
        raise ValueError('Protocol bundle changed during verification')
    parameters = record.get('parameters') or {}
    if int(parameters.get('conformers_per_state', 0)) < 1 or not parameters.get('seeds'):
        raise ValueError('Protocol lacks complete conformer and repeat settings')
    return {
        'source': str(source), 'sha256': before, 'protocol_type': protocol_type(record),
        'target': record.get('target') or 'Not recorded', 'target_identity': record.get('target_identity') or {},
        'engine': engine, 'parameters': parameters, 'region_count': len(regions) or 1,
        'regions': regions, 'verified_files': len(inventory),
        'exploratory_authorization_required': protocol_type(record) != 'control-validated',
        'receptor_sha256': locked['receptor_sha256'], 'box_sha256': locked['box_sha256'],
        'receptor_modification_warning': (record.get('receptor_preparation') or {}).get('receptor_modification_warning'),
        'scientific_software': record.get('software') or {},
    }


def import_protocol_bundle(controller, study_id, source, reviewed_sha256, *, expected_revision, request_id):
    """Snapshot a reviewed bundle; never transfer a different engine's approval."""
    if expected_revision is None:
        raise ValueError('A state revision is required to import a protocol')
    state = controller.get_study(study_id)
    if state.workflow_data.get('protocol_import', {}).get('request_id') == request_id:
        return state
    if state.revision != expected_revision:
        raise RevisionConflictError('Study changed before protocol import; refresh and review again')

    def require_fresh(current):
        if current.jobs or current.decisions or current.artifacts or current.workflow_data.get('study_setup'):
            raise ValueError('Import requires a fresh study; create a new study instead of replacing existing work')

    require_fresh(state)
    preview = inspect_protocol_bundle(source)
    if preview['sha256'] != reviewed_sha256:
        raise ValueError('Protocol bundle changed after review; review it again before importing')
    # Copy before registering. A crash can leave an unreferenced snapshot, never
    # a registered bundle that still depends on the original source location.
    directory = controller.store.path_for(study_id).parent / 'inputs' / 'protocol'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (reviewed_sha256 + '.duprotocol')
    if target.exists() and _digest(target) != reviewed_sha256:
        raise ValueError('Existing imported bundle snapshot has changed')
    descriptor, name = tempfile.mkstemp(dir=directory, prefix='.import-', suffix='.duprotocol')
    os.close(descriptor)  # Windows must not retain an open temporary-file handle.
    temporary = Path(name)
    try:
        shutil.copyfile(preview['source'], temporary)
        copied = inspect_protocol_bundle(temporary)
        if copied['sha256'] != reviewed_sha256:
            raise ValueError('Protocol bundle changed while copying')
        if not target.exists():
            temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    if _digest(target) != reviewed_sha256:
        raise ValueError('Imported protocol snapshot failed verification')

    def mutation(current):
        require_fresh(current)
        current.artifacts.append(ArtifactRecord('imported-protocol-bundle', 'protocol_bundle', str(target),
                                               reviewed_sha256, 'Verified saved protocol imported into this study'))
        current.workflow_data['protocol_import'] = {**preview, 'snapshot': str(target), 'request_id': request_id}
        current.workflow_data['study_setup'] = {'pathway': 'reuse', 'protocol_bundle': str(target),
                                               'imported_source': preview['source'], 'engine': preview['engine']}
        current.workflow_data['completed_stages'] = ['protocol_import']
        current.workflow_data['next_stage'] = 'screening'
        current.completion_status = CompletionStatus.DRAFT
        current.scientific_authority = (ScientificAuthority.EXPLORATORY_NO_CONTROL
            if preview['exploratory_authorization_required'] else ScientificAuthority.CONTROL_APPROVED)
        controller._event(current, EventType.ARTIFACT_CREATED, 'Verified saved protocol imported',
                          explanation='The receptor, regions, engine and settings remain locked. No preparation or docking was run.',
                          technical={'source_sha256': reviewed_sha256, 'protocol_type': preview['protocol_type']})
    result, _ = controller.store.update(study_id, mutation, expected_revision=expected_revision)
    return result

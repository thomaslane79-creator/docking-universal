"""Preparation-time backend identity, portable with the exact receptor output.

Never infer historical versions from today's installation or a folder name.
The legacy suite exposes its version as literals in its ADFR package. Query
that package through the official launcher's own Python environment without
importing the molecular libraries or running another preparation.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

SCHEMA = 'docking-universal-receptor-backend-identity'
FILENAME = 'receptor_backend_identity.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned_file(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=digest(path))


def capture_adfr_identity(executable, *, timeout=10):
    """Read the version in the exact official wrapper's runtime, or mark unknown."""
    executable = Path(executable).resolve()
    record = dict(schema_name=SCHEMA, schema_version=1, software='ADFRsuite',
                  version='not recorded', identity_status='unavailable',
                  captured_utc=datetime.now(timezone.utc).isoformat(), executable=pinned_file(executable))
    try:
        wrapper = executable.read_text()
        match = re.search(r'^ADS_ROOT=["\']([^"\'\n]+)["\']\s*$', wrapper, re.M)
        entry_command = re.search(r'(?m)^\s*exec\s+\$python\s+\$pyflags\s+\$ADS_ROOT/CCSBpckgs/AutoDockTools/Utilities24/prepare_receptor4\.py(?:\s|$)', wrapper)
        if not match or not entry_command:
            raise ValueError('Unrecognized ADFRsuite launcher; version cannot be established')
        root = Path(match.group(1)).resolve()
        pythonsh = root / 'bin/pythonsh'
        # Validate the official companion wrapper uses the same suite root.
        runtime_wrapper = pythonsh.read_text()
        runtime_root = re.search(r'^ADS_ROOT=["\']([^"\'\n]+)["\']\s*$', runtime_wrapper, re.M)
        if not runtime_root or Path(runtime_root.group(1)).resolve() != root:
            raise ValueError('ADFRsuite runtime and receptor launcher roots differ')
        entrypoint = root / 'CCSBpckgs/AutoDockTools/Utilities24/prepare_receptor4.py'
        record['entrypoint'] = pinned_file(entrypoint)
        record['runtime_launcher'] = pinned_file(pythonsh)
        # Python 2-compatible code runs in the suite environment. imp locates
        # the package without importing ProDy or changing user configuration.
        code = """import ast, imp, json, os, sys
_, folder, _ = imp.find_module('ADFR')
source = os.path.join(folder, '__init__.py')
values = {}
for node in ast.parse(open(source).read()).body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in ('__version__', '__subversion__', '__revision__'):
                values[target.id] = ast.literal_eval(node.value)
version = str(values['__version__']) + '.' + str(values['__subversion__']) + str(values.get('__revision__', ''))
print('DU_BACKEND_IDENTITY ' + json.dumps(dict(version=version, version_source=source, runtime=sys.executable)))
"""
        result = subprocess.run([str(pythonsh), '-c', code], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=timeout)
        lines = [l[len('DU_BACKEND_IDENTITY '):] for l in result.stdout.splitlines()
                 if l.startswith('DU_BACKEND_IDENTITY ')]
        if result.returncode or len(lines) != 1:
            raise ValueError('ADFRsuite identity query failed: ' + (result.stderr or result.stdout)[-1500:])
        identity = json.loads(lines[0])
        if not re.fullmatch(r'[0-9]+\.[0-9]+[A-Za-z0-9.\-]*', identity['version']):
            raise ValueError('ADFRsuite runtime returned an invalid version')
        source = Path(identity['version_source']).resolve()
        if source != (root / 'CCSBpckgs/ADFR/__init__.py').resolve():
            raise ValueError('ADFR package came from outside the receptor launcher suite')
        record.update(version=identity['version'], version_source=pinned_file(source),
                      runtime=pinned_file(identity['runtime']), identity_status='recorded')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        record['detail'] = str(exc)
    return record


def bind_output(startup_audit, receptor_pdbqt, route, output):
    """Seal the identity captured before execution to the accepted output."""
    startup = json.loads(Path(startup_audit).read_text())
    identity = copy.deepcopy(startup['backend_identity'])
    # A tool changed during execution is not the tool whose identity was queried.
    for key in ('executable', 'entrypoint', 'runtime_launcher', 'version_source', 'runtime'):
        pin = identity.get(key)
        if pin and digest(pin['path']) != pin['sha256']:
            raise ValueError('ADFRsuite implementation changed during preparation: ' + key)
    source = startup['input']
    if digest(source['path']) != source['sha256']:
        raise ValueError('ADFRsuite receptor input changed during preparation')
    identity.update(prepared_receptor_sha256=digest(receptor_pdbqt), preparation_route=route,
                    input=source, startup_audit_sha256=digest(startup_audit))
    validate_identity(identity, digest(receptor_pdbqt))
    Path(output).write_text(json.dumps(identity, indent=2) + '\n')
    return identity


def validate_identity(record, receptor_sha256=None):
    if (not isinstance(record, dict) or record.get('schema_name') != SCHEMA
            or record.get('schema_version') != 1 or record.get('software') != 'ADFRsuite'):
        raise ValueError('Unsupported receptor backend identity record')
    if record.get('preparation_route') not in {'adfr_primary', 'adfr_legacy_linked_component_fallback'}:
        raise ValueError('Backend identity must name the actual ADFRsuite preparation route')
    if not re.fullmatch('[0-9a-f]{64}', str(record.get('prepared_receptor_sha256', ''))):
        raise ValueError('Backend identity requires a prepared receptor hash')
    if receptor_sha256 and record['prepared_receptor_sha256'] != receptor_sha256:
        raise ValueError('Backend identity belongs to a different prepared receptor')
    if record.get('identity_status') == 'recorded':
        if not re.fullmatch(r'[0-9]+\.[0-9]+[A-Za-z0-9.\-]*', str(record.get('version', ''))):
            raise ValueError('Backend identity requires the captured version')
        for key in ('executable', 'entrypoint', 'runtime_launcher', 'runtime', 'version_source', 'input'):
            pin = record.get(key) or {}
            if not pin.get('path') or not re.fullmatch('[0-9a-f]{64}', str(pin.get('sha256', ''))):
                raise ValueError('Backend identity requires complete implementation/input hashes')
    return record


def attach_retained_backend(preparation, preparation_root, receptor_pdbqt):
    result = copy.deepcopy(preparation)
    path = Path(preparation_root) / 'receptor' / FILENAME
    if path.is_file():
        identity = validate_identity(json.loads(path.read_text()), digest(receptor_pdbqt))
        result.update(backend_identity=identity, backend_identity_audit=str(path.resolve()),
                      backend_identity_audit_sha256=digest(path))
    return result

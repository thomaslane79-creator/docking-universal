"""Coordinate-only site exploration, deliberately independent of parameterization."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
from dataclasses import replace
from ..processes import ProcessRequest

def exploration_root(plan):
    return plan.output_root.with_name(plan.output_root.name + '-site-review')

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def exploration_request(preparation_plan, options):
    worker = Path(preparation_plan.request.command[0]).with_name('docking-universal-explore-sites.py')
    if not worker.is_file():
        raise FileNotFoundError('Coordinate-only site exploration worker is unavailable')
    engine = ('none' if options.site_mode == 'ligand' and not options.predict_pockets_with_ligand
              else 'p2rank' if options.pocket_engine == 'auto' else options.pocket_engine)
    if engine not in {'p2rank', 'none'}:
        raise ValueError('Site-first exploration currently requires P2Rank or the exact input-ligand site')
    return ProcessRequest(
        command=(sys.executable, str(worker), '--input', str(preparation_plan.structure_input.engine_pdb_path),
                 '--source-sha256', sha256(preparation_plan.structure_input.engine_pdb_path),
                 '--out', str(exploration_root(preparation_plan)), '--target', preparation_plan.receptor_pdb.stem,
                 '--engine', engine, '--maximum-pockets', str(options.max_pockets)),
        cwd=preparation_plan.request.cwd, environment=preparation_plan.request.environment,
        log_directory=preparation_plan.request.log_directory,
        log_name=preparation_plan.request.log_name + '-site-exploration', check=False)

def read_exploration(root):
    root = Path(root).resolve(); path = root / 'site_exploration.json'
    record = json.loads(path.read_text())
    if record.get('schema_name') != 'docking-universal-site-exploration' or record.get('schema_version') != 1:
        raise ValueError('Unsupported site-exploration record')
    if (record.get('parameterization_performed') is not False or record.get('docking_ready') is not False
            or record.get('status') != 'sites_available_not_parameterized'):
        raise ValueError('Site exploration must not imply successful receptor parameterization')
    source = Path(record['input_pdb'])
    if not source.is_file() or sha256(source) != record['input_sha256']:
        raise ValueError('Input coordinates changed after site exploration')
    receptor = root / record['prediction_receptor']
    if not receptor.resolve().is_relative_to(root) or receptor.is_symlink():
        raise ValueError('Prediction coordinates must be retained inside the site-review directory')
    if not receptor.is_file() or sha256(receptor) != record['prediction_receptor_sha256']:
        raise ValueError('Prediction coordinates changed after exploration')
    return record

def parameterization_plan(plan):
    """Prepare only; never predict again or overwrite the reviewed boxes."""
    environment = dict(plan.request.environment or {})
    environment['DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY'] = '1'
    return replace(plan, request=replace(plan.request, environment=environment))

class SiteExplorationService:
    def __init__(self, controller):
        self.controller = controller

    def run(self, study_id, plan, options, **run_options):
        from ..jobs import JobService
        from ..models import ArtifactRecord
        root = exploration_root(plan)
        Path(plan.request.cwd).mkdir(parents=True, exist_ok=True)
        result = JobService(self.controller).run(
            study_id, 'site_exploration', exploration_request(plan, options),
            required_outputs=(root / 'site_exploration.json',),
            progress_probe=lambda: ('site_exploration',
                'Finding docking regions from coordinates; receptor parameterization has not run.', None, None),
            **run_options)
        if result.status.value != 'completed':
            return result
        record = read_exploration(root)
        def register(state):
            state.workflow_data['site_exploration_root'] = str(root)
            state.workflow_data['receptor_parameterization_status'] = 'not_started'
            known = {a.id for a in state.artifacts}
            for identity, kind, path in (
                ('source-receptor-structure', 'source_receptor_structure', plan.structure_input.source_path),
                ('normalized-receptor-input', 'normalized_receptor_input', plan.structure_input.engine_pdb_path),
                ('structure-input-metadata', 'structure_input_metadata', plan.structure_input.metadata_path),
                ('coordinate-site-receptor', 'site_review_receptor_structure', root / record['prediction_receptor']),
                ('site-exploration-record', 'site_exploration_record', root / 'site_exploration.json'),
            ):
                if identity not in known:
                    state.artifacts.append(ArtifactRecord(identity, kind, str(path.resolve()), sha256(path),
                        'Coordinate-only site review; not a parameterized docking receptor'))
        self.controller.store.update(study_id, register)
        return result

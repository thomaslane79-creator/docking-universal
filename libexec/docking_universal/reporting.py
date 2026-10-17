"""Shared reader-facing tables for PDF, HTML and Markdown reports."""
import json


def engine_display_name(engine):
    return {'qvinaw':'QuickVina-W','vina':'AutoDock Vina',
            'adgpu':'AutoDock-GPU (AD4, experimental)'}.get(str(engine).lower(),str(engine))


def scoring_function_label(engine):
    return {'adgpu':'AD4','vina':'Vina','qvinaw':'Vina'}.get(str(engine).lower(),'Not recorded')


def engine_parameter_rows(engine, manifest, configured, regions=()):
    if str(engine).lower() != 'adgpu':
        return [['Exhaustiveness',manifest.get('exhaustiveness') or configured.get('exhaustiveness','NA')],
                ['Modes per job',manifest.get('num_modes') or configured.get('num_modes','NA')],
                ['Energy range',f"{manifest.get('energy_range_kcal_per_mol') or configured.get('energy_range_kcal_per_mol','NA')} kcal/mol"]]
    ad4 = configured.get('ad4') or {}
    if manifest.get('ad4_settings_json'):
        try: ad4 = json.loads(manifest['ad4_settings_json'])
        except (ValueError,TypeError): pass
    return [['Genetic runs per repeat',ad4.get('lga_runs','not recorded')],
            ['Heuristic evaluation cap',ad4.get('heuristic_cap','not recorded')]]


def protocol_summary_rows(engine, manifest, configured, *, seed_count=None):
    rows = [['Setting','Selected value'],['Docking program',engine_display_name(engine)]]
    if configured.get('ph') is not None: rows.append(['Ligand preparation pH',configured['ph']])
    if configured.get('conformers_per_state') is not None:
        rows.append(['Starting shapes per chemical state',configured['conformers_per_state']])
    if seed_count is None:
        seeds = configured.get('seeds')
        seed_count = len(seeds) if isinstance(seeds,(list,tuple)) else 'not recorded'
    rows.append(['Independent repeats per shape',seed_count])
    if configured.get('ensemble_seed') is not None: rows.append(['Starting random seed',configured['ensemble_seed']])
    return rows + engine_parameter_rows(engine,manifest,configured)


def compound_overview_rows(records, engine=None):
    rows = [['Ligand','Best docking score','Scoring function','Top cluster','Clusters','Status']]
    for result in records:
        score = result.get('best_energy_kcal_per_mol','Unavailable')
        rows.append([result['name'],f'{score} kcal/mol' if str(score) not in {'','Unavailable','NA'} else 'Unavailable',
            result.get('scoring_function') or scoring_function_label(engine),result.get('top_cluster') or 'Unavailable',
            result.get('cluster_count') or 'Unavailable',result.get('status','Unavailable')])
    return rows

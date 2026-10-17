#!/usr/bin/env python3
"""Complete previously unlaunched KNI-577 matched-coordinate audit."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from autodock_gpu_control_panel import ARMS, assess_run, command
from autodock_gpu_energy_reference import analyze
from autodock_gpu_trial import check_idle, digest, execute, save


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();root=a.root.resolve();out=a.out.resolve()
    prior=json.loads((root/'cutoff-investigation/tipranavir-actual-kernel/summary.json').read_text())
    if prior['status']!='completed_scoped_cutoff_reference_checks':raise ValueError('Tipranavir cutoff explanation has not passed')
    panel=json.loads((root/'control-panel-20261016_checked/summary.json').read_text())
    case=next(c for c in panel['cases'] if c['id']=='kni577_1mrw')
    reference=next(r for r in case['runs'] if r['arm']==ARMS[0] and r['repeat']==0)
    engine=root/'source-energy-audit/bin/adgpu_energy_audit_128'
    hashes={**case['input_hashes'],**case['map_hashes']}
    for path,expected in hashes.items():
        if digest(path)!=expected:raise ValueError('Retained KNI input changed')
    out.mkdir(parents=True,exist_ok=False);shutil.copy2(case['ligand'],out/'ligand.pdbqt')
    state={'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),'processes':[],
        'engine_sha256':digest(engine),'harness_sha256':digest(__file__),'source_hashes':hashes,
        'declared_gates':{'bounded_max_absolute_kcal_mol':.001,'run_winner_max_absolute_kcal_mol':.0001,
                         'all_population_max_scaled_error':.00001},
        'purpose':'One instrumented repeat captures retained arrays, not a new recovery seed or speed test.',
        'production_changed':False}
    path=out/'summary.json';save(path,state)
    try:
        check_idle();maps=Path(next(iter(case['map_hashes']))).parent/'receptor.maps.fld'
        process=execute(command(engine,maps,ARMS[0],41001),out,'adgpu',state,path,900)
        run=assess_run(case,out,process,41001,0,ARMS[0])
        matches={key:run[key]==reference[key] for key in ('pose_sha256','population_sha256','scores_sha256')}
        numerical=analyze(out);values=numerical['comparisons']['independent_gpu_formula_minus_gpu'];gates=state['declared_gates']
        passed=all(matches.values()) and values['both_absolute_energies_le_1000']['max']<=gates['bounded_max_absolute_kcal_mol'] and values['run_winners']['max']<=gates['run_winner_max_absolute_kcal_mol'] and numerical['matched_model_scaled_error']['all']['max']<=gates['all_population_max_scaled_error']
        state.update(same_seed_uninstrumented_matches=matches,chemistry_checks_passed=run['chemistry_checks_passed'],
            numerical_reference=numerical,declared_gates_passed=passed,pose_count=run['pose_count'])
        for file,expected in hashes.items():
            if digest(file)!=expected:raise ValueError('KNI source changed during audit')
        if not passed:raise ValueError('KNI numerical gate failed; retain results and investigate before integration')
        state.update(status='completed_scoped_numerical_checks',source_artifacts_unchanged=True)
    except BaseException as error:
        state.update(status='failed',error=str(error));raise
    finally:
        state['finished_utc']=datetime.now(timezone.utc).isoformat();save(path,state)
    print(json.dumps({'status':state['status'],'matches':matches,'energy_metrics':values,'scaled_error':numerical['matched_model_scaled_error']['all']}))


if __name__=='__main__':main()

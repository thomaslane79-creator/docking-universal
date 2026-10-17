#!/usr/bin/env python3
"""Native adapter acceptance in an isolated folder; original studies untouched."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from autodock_gpu_trial import ROOT, check_idle, digest, save
from autodock_gpu_repro import fingerprint


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    gpu=ROOT/'validation/runs/autodock-gpu-mac-20261016'
    panel=json.loads((gpu/'control-panel-20261016_checked/summary.json').read_text())
    case=next(c for c in panel['cases'] if c['id']=='indinavir_protease')
    prior=next(r for r in case['runs'] if r['arm']=='heuristic_autostop' and r['seed']==41001 and r['repeat']==0)
    inputs=out/'inputs';inputs.mkdir();ligands=inputs/'ligands';ligands.mkdir()
    receptor=inputs/'receptor.pdbqt';box=inputs/'box.conf'
    source_box=next(Path(path) for path in case['input_hashes'] if Path(path).suffix=='.conf')
    shutil.copy2(case['receptor'],receptor);shutil.copy2(source_box,box);shutil.copy2(case['ligand'],ligands/'ligand.pdbqt')
    config=out/'validation-runtime.json'
    save(config,{'schema':'docking-universal-adgpu-runtime-v1','integration_accepted':False,'validation_only':True,
        'executable':str(gpu/'source-gpu-candidate-guarded/bin/adgpu_guarded_128')})
    env=dict(os.environ,DOCKING_UNIVERSAL_ADGPU_CONFIG=str(config),DOCKING_UNIVERSAL_ADGPU_VALIDATION='1',
        DOCKING_UNIVERSAL_PYTHON=sys.executable,PYTHONPATH=str(ROOT/'libexec'),
        PATH=str(Path(sys.executable).parent)+os.pathsep+'/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin')
    command=[str(ROOT/'bin/docking-universal'),'dock','--engine','adgpu','--receptor',str(receptor),
        '--ligands',str(ligands),'--config',str(box),'--out',str(out/'docking'),'--seed','41001']
    state={'status':'running','phase':'native_adapter','started_utc':datetime.now(timezone.utc).isoformat(),
           'command':command,'production_installed':False,'original_input_hashes':case['input_hashes']}
    save(out/'summary.json',state)
    try:
        check_idle();result=subprocess.run(command,env=env,text=True,capture_output=True,timeout=180)
        save(out/'adapter-log.json',{'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode:raise ValueError('Native adapter failed; inspect adapter-log.json')
        native=out/'docking/ad4_native/ligand';actual=fingerprint(native,20)
        if actual['pose_sha256']!=prior['pose_sha256'] or actual['population_sha256']!=prior['population_sha256']:
            raise ValueError('Adapter native results differ from matched retained control')
        output=out/'docking/ligand_adgpu.pdbqt';text=output.read_text()
        if 'REMARK VINA RESULT:' in text or text.count('MODEL ')!=20:raise ValueError('Invalid normalized AD4 labeling/inventory')
        result=subprocess.run([str(ROOT/'bin/docking-universal'),'collect',str(output),'--out',str(out/'scores.csv')],env=env,text=True,capture_output=True)
        save(out/'collect-log.json',{'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode:raise ValueError('Common score collector failed')
        state.update(status='completed_native_adapter_acceptance',native_poses_identical=True,native_population_identical=True,
                     normalized_output_sha256=digest(output),poses=20,shared_collection_passed=True)
        for file,expected in case['input_hashes'].items():
            if digest(file)!=expected:raise ValueError('Original control input changed')
    except BaseException as error:
        state.update(status='failed',error=str(error));raise
    finally:
        state['finished_utc']=datetime.now(timezone.utc).isoformat();save(out/'summary.json',state)
    print(json.dumps(state))


if __name__=='__main__':main()

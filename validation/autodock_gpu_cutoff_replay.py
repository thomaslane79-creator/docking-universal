#!/usr/bin/env python3
"""Diagnostic scoring replay of retained raw population; no new search."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import numpy as np

from autodock_gpu_trial import check_idle, digest, save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();root=args.root.resolve();out=args.out.resolve()
    source=root/'control-panel-atomtype-audit/tipranavir_2o4p'
    previous=json.loads((root/'control-panel-atomtype-audit/summary.json').read_text())
    command=previous['processes'][0]['command'].copy()
    engine=root/'source-cutoff-replay/bin/autodock_gpu_128wi';command[0]=str(engine)
    hashes={str(f):digest(f) for f in source.glob('audit-*') if f.is_file()}
    out.mkdir(parents=True,exist_ok=False);shutil.copy2(source/'ligand.pdbqt',out/'ligand.pdbqt')
    state={'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),'source_hashes':hashes,
           'search_generations_requested':0,'purpose':'Replay raw saved population and capture native pair 6/16 cutoff in coordinate w lanes; diagnostic only.',
           'engine_sha256':digest(engine),'command':command,'production_changed':False}
    save(out/'summary.json',state)
    try:
        check_idle();env=dict(os.environ,DU_AUDIT_REPLAY_POPULATION=str(source/'audit-population.bin'),
                             DU_AUDIT_REPLAY_ENERGIES=str(source/'audit-search-energy.bin'))
        result=subprocess.run(command,cwd=out,env=env,text=True,capture_output=True,timeout=180)
        save(out/'native-log.json',{'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode or 'DIAGNOSTIC REPLAY:' not in result.stdout or 'All jobs ran without errors.' not in result.stdout:
            raise ValueError('Native scoring replay failed')
        meta=json.loads((source/'audit-metadata.json').read_text());shape=(meta['entities'],meta['atoms'],4)
        old=np.fromfile(source/'audit-gpu-coordinates.bin',np.float32).reshape(shape)
        new=np.fromfile(out/'audit-gpu-coordinates.bin',np.float32).reshape(shape)
        energies=np.fromfile(out/'audit-reevaluated-energy.bin',np.float32)
        old_energies=np.fromfile(source/'audit-reevaluated-energy.bin',np.float32)
        state.update(status='completed_diagnostic_replay',coordinates_identical=bool(np.array_equal(old[:,:,:3],new[:,:,:3])),
           max_energy_change_kcal_mol=float(np.max(np.abs(energies-old_energies))),
           target_entity_173={'distance':float(new[173,0,3]),'vdw_included':bool(new[173,1,3]),
                              'deltas':new[173,2:5,3].tolist(),'energy':float(energies[173]),'prior_energy':float(old_energies[173])})
        for file,expected in hashes.items():
            if digest(file)!=expected:raise ValueError('Retained source changed')
        state['source_unchanged']=True
    except BaseException as error:
        state.update(status='failed',error=str(error));raise
    finally:
        state['finished_utc']=datetime.now(timezone.utc).isoformat();save(out/'summary.json',state)
    print(json.dumps({k:v for k,v in state.items() if k not in ('source_hashes','command')}))


if __name__=='__main__':main()

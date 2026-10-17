#!/usr/bin/env python3
"""Probe retained pair distances at piecewise AD4 cutoffs; no docking."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import numpy as np

from autodock_gpu_trial import check_idle, digest, save
from autodock_gpu_energy_reference import analyze, intramolecular


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--probe",type=Path)
    parser.add_argument("--native-replay",type=Path)
    args=parser.parse_args();source=args.source.resolve();out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    meta=json.loads((source/"audit-metadata.json").read_text())
    pairs=np.asarray(meta['pairs'],dtype=int).reshape(-1,2)
    xyz=np.fromfile(source/'audit-gpu-coordinates.bin',np.float32).reshape(meta['entities'],meta['atoms'],4)
    checked_files={str(p):digest(p) for p in source.glob('audit-*') if p.is_file()}
    if bool(args.probe)==bool(args.native_replay):parser.error('Choose exactly one of --probe or --native-replay')
    state={"status":"running", "started_utc":datetime.now(timezone.utc).isoformat(),
        "source_hashes":checked_files,"harness_sha256":digest(__file__),
        "searches_launched":0,"production_changed":False,
        "declared_checks":{"distance_error_max_float32_ulps":4,
            "branch_disagreement_only_within_same_distance_bound":True,
            "bounded_max_absolute_kcal_mol":.001,"run_winner_max_absolute_kcal_mol":.0001,
            "all_population_max_scaled_error":.00001},
        "reference_boundary":"Independent double-precision energy terms, conditioned only at discontinuous cutoffs on separately probed native float distances. Probe distances must pass independent four-ULP checks. No entities excluded or energy gates relaxed. This is not a wholly double-precision independent scorer."}
    save(out/'summary.json',state)
    try:
        if args.native_replay:
            replay=args.native_replay.resolve()
            verification=json.loads((replay/'summary.json').read_text())
            if verification['status']!='completed_diagnostic_replay' or not verification['coordinates_identical'] or verification['max_energy_change_kcal_mol']!=0:
                raise ValueError('Instrumented native replay changed coordinates or energies')
            replay_xyz=np.fromfile(replay/'audit-gpu-coordinates.bin',np.float32).reshape(xyz.shape)
            replay_energy=np.fromfile(replay/'audit-reevaluated-energy.bin',np.float32)
            if not np.array_equal(replay_xyz[:,:,:3],xyz[:,:,:3]) or not np.array_equal(replay_energy,np.fromfile(source/'audit-reevaluated-energy.bin',np.float32)):
                raise ValueError('Replay no longer matches retained source')
            distances=np.fromfile(replay/'audit-native-pair-distances.bin',np.float32).reshape(meta['entities'],len(pairs))
            data=np.stack([distances]*4,axis=2)
            state['native_replay']={str(replay/name):digest(replay/name) for name in ['summary.json','audit-gpu-coordinates.bin','audit-reevaluated-energy.bin','audit-native-pair-distances.bin']}
        else:
            state['probe_sha256']=digest(args.probe)
            coords=np.stack((xyz[:,pairs[:,0]],xyz[:,pairs[:,1]]),axis=2).astype(np.float32)
            coords.tofile(out/'pairs.bin')
            command=[str(args.probe.resolve()),str(out/'pairs.bin'),str(out/'distances.bin'),str(meta['spacing']),str(meta['entities']*len(pairs))]
            check_idle();result=subprocess.run(command,text=True,capture_output=True)
            save(out/'probe-log.json',{"command":command,"returncode":result.returncode,"stdout":result.stdout,"stderr":result.stderr})
            if result.returncode or 'Apple M2 Max' not in result.stdout:raise ValueError('Native distance probe failed or wrong device')
            data=np.fromfile(out/'distances.bin',np.float32).reshape(meta['entities'],len(pairs),4)
        native=data[:,:,0].astype(float)
        reference=np.linalg.norm((xyz[:,pairs[:,0],:3].astype(float)-xyz[:,pairs[:,1],:3].astype(float))*meta['spacing'],axis=2)
        ulp=np.abs(np.spacing(reference.astype(np.float32))).astype(float)
        error=np.abs(native-reference)/ulp
        if not np.isfinite(data).all() or np.max(error)>4:raise ValueError('Native distances exceed declared independent precision bound')
        differences=[]
        for threshold in [8.,20.48]:
            mask=(native<float(np.float32(threshold)))!=(reference<threshold)
            for entity,pair in zip(*np.where(mask)):
                if abs(reference[entity,pair]-threshold)>4*ulp[entity,pair]:raise ValueError('Branch mismatch outside verified precision boundary')
                differences.append({"entity":int(entity),"pair_index":int(pair),"atom_indices_zero_based":pairs[pair].tolist(),
                     "cutoff_angstrom":threshold,"reference_distance":float(reference[entity,pair]),
                     "native_distance":float(native[entity,pair]),
                     "distance_error_ulps":float(error[entity,pair])})
        old=analyze(source);new=analyze(source,cutoff_distances=native)
        corrected=new['comparisons']['independent_gpu_formula_minus_gpu'];gates=state['declared_checks']
        passed=(corrected['both_absolute_energies_le_1000']['max']<=gates['bounded_max_absolute_kcal_mol'] and
                corrected['run_winners']['max']<=gates['run_winner_max_absolute_kcal_mol'] and
                new['matched_model_scaled_error']['all']['max']<=gates['all_population_max_scaled_error'])
        before=intramolecular(xyz[:,:,:3].astype(float),meta,'gpu_continuous').sum(1)
        after=intramolecular(xyz[:,:,:3].astype(float),meta,'gpu_continuous',cutoff_distances=native).sum(1)
        state.update(status='completed_scoped_cutoff_reference_checks' if passed else 'failed_energy_gate',
            max_distance_error_ulps=float(np.max(error)),branch_differences=differences,
            branch_conditioning_energy_changes=[{"entity":int(i),"reference_energy_change_kcal_mol":float(after[i]-before[i])} for i in sorted({row['entity'] for row in differences})],
            original_energy_metrics=old['comparisons']['independent_gpu_formula_minus_gpu'],
            original_scaled_error=old['matched_model_scaled_error'],corrected_energy_metrics=corrected,
            corrected_scaled_error=new['matched_model_scaled_error'],all_entities_retained=meta['entities'],
            winner_count=meta['runs'],declared_energy_gates_passed=passed,
            largest_absolute_corrected_residual=new['largest_absolute_matched_model_residual'])
        for file,expected in checked_files.items():
            if digest(file)!=expected:raise ValueError('Retained scientific audit changed')
        state['source_artifacts_unchanged']=True
        if not passed:raise ValueError('Energy gates remain failed after declared branch conditioning')
    except BaseException as error:
        state.update(status='failed',error=str(error));raise
    finally:
        state['finished_utc']=datetime.now(timezone.utc).isoformat();save(out/'summary.json',state)
    print(json.dumps({k:state[k] for k in ['status','max_distance_error_ulps','branch_differences','corrected_scaled_error']}))


if __name__=='__main__':main()

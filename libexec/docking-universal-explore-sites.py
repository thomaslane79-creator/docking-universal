#!/usr/bin/env python3
"""Suggest P2Rank pockets from coordinates without producing a docking receptor."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from docking_universal.p2rank_adapter import materialize_p2rank_candidates
from docking_universal.pocket_engines import build_p2rank_prediction_command
from docking_universal.receptor_filter import filter_receptor_pdb
from docking_universal.services.site_exploration import sha256

def run(args):
    source = args.input.expanduser().resolve(); out = args.out.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.pdb':
        raise ValueError('Site exploration requires the retained normalized PDB coordinates')
    if sha256(source) != args.source_sha256:
        raise ValueError('Source coordinates changed before exploration')
    if out.exists():
        raise ValueError('Site exploration requires a new output directory')
    out.mkdir(parents=True); cavity = out / 'cavity'; cavity.mkdir()
    receptor = out / 'coordinates' / (args.target + '.pdb')
    filtering = filter_receptor_pdb(source, receptor)
    record = {'schema_name':'docking-universal-site-exploration','schema_version':1,
              'input_pdb':str(source),'input_sha256':args.source_sha256,
              'prediction_receptor':str(receptor.relative_to(out)),
              'prediction_receptor_sha256':sha256(receptor),'coordinate_filter':filtering,
              'parameterization_performed':False,'docking_ready':False,
              'engine':args.engine,'network_used':False,'status':'running'}
    try:
        if args.engine == 'p2rank':
            prefix = Path(sys.prefix)
            launcher = (os.environ.get('DOCKING_UNIVERSAL_P2RANK') or shutil.which('prank')
                        or str(prefix/'share/docking-universal/p2rank-2.5.1/prank'))
            environment = dict(os.environ)
            java = os.environ.get('DOCKING_UNIVERSAL_JAVA')
            java_dir = Path(java).parent if java else prefix/'lib/jvm/bin'
            if java_dir.is_dir():environment['PATH']=str(java_dir)+os.pathsep+environment.get('PATH','')
            command = build_p2rank_prediction_command(launcher, receptor, cavity/'p2rank_output')
            result = subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,text=True,env=environment)
            (out/'p2rank.log').write_text(result.stdout+'\n'+result.stderr)
            record.update(command=list(command),p2rank_exit_code=result.returncode)
            if result.returncode:
                raise RuntimeError('P2Rank failed; see retained p2rank.log (not a parameterization failure)')
            predictions = sorted((cavity/'p2rank_output').glob('*_predictions.csv'))
            if len(predictions) != 1:
                raise ValueError('P2Rank did not produce exactly one prediction table')
            version = subprocess.run([launcher,'-v'],capture_output=True,text=True,env=environment,stdin=subprocess.DEVNULL)
            fields = version.stdout.strip().split()
            materialize_p2rank_candidates(predictions[0], receptor, cavity, args.target,
                maximum_pockets=args.maximum_pockets, p2rank_version=fields[1] if len(fields)>1 else 'not recorded')
        else:
            (cavity/'pocket_detection_provenance.json').write_text(json.dumps({
                'engine':'none','mode':'input_bound_ligand','prediction_executed':False,
                'site_definition':'input_bound_ligand','parameterization_performed':False})+'\n')
        record.update(status='sites_available_not_parameterized',
                      candidate_boxes=[str(p.relative_to(out)) for p in sorted(cavity.glob('*.conf'))])
    except BaseException as exc:
        record.update(status='failed',error_type=type(exc).__name__,reason=str(exc));raise
    finally:
        if sha256(source) != args.source_sha256:
            record.update(status='failed',reason='Source coordinates changed during exploration')
        (out/'site_exploration.json').write_text(json.dumps(record,indent=2)+'\n')
    if record['status'] != 'sites_available_not_parameterized':
        raise ValueError(record.get('reason', 'Site exploration did not complete safely'))
    print(json.dumps({'status':record['status'],'parameterization_performed':False,
                      'candidate_boxes':len(record['candidate_boxes'])}))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,type=Path);p.add_argument('--source-sha256',required=True)
    p.add_argument('--out',required=True,type=Path);p.add_argument('--target',required=True)
    p.add_argument('--engine',choices=['p2rank','none'],required=True)
    p.add_argument('--maximum-pockets',type=int,default=3)
    args=p.parse_args()
    if not args.target or Path(args.target).name != args.target or args.maximum_pockets < 0:
        p.error('Invalid target name or maximum pocket count')
    run(args)

if __name__=='__main__':main()

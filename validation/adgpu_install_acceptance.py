#!/usr/bin/env python3
"""Deploy only the accepted optional integration, with recoverable file backups."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from autodock_gpu_trial import ROOT, check_idle, digest, save
from docking_universal.ad4_gpu import PINNED_ENGINE_SHA256

FILES = '''docking-universal-run.py docking-universal-calibrate.py docking-universal-cluster-poses.py
docking-universal-redock-compare.py docking_universal_ligands.py docking_universal_bundle.py
docking-universal-render3d.py docking-universal-collect.py docking-universal-screen.py
docking-universal-report-figures.py docking-universal-finalize-protocol.py docking-universal-pdf-report.py
docking_universal_dock.py docking-universal-control docking_universal/protocol_finalization.py
docking_universal/orchestration.py docking_universal/jobs.py docking_universal/ad4_gpu.py
docking_universal/viewer/figure_labels.py docking_universal/gui/workflow_panels.py
docking_universal/gui/host_client.py docking_universal/gui/protocol_help.py docking_universal/gui/desktop.py
docking_universal/services/compound_identity.py docking_universal/services/ligand_library.py'''.split()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--install',action='store_true',required=True);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    acceptance=ROOT/'validation/runs/adgpu-integration-20261016'
    gates={'gui-ready/summary.json':'completed_gui_acceptance',
           'gui-ready/final-report-pose-audit-v5.json':'completed_report_and_pose_acceptance',
           'gui-ready/compact-callout-review/summary.json':'completed_compact_callout_rendering',
           'native-pymol-review/verification.json':'passed','runtime-guards/summary.json':'completed_runtime_guards',
           'final-regressions-release/summary.json':'passed','pdf-visual-qa.json':'passed'}
    for relative,expected in gates.items():
        if json.loads((acceptance/relative).read_text()).get('status')!=expected:
            raise ValueError('Unfinished acceptance gate: '+relative)
    visual=json.loads((acceptance/'pdf-visual-qa.json').read_text())
    gui=json.loads((acceptance/'gui-ready/summary.json').read_text())
    for key in ('protocol_report','screening_report'):
        if digest(gui[key])!=visual[key+'_sha256']:raise ValueError('PDF changed after visual QA')
    numerical=ROOT/'validation/runs/autodock-gpu-mac-20261016'
    if json.loads((numerical/'cutoff-investigation/tipranavir-actual-kernel/summary.json').read_text())['status']!='completed_scoped_cutoff_reference_checks':
        raise ValueError('Numerical reference gate missing')
    if json.loads((numerical/'kni-numerical-followup/summary.json').read_text())['status']!='completed_scoped_numerical_checks':
        raise ValueError('KNI numerical gate missing')
    source_engine=numerical/'source-gpu-candidate-guarded/bin/adgpu_guarded_128'
    if digest(source_engine)!=PINNED_ENGINE_SHA256:raise ValueError('GPU candidate changed')
    check_idle()
    prefix=Path('/opt/anaconda3/envs/docking-universal');destination=prefix/'libexec/docking-universal'
    engine=prefix/'share/docking-universal/adgpu/adgpu_guarded_128'
    descriptor=Path.home()/'.config/docking-universal/adgpu.json'
    original_source=Path(gui['source_state']);original_hash=digest(original_source)
    vina=Path('/opt/anaconda3/envs/docking-universal-vina/bin/vina');vina_hash=digest(vina)
    record={'status':'installing','acceptance_gates':{key:digest(acceptance/key) for key in gates},
            'files':[],'descriptor':str(descriptor),'executable':str(engine),'engine_sha256':PINNED_ENGINE_SHA256,
            'original_study_sha256':original_hash,'vina_executable_sha256':vina_hash,'default_engine':'vina'}
    backup=out/'backup';backup.mkdir();old_descriptor=descriptor.read_bytes() if descriptor.is_file() else None
    def publish_copy(source,target):
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.ad4-install-new')
        shutil.copy2(source,temporary);temporary.replace(target)
    try:
        for relative in FILES:
            source=ROOT/'libexec'/relative;target=destination/relative
            row={'relative':relative,'source_sha256':digest(source),'installed_before_sha256':digest(target) if target.is_file() else None}
            if target.is_file():
                saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            publish_copy(source,target)
            if digest(target)!=row['source_sha256']:raise ValueError('Installed hash mismatch: '+relative)
            record['files'].append(row)
        if engine.is_file() and digest(engine)!=PINNED_ENGINE_SHA256:raise ValueError('Existing GPU runtime differs; refusing overwrite')
        publish_copy(source_engine,engine)
        if old_descriptor is not None:(backup/'runtime-descriptor.json').write_bytes(old_descriptor)
        descriptor.parent.mkdir(parents=True,exist_ok=True)
        temporary=descriptor.with_suffix('.json.new')
        save(temporary,{'schema':'docking-universal-adgpu-runtime-v1','integration_accepted':True,
                       'validation_only':False,'executable':str(engine),'acceptance_record':str(out/'summary.json'),
                       'scope':'Experimental dry rigid-receptor AD4 on locally validated Apple Silicon OpenCL 128-work-item build'})
        temporary.replace(descriptor)  # activate only after the complete file set is installed
        env={**os.environ,'PYTHONPATH':str(destination),'DOCKING_UNIVERSAL_CLI':str(prefix/'bin/docking-universal'),
             'DOCKING_UNIVERSAL_LIBEXEC':str(destination),'DOCKING_UNIVERSAL_PYTHON':str(prefix/'bin/python'),
             'PATH':str(prefix/'bin')+':/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin'}
        env.pop('DOCKING_UNIVERSAL_ADGPU_CONFIG',None);env.pop('DOCKING_UNIVERSAL_ADGPU_VALIDATION',None)
        code='import json,docking_universal.ad4_gpu as a;from docking_universal.protocol_finalization import FinalizationSettings;print(json.dumps({"module":a.__file__,"available":a.available(),"runtime":a.runtime_descriptor(),"default_engine":FinalizationSettings().engine}))'
        result=subprocess.run([str(prefix/'bin/python'),'-c',code],env=env,text=True,capture_output=True,check=True)
        smoke=json.loads(result.stdout)
        if not smoke['available'] or smoke['default_engine']!='vina' or Path(smoke['module'])!=destination/'docking_universal/ad4_gpu.py':
            raise ValueError('Installed runtime/default smoke failed')
        record['runtime_smoke']=smoke
        fixture=acceptance/'runtime-guards/native'
        command=json.loads((fixture/'summary.json').read_text())['command'];command[0]=str(prefix/'bin/docking-universal')
        native={str(p):digest(p) for p in (fixture/'docking/ad4_native/ligand').iterdir() if p.is_file()}
        result=subprocess.run(command+['--skip-existing'],env=env,capture_output=True,text=True,timeout=30)
        save(out/'installed-skip.json',{'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode or 'skip  ligand' not in result.stdout or any(digest(path)!=value for path,value in native.items()):
            raise ValueError('Installed completed-result skip failed or changed native data')
        if digest(original_source)!=original_hash or digest(vina)!=vina_hash:raise ValueError('Existing user study or Vina changed')
        if any(digest(destination/row['relative'])!=row['source_sha256'] for row in record['files']):raise ValueError('Installed files changed during smoke')
        record.update(status='installed_core_acceptance_passed',installed_files_hash_verified=True,
                      installed_skip_without_docking=True,user_study_unchanged=True,vina_unchanged=True)
    except BaseException as exc:
        record.update(status='failed',error=str(exc),activation_rolled_back=True)
        if old_descriptor is None:
            if descriptor.is_file():shutil.move(str(descriptor),str(out/'failed-runtime-descriptor.json'))
        else:descriptor.write_bytes(old_descriptor)
        for row in record['files']:
            saved=backup/row['relative']
            if saved.is_file():publish_copy(saved,destination/row['relative'])
        raise
    finally:save(out/'summary.json',record)
    print(json.dumps({key:record[key] for key in ('status','executable','default_engine','user_study_unchanged','vina_unchanged')},indent=2))


if __name__=='__main__':main()

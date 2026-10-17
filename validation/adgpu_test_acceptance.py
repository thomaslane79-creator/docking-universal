#!/usr/bin/env python3
"""Retain final regression logs for the optional engine integration."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SCIENTIFIC='test_ad4_gpu test_autodock_gpu_energy_reference test_dock_runner test_protocol_finalization test_protocol_finalization_integration test_protocol_types test_protocol_workflow test_screening_service test_screening_workflow test_retained_report_artifacts test_multisite_report_figures test_control_pose_landscape test_ligand_library test_ligand_input test_process_adapter test_job_service test_host_client test_run_selection test_report_cavity'
GUI='test_workflow_panels test_desktop_workspace test_linked_pose_review test_cluster_contacts test_embedded_pymol_adapter test_image_export test_ligand_library_panel'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'PYTHONPATH':str(ROOT/'libexec')+os.pathsep+str(ROOT/'tests'),'QT_QPA_PLATFORM':'offscreen',
         'PATH':'/opt/anaconda3/envs/docking-universal/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin'}
    record={'status':'running','suites':[]}
    def save():(out/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    save()
    for label,python,names in (('scientific','/opt/anaconda3/envs/docking-universal/bin/python',SCIENTIFIC),
                              ('gui','/opt/anaconda3/envs/docking-universal-gui-next/bin/python',GUI)):
        command=[python,'-m','unittest','-v',*names.split()]
        with (out/(label+'.log')).open('w') as log:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        text=(out/(label+'.log')).read_text();match=re.search(r'Ran (\d+) tests? in ([\d.]+)s',text)
        row={'suite':label,'command':command,'returncode':result.returncode,'tests':int(match[1]) if match else None,
             'seconds':float(match[2]) if match else None,'passed':result.returncode==0}
        record['suites'].append(row);save()
        if result.returncode:
            record['status']='failed';save();raise SystemExit(label+' regression failed; inspect retained log')
    record['status']='passed';record['total_tests']=sum(r['tests'] for r in record['suites']);save()
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()

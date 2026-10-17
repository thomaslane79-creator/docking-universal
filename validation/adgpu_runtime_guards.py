#!/usr/bin/env python3
"""Native skip/failure/cancellation acceptance; deliberately isolated from user studies."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from autodock_gpu_trial import ROOT, check_idle, digest, save
from docking_universal.application import StudyController
from docking_universal.jobs import JobService
from docking_universal.processes import ProcessRequest
from docking_universal.state import JsonStudyStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    state={'status':'running','phase':'native_skip_fixture'};save(out/'summary.json',state)
    env=dict(os.environ,DOCKING_UNIVERSAL_PYTHON=sys.executable,PYTHONPATH=str(ROOT/'libexec'),
        DOCKING_UNIVERSAL_CLI=str(ROOT/'bin/docking-universal'),DOCKING_UNIVERSAL_LIBEXEC=str(ROOT/'libexec'),
        PATH=str(Path(sys.executable).parent)+':/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin')
    try:
        check_idle()
        # One bounded native fixture is necessary to test actual completed-skip
        # behavior under the final provenance checks, not another efficacy trial.
        result=subprocess.run([sys.executable,str(ROOT/'validation/adgpu_integration.py'),'--out',str(out/'native')],env=env,capture_output=True,text=True,timeout=180)
        save(out/'fixture-log.json',{'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode:raise ValueError('Native guard fixture failed')
        native=out/'native';record=json.loads((native/'summary.json').read_text());command=record['command']
        native_files={str(p):{'sha256':digest(p),'mtime_ns':p.stat().st_mtime_ns}
            for p in (native/'docking/ad4_native/ligand').iterdir() if p.is_file()}
        result=subprocess.run(command+['--skip-existing'],env=env,capture_output=True,text=True,timeout=30)
        save(out/'skip-log.json',{'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode or 'skip  ligand' not in result.stdout:raise ValueError('Completed AD4 skip failed')
        if any(digest(p)!=v['sha256'] or Path(p).stat().st_mtime_ns!=v['mtime_ns'] for p,v in native_files.items()):
            raise ValueError('Skipping modified or reran native outputs')
        state['completed_skip_without_search']=True
        def changed_command(folder):
            copied=list(command);copied[copied.index('--out')+1]=str(folder);return copied
        # Integrity and unsupported-input failures are all before any search.
        damaged=out/'tampered-output';shutil.copytree(native/'docking',damaged)
        output=damaged/'ligand_adgpu.pdbqt';output.write_text(output.read_text()+'\nREMARK TEST TAMPER\n')
        result=subprocess.run(changed_command(damaged)+['--skip-existing'],env=env,capture_output=True,text=True,timeout=30)
        save(out/'tamper-log.json',{'returncode':result.returncode,'stderr':result.stderr})
        if not result.returncode or 'skipped result changed' not in result.stderr:raise ValueError('Tampered output was accepted')
        state['tampered_output_rejected']=True
        fail_env={**env,'DOCKING_UNIVERSAL_AUTOGRID':'/usr/bin/false'}
        result=subprocess.run(changed_command(out/'map-failure'),env=fail_env,capture_output=True,text=True,timeout=30)
        save(out/'map-failure-log.json',{'returncode':result.returncode,'stderr':result.stderr})
        if not result.returncode or list((out/'map-failure').glob('ad4_native/*')):raise ValueError('AutoGrid failure did not stop before search')
        state['native_map_failure_without_fallback']=True
        # Exercise the same durable JobService and process-group cancellation
        # used by the GUI, after a real native GPU process begins.
        state['phase']='native_cancellation';save(out/'summary.json',state)
        cancelled=out/'cancelled';cancel_command=changed_command(cancelled)+['--ad4-settings',json.dumps({'lga_runs':100,'heuristic_cap':100_000_000,'autostop':False})]
        controller=StudyController(JsonStudyStore(out/'state'))
        controller.create_study('native-cancel','Native AD4 cancellation acceptance')
        cancellation=threading.Event();results=[];errors=[]
        def work():
            try:
                results.append(JobService(controller).run('native-cancel','docking',ProcessRequest(
                    command=cancel_command,environment=env,log_directory=out/'cancel-logs',log_name='native',check=False),
                    cancel_event=cancellation))
            except BaseException as exc:errors.append(str(exc))
        worker=threading.Thread(target=work);worker.start()
        native_log=cancelled/'ad4_native/ligand/adgpu.log'
        observed=False;deadline=time.monotonic()+30
        try:
            while worker.is_alive() and time.monotonic()<deadline:
                if native_log.is_file() and 'OpenCL device:' in native_log.read_text():
                    observed=True;break
                time.sleep(.02)
        finally:
            cancellation.set();worker.join(15)
        if worker.is_alive() or errors or not observed or not results or results[0].status.value!='cancelled':
            raise ValueError('Actual native cancellation not confirmed: '+str(errors))
        job=controller.get_study('native-cancel').jobs[-1]
        if job.status.value!='cancelled' or controller.get_study('native-cancel').active_job:
            raise ValueError('Cancellation did not persist terminal state')
        # No completed normalized result may be mistaken for cancellation success.
        if list(cancelled.glob('*_adgpu.pdbqt')):raise ValueError('Cancelled native search published completed output')
        result=subprocess.run(cancel_command+['--skip-existing'],env=env,capture_output=True,text=True,timeout=30)
        save(out/'cancelled-resume-rejection.json',{'returncode':result.returncode,'stderr':result.stderr})
        if not result.returncode or 'Incomplete or failed AD4 batch' not in result.stderr:
            raise ValueError('Cancelled partial job could be silently restarted')
        processes=subprocess.run(['ps','-axo','pid=,command='],text=True,capture_output=True,check=True).stdout
        leftovers=[line for line in processes.splitlines() if str(cancelled) in line or ('adgpu_guarded_128' in line and '--ffile' in line)]
        if leftovers:raise ValueError('Owned native process remained after cancellation: '+str(leftovers))
        state.update(status='completed_runtime_guards',phase='completed',native_gpu_observed_before_cancel=True,
                     native_cancellation_terminal=True,cancelled_output_not_published=True,
                     cancelled_batch_not_restarted=True,no_native_orphan=True)
        save(out/'cancel-result.json',asdict(results[0]))
    except BaseException as exc:
        state.update(status='failed',error=str(exc));raise
    finally:save(out/'summary.json',state)
    print(json.dumps(state,indent=2))


if __name__=='__main__':main()
